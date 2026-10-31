"""Observable retrieval, citation and pagination contracts; no network or source writes."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import library


def doc(key, text, title="文章", author="某作者"):
    return {"article_id": key, "title": title, "author": author, "column": "专栏",
            "collection": "资料组", "article_version": "v1", "text": text, "source": "reading"}


class RetrievalContracts(unittest.TestCase):
    def test_mechanism_can_be_found_without_the_input_industry_word(self):
        source = doc("source", "新体验要扣除旧体验和用户的替换成本。", "用户价值")
        unrelated = doc("noise", "AI工具的版本号今天更新了。", "工具新闻")
        hits = library.search_records([source, unrelated], ["用户 替换成本"], match="all")[0]
        self.assertEqual([r["record"]["article_id"] for r in hits["results"]], ["source"])

    def test_latin_keyword_does_not_match_inside_unrelated_word(self):
        correct = doc("correct", "用AI写作，需要判断内容质量。")
        noisy = doc("noise", "Airbnb 房东用 mail 沟通写作。")
        hits = library.search_records([noisy, correct], ["AI 写作"], match="all")[0]
        self.assertEqual([r["record"]["article_id"] for r in hits["results"]], ["correct"])

    def test_excerpt_start_does_not_turn_a_cut_word_into_a_keyword(self):
        a = doc("a", "甲" * 716 + "OpenAI" + "乙" * 1600 + " AI 写作")
        hit = library.search_records([a], ["AI"])[0]["results"][0]
        self.assertIn(" AI 写作", hit["excerpt"])
        self.assertEqual(hit["excerpt"], a["text"][hit["start"]:hit["end"]])

    def test_excerpt_end_does_not_turn_a_cut_word_into_a_keyword(self):
        a = doc("a", "甲" * 898 + "AIrbase" + "乙" * 1600 + " AI 写作")
        hit = library.search_records([a], ["AI"])[0]["results"][0]
        self.assertIn(" AI 写作", hit["excerpt"])
        self.assertEqual(hit["excerpt"], a["text"][hit["start"]:hit["end"]])

    def test_matching_titles_do_not_collapse_different_originals(self):
        a = doc("a", "边界需要协商，拒绝后不应强迫。", "边界")
        b = doc("b", "边界涉及所有权，这一篇讨论经济范围。", "边界")
        self.assertEqual(library.search_records([a, b], ["边界"])[0]["returned_records"], 2)

    def test_layout_copies_are_folded_with_provenance(self):
        a = doc("a", "用户的替换成本不可忽视。")
        b = doc("b", "用户的替换成本\n不可忽视。")
        results = library.search_records([a, b], ["替换成本"])[0]["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(len(results[0]["copies"]), 1)

    def test_unicode_search_does_not_rewrite_the_original_excerpt(self):
        a = doc("a", "⽤户可以提出⾃⼰的观点。")
        result = library.search_records([a], ["用户 自己"], match="all")[0]["results"][0]
        self.assertEqual(result["excerpt"], a["text"])

    def test_pdf_wrapped_word_is_searchable_but_quotes_remain_literal(self):
        a = doc("a", "每个人都应该独立思\n考，承担责\n任。")
        result = library.search_records([a], ["独立思考 责任"], match="all")[0]["results"][0]
        self.assertEqual(result["excerpt"], a["text"])
        self.assertFalse(library.verify_quote(a, "独立思考")["ok"])
        self.assertTrue(library.verify_quote(a, "独立思\n考")["ok"])

    def test_paragraph_boundary_is_not_erased_during_search(self):
        a = doc("a", "我们独立思\n\n考察另一件事。")
        self.assertEqual(library.search_records([a], ["独立思考"])[0]["results"], [])

    def test_author_is_a_filter_not_an_attribution_hint(self):
        a = doc("a", "讨论边界。", author=None)
        self.assertEqual(library.search_records([a], ["边界"], author="陈海贤")[0]["results"], [])

    def test_empty_search_is_distinct_from_unavailable_corpus(self):
        self.assertEqual(library.search_records([doc("a", "谈工作")], ["完全无关"])[0]["matched_records"], 0)
        with tempfile.TemporaryDirectory() as tmp:
            library.reading_records.cache_clear()
            with patch.object(library, "CORPUS_ROOT", Path(tmp)):
                with self.assertRaisesRegex(RuntimeError, "不可用"):
                    library.reading_records()
            library.reading_records.cache_clear()


class QuoteContracts(unittest.TestCase):
    def setUp(self):
        self.a = doc("a", "小众需要少数人真正喜欢。\n这不意味着销量少就一定平庸。")

    def test_exact_quote_passes_and_paraphrase_fails(self):
        self.assertTrue(library.verify_quote(self.a, "小众需要少数人真正喜欢。", "v1", library.digest(self.a["text"]))["ok"])
        self.assertFalse(library.verify_quote(self.a, "销量少一定是平庸。")["ok"])

    def test_version_and_hash_drift_fail_even_if_words_survive(self):
        self.assertFalse(library.verify_quote(self.a, "小众", version="v0")["ok"])
        self.assertFalse(library.verify_quote(self.a, "小众", sha256="bad")["ok"])

    def test_empty_quote_cannot_verify_every_document(self):
        with self.assertRaises(ValueError):
            library.verify_quote(self.a, "")

    def test_changed_case_excerpt_invalidates_whole_card(self):
        card = {"id": "case", "source": {"article_id": "a", "article_version": "v1", "text_sha256": library.digest(self.a["text"])},
                "quote": "小众需要少数人真正喜欢。", "reasoning_excerpt": "这不意味着销量少就一定平庸。",
                "cases": [{"excerpt": "这个案例从来没有出现在原文中。"}]}
        checked = library.verify_cards(card, getter=lambda key: self.a)
        self.assertFalse(checked["ok"])
        self.assertEqual(checked["failed"], 1)

    def test_card_without_version_cannot_be_called_verified(self):
        with self.assertRaises(ValueError):
            library.verify_cards({"source": {"article_id": "a"}}, getter=lambda key: self.a)

    def test_malformed_card_source_types_are_explicit_parameter_errors(self):
        for field in ("article_id", "article_version", "text_sha256"):
            source = {"article_id": "a", "article_version": "v1", "text_sha256": library.digest(self.a["text"])}
            for value in (1, True, {}, None, " "):
                with self.subTest(field=field, value=value):
                    with self.assertRaisesRegex(ValueError, "非空字符串"):
                        library.verify_cards({"source": {**source, field: value}}, getter=lambda key: self.a)


class ReadContracts(unittest.TestCase):
    def test_multiple_editions_have_unique_ids_and_ambiguous_alias_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "data/raw_texts"
            raw.mkdir(parents=True)
            for edition, content in [("甲版", "甲版观点。"), ("乙版", "乙版观点。")]:
                (raw / ("好好说话-" + edition + ".txt")).write_text("===== 第 81 页 =====\n" + content, encoding="utf-8")
            library.book_records.cache_clear()
            with patch.object(library, "BOOK_ROOT", Path(tmp)):
                rows = library.book_records()
                self.assertEqual(len({r["article_id"] for r in rows}), 2)
                hit = library.search_records(rows, ["乙版观点"])[0]["results"][0]
                resolved = library.get_record(hit["record"]["article_id"])
                self.assertIn("乙版观点", resolved["text"])
                with self.assertRaisesRegex(ValueError, "歧义"):
                    library.get_record("book:好好说话:81")
            library.book_records.cache_clear()

    def test_book_without_page_markers_remains_readable_without_fabricated_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "data/raw_texts"
            raw.mkdir(parents=True)
            (raw / "干的漂亮.txt").write_text("没有页码但有原文。", encoding="utf-8")
            library.book_records.cache_clear()
            with patch.object(library, "BOOK_ROOT", Path(tmp)):
                rows = library.book_records()
                self.assertEqual(len(rows), 1)
                self.assertIsNone(rows[0]["page"])
                self.assertEqual(rows[0]["text"], "没有页码但有原文。")
            library.book_records.cache_clear()

    def test_long_original_is_not_silently_truncated(self):
        a = doc("a", "原" * 12345)
        first = library.read_slice(a)
        second = library.read_slice(a, start=first["next_start"])
        self.assertTrue(first["has_more"])
        self.assertFalse(second["has_more"])
        self.assertEqual(first["text"] + second["text"], a["text"])

    def test_around_can_read_later_occurrence_and_reports_unread_prefix(self):
        a = doc("a", "边界第一处。" + "隔" * 30 + "边界第二处。")
        result = library.read_slice(a, around="边界", context=4, occurrence=2)
        self.assertIn("第二处", result["text"])
        self.assertTrue(result["prefix_unread"])
        self.assertEqual(result["occurrences"], 2)

    def test_malformed_ranges_fail_instead_of_returning_empty_success(self):
        for start, end in [(-1, 3), (0, 0), (9, None)]:
            with self.assertRaises(ValueError):
                library.read_slice(doc("a", "原文"), start=start, end=end)


if __name__ == "__main__":
    unittest.main(verbosity=2)
