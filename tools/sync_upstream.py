#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 Hello-CTF 上游同步文档更新。

本仓库由 ProbiusOfficial/Hello-CTF 二次创作而来，但两边分别维护，不能直接
`git merge`（历史不共享、目录与页面也有本地定制）。该工具用「基线快照」做三方比较：

    基线（.sync/baseline.json，记录上次同步时上游各文件的 blob SHA）
      × 上游最新（临时 fetch，只取目录树）
      × 本地工作区

据此把差异分为「可安全同步」「需人工处理」「本地已删除」等类别。只有「上游改了、
而本地仍与基线一致」的文件才会被自动写入，本地改动过的文件一律不覆盖。

常用命令：

    python tools/sync_upstream.py check        # 只生成报告，不改文件
    python tools/sync_upstream.py apply        # 在新分支上应用安全更新并提交
    python tools/sync_upstream.py init ...     # 重新生成基线（谨慎）

依赖：Python 3.9+、git。Windows 下如果系统 git 的 TLS 有问题，可指定：
    set SYNC_GIT=D:\\Git\\cmd\\git.exe
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / ".sync" / "config.json"
BASELINE_PATH = ROOT / ".sync" / "baseline.json"
DEFAULT_REPORT = ".sync/reports/upstream-sync.md"

GIT = os.environ.get("SYNC_GIT") or shutil.which("git") or "git"

# 状态 → 报告中的人类可读标签
STATUS_LABELS = {
    "added": "上游新增（可同步）",
    "updated": "上游更新（可同步）",
    "conflict": "双方都改过（需人工）",
    "conflict-added": "两边各自新增（需人工）",
    "locally-deleted": "本地已删除（跳过）",
    "upstream-deleted": "上游已删除（默认跳过）",
    "conflict-deleted": "上游删除但本地有改动（需人工）",
    "in-sync": "内容一致",
    "excluded": "命中排除规则（跳过）",
}
APPLY_STATUSES = {"added", "updated"}


class SyncError(RuntimeError):
    """工具可控的失败，统一转成退出码 2。"""


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------


def log(msg: str = "") -> None:
    print(msg, flush=True)


def git(args, cwd=ROOT, check=True) -> bytes:
    """运行 git，返回原始 bytes（路径/内容都可能是 UTF-8 中文）。"""
    proc = subprocess.run([GIT, *args], cwd=str(cwd), capture_output=True)
    if check and proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        raise SyncError("git %s 失败：%s" % (" ".join(args), err or "未知错误"))
    return proc.stdout


def blob_sha1(data: bytes) -> str:
    """与 `git hash-object` 相同的 blob SHA1。"""
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def glob_to_regex(pattern: str) -> str:
    """把 docs/**、docs/*.md 这类 glob 转成路径匹配正则（`**` 可跨目录）。"""
    i, out = 0, ["^"]
    while i < len(pattern):
        ch = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif ch == "*":
            out.append("[^/]*")
            i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(ch))
            i += 1
    out.append("$")
    return "".join(out)


class Matcher:
    def __init__(self, include, exclude):
        self.include = [re.compile(glob_to_regex(p)) for p in include]
        self.exclude = [re.compile(glob_to_regex(p)) for p in exclude]

    def included(self, path: str) -> bool:
        return any(rx.match(path) for rx in self.include)

    def excluded(self, path: str) -> bool:
        return any(rx.match(path) for rx in self.exclude)

    def in_scope(self, path: str) -> bool:
        return self.included(path) and not self.excluded(path)


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise SyncError("缺少配置文件：%s" % CONFIG_PATH)
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SyncError("配置文件 JSON 解析失败：%s" % exc) from exc
    for key in ("upstream", "include", "exclude"):
        if key not in cfg:
            raise SyncError("配置缺少字段：%s" % key)
    return cfg


def load_baseline() -> dict:
    if not BASELINE_PATH.exists():
        raise SyncError(
            "缺少基线文件：%s\n首次使用请先运行 `python tools/sync_upstream.py init`。"
            % BASELINE_PATH
        )
    try:
        data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SyncError("基线 JSON 解析失败：%s" % exc) from exc
    if "files" not in data or not isinstance(data["files"], dict):
        raise SyncError("基线格式不正确：缺少 files 映射")
    return data


def write_baseline(files: dict, commit: str, commit_date: str | None = None) -> None:
    cfg = load_config()
    payload = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "upstream": {
            "repo": cfg["upstream"]["repo"],
            "branch": cfg["upstream"].get("branch", "main"),
            "commit": commit,
            "commit_date": commit_date,
        },
        "files": {p: files[p] for p in sorted(files)},
    }
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=0) + "\n", encoding="utf-8"
    )
    log("已写入基线：%s（上游 %s，文件 %d 个）" % (BASELINE_PATH, commit[:12], len(files)))


# --------------------------------------------------------------------------
# 读取三方状态
# --------------------------------------------------------------------------


def list_tree(repo: Path, rev: str, prefix: str = "docs") -> dict:
    """读取某个 revision 下 docs/ 的 {path: blob_sha}，不需要下载 blob。"""
    out = git(["-C", str(repo), "ls-tree", "-r", "-z", rev, "--", prefix])
    result = {}
    for entry in out.split(b"\0"):
        if not entry:
            continue
        meta, path = entry.split(b"\t", 1)
        mode, obj_type, sha = meta.split(b" ")
        if obj_type != b"blob":
            continue
        result[path.decode("utf-8", "surrogateescape")] = sha.decode("ascii")
    return result


def local_docs_map() -> dict:
    """本地工作区 docs/ 下所有文件的 {path: blob_sha}。"""
    docs = ROOT / "docs"
    if not docs.is_dir():
        raise SyncError("找不到 docs 目录：%s" % docs)
    result = {}
    for path in docs.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        try:
            result[rel] = blob_sha1(path.read_bytes())
        except OSError as exc:
            raise SyncError("读取文件失败：%s（%s）" % (rel, exc)) from exc
    return result


def fetch_upstream(cfg: dict, retries: int = 3) -> str:
    """fetch 上游分支，返回 commit SHA。先试 blobless，失败再退回普通 fetch。"""
    url = cfg["upstream"]["repo"]
    branch = cfg["upstream"].get("branch", "main")
    attempts = [
        ["fetch", "--no-tags", "--depth=1", "--filter=blob:none", url, branch],
        ["fetch", "--no-tags", "--depth=1", url, branch],
    ]
    last_error = None
    for _ in range(max(1, retries)):
        for args in attempts:
            try:
                git(args)
                return git(["rev-parse", "FETCH_HEAD"]).decode().strip()
            except SyncError as exc:
                last_error = exc
    raise SyncError(
        "拉取上游失败（%s）。请检查网络/git TLS 配置，或用 --upstream-commit 指定已\n"
        "存在的 commit，或设置 SYNC_GIT 指向可用的 git。最后错误：%s"
        % (url, last_error)
    )


def resolve_commit(rev: str) -> str:
    try:
        return git(["rev-parse", rev + "^{commit}"]).decode().strip()
    except SyncError as exc:
        raise SyncError("无法解析 commit：%s" % rev) from exc


def commit_date(rev: str) -> str | None:
    try:
        out = git(["show", "-s", "--format=%cI", rev]).decode().strip()
        return out or None
    except SyncError:
        return None


# --------------------------------------------------------------------------
# 分类
# --------------------------------------------------------------------------


def classify(baseline: dict, upstream: dict, local: dict, matcher: Matcher):
    """三方比较，返回按状态分组的记录列表。"""
    base = baseline["files"]
    all_paths = set(base) | set(upstream) | set(local)
    entries = []
    for path in sorted(all_paths):
        if not matcher.included(path):
            continue
        b, u, l = base.get(path), upstream.get(path), local.get(path)
        if matcher.excluded(path):
            if u != b or (b is None and u is not None):
                entries.append(_entry("excluded", path, b, u, l))
            continue
        if u == b:
            continue  # 上游没动，本地怎么改都与同步无关
        if u is None:
            if l is None:
                continue
            status = "upstream-deleted" if l == b else "conflict-deleted"
        elif b is None:
            if l is None:
                status = "added"
            elif l == u:
                status = "in-sync"
            else:
                status = "conflict-added"
        else:
            if l is None:
                status = "locally-deleted"
            elif l == b:
                status = "updated"
            elif l == u:
                status = "in-sync"
            else:
                status = "conflict"
        entries.append(_entry(status, path, b, u, l))
    return entries


def _entry(status: str, path: str, base_sha, upstream_sha, local_sha) -> dict:
    return {
        "status": status,
        "path": path,
        "baseline": base_sha,
        "upstream": upstream_sha,
        "local": local_sha,
    }


# --------------------------------------------------------------------------
# 报告
# --------------------------------------------------------------------------


def nav_pages() -> set:
    """解析 mkdocs.yml nav，收集出现的 .md 页面（相对 docs/）。"""
    path = ROOT / "mkdocs.yml"
    if not path.exists():
        return set()
    pages = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.search(r":\s*([A-Za-z0-9_./-]+\.md)\s*$", line)
        if m:
            pages.add(m.group(1))
        else:
            m = re.match(r"\s*-\s+([A-Za-z0-9_./-]+\.md)\s*$", line)
            if m:
                pages.add(m.group(1))
    return pages


def build_report(entries, baseline: dict, upstream_commit: str, local_branch: str,
                 local_head: str, nav_missing: list) -> str:
    groups = {}
    for entry in entries:
        groups.setdefault(entry["status"], []).append(entry)

    lines = []
    lines.append("# Hello-CTF 上游同步报告")
    lines.append("")
    lines.append("- 生成时间：%s" % datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z"))
    lines.append("- 本地：分支 `%s` @ `%s`" % (local_branch, local_head[:12]))
    lines.append(
        "- 基线：上游 `%s` @ `%s`"
        % (baseline.get("upstream", {}).get("repo", "?"),
           str(baseline.get("upstream", {}).get("commit", "?"))[:12])
    )
    lines.append("- 上游最新：`%s`" % upstream_commit[:12])
    lines.append("")

    lines.append("## 汇总")
    lines.append("")
    lines.append("| 状态 | 数量 |")
    lines.append("| --- | ---: |")
    for status in (
        "added", "updated", "conflict", "conflict-added", "conflict-deleted",
        "locally-deleted", "upstream-deleted", "in-sync", "excluded",
    ):
        if status in groups:
            lines.append("| %s | %d |" % (STATUS_LABELS[status], len(groups[status])))
    if not groups:
        lines.append("| 无差异 | 0 |")
    lines.append("")

    def section(title: str, statuses, note: str = "") -> None:
        rows = [e for s in statuses for e in groups.get(s, [])]
        if not rows:
            return
        lines.append("## %s（%d）" % (title, len(rows)))
        lines.append("")
        if note:
            lines.append(note)
            lines.append("")
        lines.append("| 文件 | 状态 |")
        lines.append("| --- | --- |")
        for entry in rows:
            lines.append("| `%s` | %s |" % (entry["path"], STATUS_LABELS[entry["status"]]))
        lines.append("")

    section(
        "可安全同步",
        ["added", "updated"],
        "这些文件上游有变化、本地与基线一致，`apply` 会写入它们。",
    )
    section(
        "需人工处理",
        ["conflict", "conflict-added", "conflict-deleted"],
        "本地也改过（或两边各自新增），工具不会覆盖，请手动合并后更新基线。",
    )
    section("本地已删除", ["locally-deleted"], "上游有变化但本地删除了该文件，保持现状。")
    section("上游已删除", ["upstream-deleted"], "默认不删除本地文件；确认后可加 `--prune`。")
    section("命中排除规则", ["excluded"], "由 `.sync/config.json` 的 `exclude` 控制，工具不处理。")
    section("已一致", ["in-sync"], "上游和本地内容相同，无需处理。")

    if nav_missing:
        lines.append("## 新页面未加入导航（%d）" % len(nav_missing))
        lines.append("")
        lines.append("以下页面在 `mkdocs.yml` 的 `nav` 中找不到入口，同步后需要手动补导航：")
        lines.append("")
        for path in nav_missing:
            lines.append("- `%s`" % path)
        lines.append("")

    lines.append("## 下一步")
    lines.append("")
    lines.append("```bash")
    lines.append("python tools/sync_upstream.py apply   # 应用「可安全同步」的改动")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def write_report(text: str, path_arg: str | None = None) -> Path:
    cfg = load_config()
    if path_arg:
        path = (ROOT / path_arg).resolve()
    else:
        path = ROOT / cfg.get("report_dir", ".sync/reports") / "upstream-sync.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def print_summary(entries) -> None:
    counts = {}
    for entry in entries:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    if not counts:
        log("上游没有需要同步的改动。")
        return
    log("差异汇总：")
    for status in ("added", "updated", "conflict", "conflict-added", "conflict-deleted",
                   "locally-deleted", "upstream-deleted", "in-sync", "excluded"):
        if status in counts:
            log("  %-14s %d" % (STATUS_LABELS[status], counts[status]))


# --------------------------------------------------------------------------
# 命令
# --------------------------------------------------------------------------


def collect_state(args):
    cfg = load_config()
    baseline = load_baseline()
    matcher = Matcher(cfg["include"], cfg["exclude"])

    if getattr(args, "upstream_commit", None):
        commit = resolve_commit(args.upstream_commit)
    elif getattr(args, "no_fetch", False):
        commit = resolve_commit("FETCH_HEAD")
    else:
        commit = fetch_upstream(cfg, cfg.get("fetch_retries", 3))

    upstream = list_tree(ROOT, commit)
    local = local_docs_map()
    entries = classify(baseline, upstream, local, matcher)
    return cfg, baseline, entries, commit


def cmd_check(args) -> int:
    cfg, baseline, entries, commit = collect_state(args)
    nav = nav_pages()
    missing = [
        e["path"][len("docs/"):]
        for e in entries
        if e["status"] in APPLY_STATUSES and e["path"].endswith(".md")
        and e["path"][len("docs/"):] not in nav
    ]
    local_branch = git(["rev-parse", "--abbrev-ref", "HEAD"]).decode().strip()
    local_head = git(["rev-parse", "HEAD"]).decode().strip()
    report = build_report(entries, baseline, commit, local_branch, local_head, missing)
    path = write_report(report, args.report)
    print_summary(entries)
    if missing:
        log("提示：%d 个新页面未加入 mkdocs.yml nav，报告中有清单。" % len(missing))
    log("报告已写入：%s" % path)
    if args.fail_on_drift and any(e["status"] in APPLY_STATUSES | {"conflict", "conflict-added",
                                                                  "conflict-deleted"} for e in entries):
        return 1
    return 0


def cmd_apply(args) -> int:
    status = git(["status", "--porcelain"]).decode()
    if status.strip():
        raise SyncError(
            "工作区有未提交的改动，apply 需要干净的工作区。\n请先提交或 stash：\n%s" % status
        )

    cfg, baseline, entries, commit = collect_state(args)
    todo = [e for e in entries if e["status"] in APPLY_STATUSES]
    deletes = [e for e in entries if e["status"] == "upstream-deleted"] if args.prune else []
    if not todo and not deletes:
        log("没有可应用的改动。")
        return 0

    branch = args.branch or "sync/upstream-%s" % datetime.now().strftime("%Y%m%d")
    current = git(["rev-parse", "--abbrev-ref", "HEAD"]).decode().strip()
    if current != branch:
        exists = git(["rev-parse", "--verify", "--quiet", "refs/heads/%s" % branch], check=False)
        if exists.strip():
            raise SyncError("分支已存在：%s，请换一个 --branch 或先删除它" % branch)
        git(["switch", "-c", branch])
        log("已创建分支：%s" % branch)

    written = 0
    for entry in todo:
        path = entry["path"]
        assert path.startswith("docs/") and ".." not in Path(path).parts
        data = git(["show", "%s:%s" % (commit, path)])
        target = ROOT / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        baseline["files"][path] = entry["upstream"]
        written += 1
    for entry in deletes:
        path = entry["path"]
        target = ROOT / path
        if target.exists():
            target.unlink()
        baseline["files"].pop(path, None)
        written += 1

    baseline["upstream"]["commit"] = commit
    baseline["upstream"]["commit_date"] = commit_date(commit)
    baseline["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    BASELINE_PATH.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=0) + "\n", encoding="utf-8"
    )

    nav = nav_pages()
    missing = sorted(
        e["path"][len("docs/"):]
        for e in todo
        if e["path"].endswith(".md") and e["path"][len("docs/"):] not in nav
    )
    changed = ", ".join(e["path"] for e in (todo + deletes)[:5])
    if len(todo) + len(deletes) > 5:
        changed += " 等"

    if not args.no_commit:
        git(["add", "-A", "docs", ".sync/baseline.json"])
        message = args.message or "docs(sync): 同步 Hello-CTF 上游文档（%s）" % commit[:12]
        git(["commit", "-m", message])

    print_summary(entries)
    log("已应用 %d 个文件（%s）" % (written, changed))
    if missing:
        log("注意：以下新页面不在 mkdocs.yml nav 中，请手动补导航：")
        for path in missing:
            log("  - %s" % path)
    if not args.no_commit:
        log("已提交到分支 %s，下一步可推送并提 PR。" % branch)
    return 0


def cmd_init(args) -> int:
    cfg = load_config()
    if BASELINE_PATH.exists() and not args.force and not args.from_repo:
        raise SyncError("基线已存在：%s（加 --force 覆盖）" % BASELINE_PATH)
    if args.from_repo:
        repo = Path(args.from_repo).expanduser().resolve()
        if not (repo / ".git").exists():
            raise SyncError("--from-repo 不是 git 仓库：%s" % repo)
        commit = resolve_commit_at(repo, args.rev)
        tree = list_tree(repo, commit)
        date = commit_date_at(repo, commit)
    else:
        commit = fetch_upstream(cfg, cfg.get("fetch_retries", 3))
        tree = list_tree(ROOT, commit)
        date = commit_date(commit)
    matcher = Matcher(cfg["include"], cfg["exclude"])
    files = {p: s for p, s in tree.items() if matcher.included(p)}
    write_baseline(files, commit, date)
    log("基线已按上游快照生成（仅包含 include 规则内的文件）。")
    return 0


def resolve_commit_at(repo: Path, rev: str) -> str:
    out = git(["-C", str(repo), "rev-parse", rev + "^{commit}"])
    return out.decode().strip()


def commit_date_at(repo: Path, rev: str) -> str | None:
    try:
        out = git(["-C", str(repo), "show", "-s", "--format=%cI", rev]).decode().strip()
        return out or None
    except SyncError:
        return None


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sync_upstream.py",
        description="同步 Hello-CTF 上游文档更新（三方比较，默认不覆盖本地改动）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p):
        p.add_argument("--upstream-commit", help="指定上游 commit（默认 fetch 最新）")
        p.add_argument("--no-fetch", action="store_true", help="不联网，直接使用现有 FETCH_HEAD")
        p.add_argument("--report", help="报告路径（默认 .sync/reports/upstream-sync.md）")

    check = sub.add_parser("check", help="只比较并生成报告，不修改文件")
    add_common(check)
    check.add_argument("--fail-on-drift", action="store_true", help="有可同步/冲突时返回退出码 1")
    check.set_defaults(func=cmd_check)

    apply = sub.add_parser("apply", help="在同步分支上应用安全更新")
    add_common(apply)
    apply.add_argument("--branch", help="目标分支名（默认 sync/upstream-YYYYMMDD）")
    apply.add_argument("--prune", action="store_true", help="同时删除上游已删除且本地未改的文件")
    apply.add_argument("--no-commit", action="store_true", help="只改工作区，不自动提交")
    apply.add_argument("--message", help="提交信息")
    apply.set_defaults(func=cmd_apply)

    init = sub.add_parser("init", help="生成/重置基线快照（谨慎）")
    init.add_argument("--from-repo", help="从另一个本地 git 仓库生成基线（离线引导用）")
    init.add_argument("--rev", default="main", help="--from-repo 时使用的 revision（默认 main）")
    init.add_argument("--force", action="store_true", help="覆盖已有基线")
    init.set_defaults(func=cmd_init)
    return parser


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except SyncError as exc:
        log("错误：%s" % exc)
        return 2
    except KeyboardInterrupt:
        log("已中断。")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
