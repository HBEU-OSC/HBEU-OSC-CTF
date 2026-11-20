# 上游同步工具

`tools/sync_upstream.py` 用来把 [ProbiusOfficial/Hello-CTF](https://github.com/ProbiusOfficial/Hello-CTF)
的文档更新同步到本仓库。本仓库是二次创作版本，和上游的 git 历史不共享，目录和页面也有
本地改动，所以不能直接 `git merge`；工具改用「基线快照 + 三方比较」的方式，只自动写入
**上游改了、本地没改过**的文件。

## 工作原理

```
.sync/baseline.json   上次同步时上游 docs/ 各文件的 blob SHA
        ×
上游最新（fetch 后读取目录树，不下载 blob）
        ×
本地工作区 docs/ 的实际内容
```

对每个文件做比较：

| 上游 | 本地 | 结果 |
| --- | --- | --- |
| 新增 | 不存在 | 可同步（新增） |
| 修改 | 与基线一致 | 可同步（更新） |
| 修改 | 本地也改过 | 冲突，不覆盖，写入报告 |
| 修改 | 本地删除 | 跳过 |
| 删除 | 与基线一致 | 默认跳过，`--prune` 时删除 |

## 常用命令

```bash
# 1. 只检查，生成报告到 .sync/reports/upstream-sync.md
python tools/sync_upstream.py check

# 2. 应用「可安全同步」的改动：自动建分支、写文件、更新基线并提交
python tools/sync_upstream.py apply

# 3. 指定报告路径 / 不联网 / 固定上游 commit
python tools/sync_upstream.py check --report .sync/reports/2026-11-20.md
python tools/sync_upstream.py check --no-fetch
python tools/sync_upstream.py check --upstream-commit 3b606f7
```

`apply` 的默认行为：

- 要求工作区干净；
- 新建 `sync/upstream-YYYYMMDD` 分支（可用 `--branch` 指定）；
- 只写 `added` / `updated` 的文件，冲突文件保持原样；
- 同步更新 `.sync/baseline.json`，记录新的上游 commit；
- 自动提交（`--no-commit` 可关闭）。

之后推送该分支并按普通 PR 流程评审即可。

## 配置

`.sync/config.json`：

```json
{
  "upstream": { "repo": "https://github.com/ProbiusOfficial/Hello-CTF.git", "branch": "main" },
  "report_dir": ".sync/reports",
  "include": ["docs/**"],
  "exclude": ["docs/hc-writeup/**", "docs/Event/**", "..."]
}
```

- `include` / `exclude` 使用 `**`、`*`、`?` 通配符，路径相对仓库根目录；
- `exclude` 中的路径既不会被写入，也不会参与冲突判断（报告里单列为「命中排除规则」）；
- 本仓库的 `docs/hc-writeup/`、`docs/Event/`、`docs/sidebar/`、`docs/shell/` 以及首页相关
  文件均为本地定制，默认排除。

## 基线

`.sync/baseline.json` 记录的是 **2026-10-23 的上游 `dca4d76`**（本仓库内容所对应的上游快照），
不是当前上游。因此第一次运行 `check` 会把 `dca4d76` 之后的上游更新都列为可同步项。

只有需要重新建立基线时才用 `init`：

```bash
# 从当前上游最新重建（会丢失「待同步」清单，谨慎）
python tools/sync_upstream.py init --force

# 离线：从本地 Hello-CTF 克隆的某个 commit 生成基线
python tools/sync_upstream.py init --from-repo ../Hello-CTF --rev dca4d76
```

## 注意事项

- **新页面不会自动进导航**：`mkdocs.yml` 的 `nav` 是手写的，`check` / `apply` 会列出「未加入
  导航的新页面」，需要手动补；否则页面能构建但站内没有入口。
- **冲突需要人工合并**：两边都改过的文件不会被覆盖；合并后可以只更新基线里该文件的 SHA，
  或整体重跑 `init`（会重置待同步清单）。
- **Windows 下 git TLS 有问题时**：设置 `SYNC_GIT` 指向可用的 git，例如
  `set SYNC_GIT=D:\Git\cmd\git.exe`。
- 同步只覆盖文档内容；`mkdocs.yml`、`overrides/`、`hooks/`、`admin/` 等站点代码不参与同步。
- 上游内容遵循其仓库的许可证（代码 GPLv3、文档 CC BY-SA 4.0），同步时请保留来源说明。

## 测试

```bash
python -m unittest discover -s tools/tests -v
```

## CI

`.github/workflows/upstream-sync-check.yml` 每周一自动运行 `check`，把报告作为 artifact 上传，
不会自动提交或开 PR。
