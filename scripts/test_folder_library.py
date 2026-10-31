"""Portable library behavior, source boundaries and CLI round trips."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import library


class FolderContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="viewpoint-folder-")
        self.root = Path(self.tmp.name) / "资料 文件夹"
        self.root.mkdir()
        library.folder_records.cache_clear()

    def tearDown(self):
        library.folder_records.cache_clear()
        self.tmp.cleanup()

    def put(self, path="文章.md", content="# 标题\n原文支持这个观点。\n"):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def test_nested_markdown_and_txt_keep_provenance_and_exact_text(self):
        p = self.put(content='---\ntitle: "测试标题"\nauthor: 记录作者\n---\n第一行。\n第二行。\n')
        self.put("子目录/记录.TXT", "其他原文。\n")
        with patch.object(library.importlib, "import_module", side_effect=AssertionError("private adapter called")):
            records = library.folder_records(self.root)
        self.assertEqual(len(records), 2)
        record = next(r for r in records if r["raw_file"] == str(p.resolve()))
        self.assertEqual(record["author"], "记录作者")
        self.assertEqual(record["raw_line"], 5)
        self.assertEqual(record["text"], "第一行。\n第二行。\n")
        self.assertEqual(record["file_sha256"], hashlib.sha256(p.read_bytes()).hexdigest())

    def test_missing_author_is_not_guessed_from_body(self):
        self.put(content="# 某人的观点\n这篇文字提到了某个作者。\n")
        record = library.folder_records(self.root)[0]
        self.assertIsNone(record["author"])
        self.assertEqual(record["author_basis"], "not_provided")

    def test_path_ids_survive_relocation_and_versions_detect_edits(self):
        p = self.put()
        before = library.folder_records(self.root)[0]
        other = Path(self.tmp.name) / "搬迁"
        shutil.copytree(self.root, other)
        after = library.folder_records(other)[0]
        self.assertEqual(before["article_id"], after["article_id"])
        p.write_text(p.read_text() + "新增一段。", encoding="utf-8")
        library.folder_records.cache_clear()
        edited = library.folder_records(self.root)[0]
        self.assertEqual(before["article_id"], edited["article_id"])
        self.assertFalse(library.verify_quote(edited, "原文支持这个观点。", before["article_version"])["ok"])

    def test_same_filename_in_different_directories_has_distinct_id(self):
        self.put("甲/文章.md", "内容甲。")
        self.put("乙/文章.md", "内容乙。")
        self.assertEqual(len({r["article_id"] for r in library.folder_records(self.root)}), 2)

    def test_missing_root_and_empty_library_are_not_no_results(self):
        with self.assertRaisesRegex(RuntimeError, "尚未指定"):
            library.folder_records(None)
        with self.assertRaises(OSError):
            library.folder_records(self.root / "不存在")
        with self.assertRaisesRegex(RuntimeError, "不是没有匹配"):
            library.folder_records(self.root)

    def test_empty_file_is_explicit_error(self):
        self.put(content="")
        with self.assertRaisesRegex(ValueError, "正文为空"):
            library.folder_records(self.root)

    def test_non_utf8_file_does_not_silently_disappear(self):
        self.put()
        (self.root / "旧编码.txt").write_bytes("观点".encode("gbk"))
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            library.folder_records(self.root)

    def test_file_symlink_is_rejected(self):
        outside = Path(self.tmp.name) / "outside.txt"
        outside.write_text("外部私人内容", encoding="utf-8")
        (self.root / "链接.txt").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "符号链接"):
            library.folder_records(self.root)

    def test_directory_symlink_is_rejected(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (self.root / "链接目录").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "符号链接"):
            library.folder_records(self.root)

    def test_hidden_and_non_text_files_are_out_of_scope(self):
        self.put()
        self.put(".private/secret.md", "不读这个。")
        self.put(".secret.txt", "不读这个。")
        self.put("document.pdf", "不解析PDF。")
        self.assertEqual(len(library.folder_records(self.root)), 1)

    def test_invalid_metadata_is_reported(self):
        self.put(content="---\nauthor: |\n  复杂值\n---\n正文")
        with self.assertRaisesRegex(ValueError, "单行元数据"):
            library.folder_records(self.root)

    def test_cli_search_read_verify_and_no_source_writes(self):
        p = self.put(content="# 资料\n工具的学习和迁移成本需要核对。\n")
        original = p.read_bytes()
        env = {k: v for k, v in os.environ.items() if not k.startswith("VIEWPOINT_")}
        script = str(Path(library.__file__).resolve())
        def cli(*args):
            result = subprocess.run([sys.executable, "-B", script, "--library", str(self.root), *args],
                                    cwd=self.tmp.name, env=env, capture_output=True, text=True)
            return result.returncode, json.loads(result.stdout)
        code, found = cli("search", "--query", "工具 成本")
        self.assertEqual(code, 0)
        source = found["queries"][0]["results"][0]["source"]
        code, read = cli("read", source["article_id"])
        self.assertEqual(code, 0)
        self.assertEqual(read["text"], original.decode())
        code, check = cli("verify", source["article_id"], "--quote", "工具的学习和迁移成本需要核对。",
                          "--version", source["article_version"], "--sha256", source["text_sha256"])
        self.assertEqual(code, 0)
        self.assertTrue(check["ok"])
        code, failed = cli("verify", source["article_id"], "--quote", "不存在的引文")
        self.assertEqual(code, 1)
        self.assertFalse(failed["ok"])
        self.assertEqual(p.read_bytes(), original)
        self.assertEqual(list(self.root.rglob("*")), [p])

    def test_unconfigured_cli_does_not_fall_back_to_private_adapter(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("VIEWPOINT_")}
        env["VIEWPOINT_CORPUS_ROOT"] = str(self.root)
        result = subprocess.run([sys.executable, "-B", str(Path(library.__file__).resolve()), "status"],
                                env=env, cwd=self.tmp.name, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("尚未指定资料文件夹", json.loads(result.stdout)["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
