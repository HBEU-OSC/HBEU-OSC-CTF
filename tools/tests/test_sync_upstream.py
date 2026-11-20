# -*- coding: utf-8 -*-
"""sync_upstream.py 的单元测试（不联网、不需要 git 仓库）。

运行：python -m unittest discover -s tools/tests -v
"""

import importlib.util
import pathlib
import unittest

TOOL = pathlib.Path(__file__).resolve().parents[2] / "tools" / "sync_upstream.py"
spec = importlib.util.spec_from_file_location("sync_upstream", TOOL)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)

SHA = {
    "a": "a" * 40,
    "b": "b" * 40,
    "c": "c" * 40,
}


def entry_map(entries):
    return {e["path"]: e["status"] for e in entries}


class GlobTests(unittest.TestCase):
    def setUp(self):
        self.m = sync.Matcher(
            include=["docs/**"],
            exclude=["docs/hc-writeup/**", "docs/Event/**", "docs/index.html"],
        )

    def test_include_everything_under_docs(self):
        self.assertTrue(self.m.included("docs/hc-ics/a.md"))
        self.assertTrue(self.m.included("docs/hc-misc/images/x.png"))
        self.assertFalse(self.m.included("mkdocs.yml"))
        self.assertFalse(self.m.included("tools/sync_upstream.py"))

    def test_exclude_glob(self):
        self.assertTrue(self.m.excluded("docs/hc-writeup/2026/x.md"))
        self.assertTrue(self.m.excluded("docs/Event/json/CN.json"))
        self.assertTrue(self.m.excluded("docs/index.html"))
        self.assertFalse(self.m.excluded("docs/hc-ics/a.md"))
        # included() 只看 include 规则，in_scope() 才同时考虑 exclude
        self.assertFalse(self.m.in_scope("docs/Event/json/CN.json"))
        self.assertTrue(self.m.in_scope("docs/hc-ics/a.md"))

    def test_double_star_middle(self):
        m = sync.Matcher(include=["docs/**/assets/**"], exclude=[])
        self.assertTrue(m.included("docs/hc-web/assets/a.png"))
        self.assertTrue(m.included("docs/assets/a.png"))
        self.assertFalse(m.included("docs/hc-web/a.png"))


class BlobTests(unittest.TestCase):
    def test_blob_sha1(self):
        self.assertEqual(
            sync.blob_sha1(b"hello"), "b6fc4c620b67d95f953a5c1c1230aaab5db5a1b0"
        )
        self.assertEqual(
            sync.blob_sha1(b""), "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
        )


class ClassifyTests(unittest.TestCase):
    def setUp(self):
        self.matcher = sync.Matcher(
            include=["docs/**"], exclude=["docs/hc-writeup/**", "docs/Event/**"]
        )

    def run_case(self, base, upstream, local):
        baseline = {"files": base}
        return entry_map(
            sync.classify(baseline, upstream, local, self.matcher)
        )

    def test_updated(self):
        result = self.run_case(
            {"docs/a.md": SHA["a"]}, {"docs/a.md": SHA["b"]}, {"docs/a.md": SHA["a"]}
        )
        self.assertEqual(result["docs/a.md"], "updated")

    def test_conflict(self):
        result = self.run_case(
            {"docs/a.md": SHA["a"]}, {"docs/a.md": SHA["b"]}, {"docs/a.md": SHA["c"]}
        )
        self.assertEqual(result["docs/a.md"], "conflict")

    def test_added(self):
        result = self.run_case({}, {"docs/new.md": SHA["b"]}, {})
        self.assertEqual(result["docs/new.md"], "added")

    def test_conflict_added(self):
        result = self.run_case({}, {"docs/new.md": SHA["b"]}, {"docs/new.md": SHA["c"]})
        self.assertEqual(result["docs/new.md"], "conflict-added")

    def test_in_sync(self):
        result = self.run_case(
            {"docs/a.md": SHA["a"]}, {"docs/a.md": SHA["b"]}, {"docs/a.md": SHA["b"]}
        )
        self.assertEqual(result["docs/a.md"], "in-sync")

    def test_locally_deleted(self):
        result = self.run_case({"docs/a.md": SHA["a"]}, {"docs/a.md": SHA["b"]}, {})
        self.assertEqual(result["docs/a.md"], "locally-deleted")

    def test_upstream_deleted(self):
        result = self.run_case({"docs/a.md": SHA["a"]}, {}, {"docs/a.md": SHA["a"]})
        self.assertEqual(result["docs/a.md"], "upstream-deleted")

    def test_conflict_deleted(self):
        result = self.run_case({"docs/a.md": SHA["a"]}, {}, {"docs/a.md": SHA["c"]})
        self.assertEqual(result["docs/a.md"], "conflict-deleted")

    def test_unchanged_upstream_ignores_local_edits(self):
        result = self.run_case(
            {"docs/a.md": SHA["a"]}, {"docs/a.md": SHA["a"]}, {"docs/a.md": SHA["c"]}
        )
        self.assertNotIn("docs/a.md", result)

    def test_excluded_path(self):
        result = self.run_case(
            {"docs/hc-writeup/x.md": SHA["a"]},
            {"docs/hc-writeup/x.md": SHA["b"]},
            {"docs/hc-writeup/x.md": SHA["a"]},
        )
        self.assertEqual(result["docs/hc-writeup/x.md"], "excluded")

    def test_local_only_file_ignored(self):
        result = self.run_case({}, {}, {"docs/hc-writeup/my.md": SHA["c"]})
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
