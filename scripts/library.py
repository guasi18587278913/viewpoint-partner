#!/usr/bin/env python3
"""Read-only, network-free retrieval over the current personal reading corpus."""
import argparse
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import sys
import unicodedata
from collections import Counter
from functools import lru_cache

CORPUS_ROOT = Path(os.environ.get("VIEWPOINT_CORPUS_ROOT", str(Path.home() / "projects/KnowledgeBase/personal-reading-wiki"))).expanduser()
BOOK_ROOT = Path(os.environ.get("VIEWPOINT_BOOK_ROOT", str(Path.home() / "book-rag"))).expanduser()
PAGE_ROOT = CORPUS_ROOT.parent / "personal-reading-wiki-index/pages"
MAX_READ = 10000


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fold(text):
    normalized = unicodedata.normalize("NFKC", text).casefold()
    # PDF line wrapping can split a Chinese word. Only the retrieval view joins
    # a single hard line break; blank paragraphs and the source text stay intact.
    return re.sub(r"(?<=[\u3400-\u9fff])\r?\n[ \t]*(?=[\u3400-\u9fff])", "", normalized)


def duplicate_key(text):
    # Conservative: only fold Unicode forms and whitespace, never infer copies
    # from matching titles or shared templates.
    return digest(re.sub(r"\s+", "", fold(text)))


@lru_cache(maxsize=1)
def reading_records():
    if not (CORPUS_ROOT / "src/prw/corpus.py").is_file():
        raise RuntimeError("阅读库不可用；不是没有匹配观点。检查 VIEWPOINT_CORPUS_ROOT。")
    sys.path.insert(0, str(CORPUS_ROOT / "src"))
    module = importlib.import_module("prw.corpus")
    if Path(module.ROOT).resolve() != CORPUS_ROOT.resolve():
        raise RuntimeError("导入的阅读库与指定目录不同，停止以免混库。")
    records = []
    for a in module.articles().values():
        records.append({"article_id": a.id, "title": a.title, "author": a.speaker,
                        "author_basis": a.speaker_source, "column": a.column,
                        "collection": a.notebook_title, "source_title": a.source_title,
                        "published_at": a.published_at, "article_version": a.version,
                        "narrator": a.narrator, "discussed_author": a.discussed_author,
                        "discussed_work": a.discussed_work, "text": a.text,
                        "source": "reading"})
    if not records:
        raise RuntimeError("阅读库没有返回篇章记录；先检查本地语料，不能据此说没有相关观点。")
    return records


@lru_cache(maxsize=1)
def book_records():
    raw = BOOK_ROOT / "data/raw_texts"
    if not raw.is_dir():
        raise RuntimeError("书籍原文不可用；不是没有匹配观点。检查 VIEWPOINT_BOOK_ROOT。")
    names = {"关于说话的一切": "汤质", "好好说话": "马薇薇、黄执中、周玄毅等",
             "好好说话2": "马薇薇、黄执中、周玄毅等", "干得漂亮": "脱不花", "沟通的方法": "脱不花"}
    records = []
    for path in sorted(raw.glob("*.txt")):
        stem = path.stem.replace("干的漂亮", "干得漂亮")
        book = next((n for n in sorted(names, key=len, reverse=True) if stem.startswith(n)), None)
        if book is None:
            continue
        file_id = digest(path.name)[:12]
        full = path.read_text(encoding="utf-8")
        headers = list(re.finditer(r"^===== 第 (\d+) 页 =====\s*$", full, re.M))
        if not headers and full.strip():
            records.append({"article_id": "book:%s@%s:full" % (book, file_id),
                            "short_id": "book:%s:full" % book, "title": book,
                            "author": names[book], "author_basis": "book_bibliography",
                            "column": None, "collection": book, "source_title": path.name,
                            "published_at": None, "article_version": digest(full)[:12],
                            "text": full, "source": "books", "page": None,
                            "raw_file": str(path), "raw_line": 1,
                            "source_note": "本书原文没有页码标记；按字符续读，不虚构页码。"})
        for i, header in enumerate(headers):
            start = header.end()
            end = headers[i + 1].start() if i + 1 < len(headers) else len(full)
            page = int(header.group(1))
            text = full[start:end]
            if not text.strip():
                continue
            records.append({"article_id": "book:%s@%s:%d" % (book, file_id, page),
                            "short_id": "book:%s:%d" % (book, page),
                            "title": "%s · 原文页 %d" % (book, page), "author": names[book],
                            "author_basis": "book_bibliography", "column": None,
                            "collection": book, "source_title": path.name,
                            "published_at": None, "article_version": digest(text)[:12],
                            "text": text, "source": "books", "page": page,
                            "raw_file": str(path), "raw_line": full.count("\n", 0, start) + 1})
    if not records:
        raise RuntimeError("书籍目录存在但没有可识别的页码原文。")
    return records


def records_for(source):
    return book_records() if source == "books" else reading_records()


def get_record(article_id):
    source = "books" if article_id.startswith("book:") else "reading"
    records = records_for(source)
    matches = [a for a in records if a["article_id"] == article_id]
    if not matches and source == "books":
        matches = [a for a in records if a.get("short_id") == article_id]
    if len(matches) > 1:
        raise ValueError("书籍简写编号有歧义；使用 search 返回的带文件标识 article_id。")
    if not matches:
        raise ValueError("未知文章编号；请使用本次搜索返回的 article_id：" + article_id)
    return matches[0]


def metadata(record):
    result = {k: v for k, v in record.items() if k != "text"}
    result["text_sha256"] = digest(record["text"])
    result["total_chars"] = len(record["text"])
    if record["source"] == "reading":
        for path in sorted(PAGE_ROOT.glob("*/%s.md" % record["article_id"])):
            # Links to stale material are worse than an explicit article ID.
            if record["text"].strip() in path.read_text(encoding="utf-8"):
                result["index_page"] = str(path)
                break
    return result


def terms_for(query):
    terms = list(dict.fromkeys(fold(t) for t in query.split() if t.strip()))
    if not terms or len(terms) > 12:
        raise ValueError("每条 query 需要 1–12 个空格分隔词组。")
    return terms


@lru_cache(maxsize=256)
def latin_pattern(term):
    return re.compile(r"(?<![a-z0-9_])" + re.escape(term) + r"(?![a-z0-9_])")


def term_present(term, normalized):
    # A query for AI should match AI写作, but not Airbnb, mail or OpenAI.
    # The agent can explicitly query names/acronyms as separate retrieval paths.
    if re.fullmatch(r"[a-z][a-z0-9_-]*", term):
        return latin_pattern(term).search(normalized) is not None
    return term in normalized


def whole_word_window(text, start, end):
    def word_char(char):
        return re.fullmatch(r"[a-z0-9_-]+", fold(char)) is not None
    # Preserve real Latin token boundaries when a fixed-size excerpt cuts a
    # word. Score exactly what will be emitted, never invisible extra context.
    while start > 0 and start < len(text) and word_char(text[start - 1]) and word_char(text[start]):
        start -= 1
    while end < len(text) and end > 0 and word_char(text[end - 1]) and word_char(text[end]):
        end += 1
    return start, end


def best_excerpt(text, terms, weights, width=900):
    best = (float("-inf"), 0, min(width, len(text)))
    for start in range(0, len(text), max(1, width - 180)):
        end = min(len(text), start + width)
        start, end = whole_word_window(text, start, end)
        normalized = fold(text[start:end])
        present = [t for t in terms if term_present(t, normalized)]
        score = sum(weights[t] for t in present) + 4 * len(present) ** 2
        if score > best[0]:
            best = (score, start, end)
    return best


def search_records(records, queries, limit=6, match="any", author="", collection="", title_only=False):
    if not 1 <= len(queries) <= 6 or not 1 <= limit <= 20:
        raise ValueError("queries 为 1–6 条，limit 为 1–20。")
    prepared = []
    for record in records:
        if author and fold(author) not in fold(record.get("author") or ""):
            continue
        if collection and fold(collection) not in fold((record.get("collection") or "") + " " + (record.get("column") or "")):
            continue
        prepared.append((record, fold(record["title"]), fold(record["text"])))
    outputs = []
    for query in queries:
        terms = terms_for(query)
        dfs = Counter()
        eligible = []
        for record, title, body in prepared:
            haystack = title if title_only else title + "\n" + body
            present = [t for t in terms if term_present(t, haystack)]
            dfs.update(present)
            if present and (match != "all" or len(present) == len(terms)):
                eligible.append((record, title, body, present))
        weights = {t: 1 + math.log((len(prepared) + 1) / (dfs[t] + 1)) for t in terms}
        ranked = []
        for record, title, body, present in eligible:
            title_score = 2 * sum(weights[t] for t in present if term_present(t, title))
            score = sum(weights[t] for t in present) + 5 * len(present) ** 2 + title_score
            score /= 1 + .2 * math.log1p(len(body) / 6000)
            ranked.append((score, record, present, title_score))
        ranked.sort(key=lambda x: (-x[0], x[1]["article_id"]))
        refined = []
        for score, record, present, title_score in ranked[:max(120, limit * 15)]:
            passage_score, start, end = best_excerpt(record["text"], terms, weights)
            refined.append((passage_score + title_score + score * .2, record, present, start, end))
        refined.sort(key=lambda x: (-x[0], x[1]["article_id"]))
        kept, keys = [], {}
        for score, record, present, start, end in refined:
            key = duplicate_key(record["text"])
            if key in keys:
                keys[key]["copies"].append({"article_id": record["article_id"], "title": record["title"], "author": record.get("author")})
                continue
            if len(kept) >= limit:
                continue
            item = {"record": record, "score": round(score, 3), "matched_terms": present,
                    "start": start, "end": end, "excerpt": record["text"][start:end], "copies": []}
            keys[key] = item
            kept.append(item)
        outputs.append({"query": query, "terms": terms, "matched_records": len(eligible),
                        "returned_records": len(kept), "results": kept})
    return outputs


def read_slice(record, start=0, end=None, around=None, context=1200, occurrence=1):
    text = record["text"]
    positions = []
    if around is not None:
        if not around:
            raise ValueError("around 不得为空。")
        offset = 0
        while True:
            pos = text.find(around, offset)
            if pos < 0:
                break
            positions.append(pos)
            offset = pos + len(around)
        if not 1 <= occurrence <= len(positions):
            raise ValueError("指定原话或 occurrence 未找到；请使用搜索摘录中的原字。")
        pos = positions[occurrence - 1]
        start, end = max(0, pos - context), min(len(text), pos + len(around) + context)
    if start < 0 or start >= len(text) or (end is not None and end <= start):
        raise ValueError("读取范围无效。")
    requested_end = len(text) if end is None else min(end, len(text))
    end = min(requested_end, start + MAX_READ)
    return {"start": start, "end": end, "total_chars": len(text), "has_more": end < len(text),
            "next_start": end if end < len(text) else None, "prefix_unread": start > 0,
            "range_capped": end < requested_end, "occurrences": len(positions) if around is not None else None,
            "text": text[start:end]}


def verify_quote(record, quote, version=None, sha256=None):
    if not isinstance(quote, str) or not quote.strip():
        raise ValueError("引文不能为空。")
    pos = record["text"].find(quote)
    version_match = version is None or version == record["article_version"]
    hash_match = sha256 is None or sha256 == digest(record["text"])
    return {"article_id": record["article_id"], "exact_quote": pos >= 0,
            "start": pos if pos >= 0 else None, "end": pos + len(quote) if pos >= 0 else None,
            "version_checked": version is not None, "version_match": version_match,
            "hash_checked": sha256 is not None, "hash_match": hash_match,
            "ok": pos >= 0 and version_match and hash_match}


def verify_cards(payload, getter=get_record):
    cards = payload.get("cards", [payload]) if isinstance(payload, dict) else payload
    if not isinstance(cards, list) or not cards:
        raise ValueError("卡片必须是非空数组、单张对象或包含 cards 的对象。")
    results = []
    for card in cards:
        if not isinstance(card, dict) or not isinstance(card.get("source"), dict):
            raise ValueError("每张卡片及其 source 必须是对象。")
        source = card.get("source", {})
        if not all(isinstance(source.get(key), str) and source[key].strip()
                   for key in ("article_id", "article_version", "text_sha256")):
            raise ValueError("卡片 article_id/article_version/text_sha256 必须是非空字符串。")
        record = getter(source["article_id"])
        checks = []
        excerpts = [("quote", card.get("quote")), ("reasoning_excerpt", card.get("reasoning_excerpt"))]
        cases = card.get("cases", [])
        if not isinstance(cases, list) or any(not isinstance(case, dict) for case in cases):
            raise ValueError("cases 必须是对象数组。")
        excerpts.extend(("cases[%d].excerpt" % i, case.get("excerpt")) for i, case in enumerate(cases))
        for field, quote in excerpts:
            check = verify_quote(record, quote, source["article_version"], source["text_sha256"])
            checks.append({"field": field, **check})
        results.append({"id": card.get("id"), "ok": all(c["ok"] for c in checks), "checks": checks})
    return {"ok": all(r["ok"] for r in results), "cards": len(results),
            "passed": sum(r["ok"] for r in results), "failed": sum(not r["ok"] for r in results), "results": results}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    s = sub.add_parser("search")
    s.add_argument("--query", action="append", required=True)
    s.add_argument("--source", choices=["reading", "books"], default="reading")
    s.add_argument("--limit", type=int, default=6)
    s.add_argument("--match", choices=["any", "all"], default="any")
    s.add_argument("--author", default="")
    s.add_argument("--collection", default="")
    s.add_argument("--title-only", action="store_true")
    r = sub.add_parser("read")
    r.add_argument("article_id")
    r.add_argument("--start", type=int, default=0)
    r.add_argument("--end", type=int)
    r.add_argument("--around")
    r.add_argument("--context", type=int, default=1200)
    r.add_argument("--occurrence", type=int, default=1)
    v = sub.add_parser("verify")
    v.add_argument("article_id")
    q = v.add_mutually_exclusive_group(required=True)
    q.add_argument("--quote")
    q.add_argument("--quote-file", type=Path)
    v.add_argument("--version")
    v.add_argument("--sha256")
    c = sub.add_parser("verify-card")
    c.add_argument("file", type=Path)
    return p


def main():
    args = parser().parse_args()
    try:
        if args.command == "status":
            records = reading_records()
            try:
                books = book_records()
                book_status = {"status": "ok", "page_records": sum(r["page"] is not None for r in books),
                               "full_books_without_page_markers": [r["collection"] for r in books if r["page"] is None],
                               "books": len(set(r["collection"] for r in books))}
            except (OSError, RuntimeError) as exc:
                book_status = {"status": "unavailable", "error": str(exc)}
            emit({"status": "ok", "engine": "local_lexical", "network_calls": 0,
                  "corpus_root": str(CORPUS_ROOT), "article_records": len(records),
                  "collections": len(set(r["collection"] for r in records)), "optional_books": book_status,
                  "note": "记录包含书籍和重复来源，不是去重得到篇数，更不是已提取观点数。"})
        elif args.command == "search":
            records = records_for(args.source)
            found = search_records(records, args.query, args.limit, args.match, args.author, args.collection, args.title_only)
            for query in found:
                for item in query["results"]:
                    item["source"] = metadata(item.pop("record"))
            emit({"status": "ok", "engine": "local_lexical", "source": args.source,
                  "corpus_records": len(records), "queries": found,
                  "note": "候选需回读；词面命中不证明观点或适配，零命中不证明库里没有。"})
        elif args.command == "read":
            if args.context < 0:
                raise ValueError("context 不得为负。")
            record = get_record(args.article_id)
            emit({"status": "ok", "source": metadata(record),
                  **read_slice(record, args.start, args.end, args.around, args.context, args.occurrence)})
        elif args.command == "verify":
            record = get_record(args.article_id)
            quote = args.quote_file.read_text(encoding="utf-8") if args.quote_file else args.quote
            result = verify_quote(record, quote, args.version, args.sha256)
            emit({"status": "ok", "source": metadata(record), **result})
            return 0 if result["ok"] else 1
        elif args.command == "verify-card":
            result = verify_cards(json.loads(args.file.read_text(encoding="utf-8")))
            emit({"status": "ok", **result})
            return 0 if result["ok"] else 1
        return 0
    except (OSError, ValueError, RuntimeError, ImportError, KeyError, TypeError) as exc:
        emit({"status": "error", "error": "%s: %s" % (type(exc).__name__, exc),
              "note": "执行失败，不是没有匹配观点；没有调用付费或网络备用入口。"})
        return 2


if __name__ == "__main__":
    # The shipped corpus uses Python 3.10+ annotations. Use its existing venv
    # instead of installing anything or altering the user's shell configuration.
    if sys.version_info < (3, 10):
        interpreter = CORPUS_ROOT / ".venv/bin/python"
        if interpreter.is_file() and Path(sys.executable).resolve() != interpreter.resolve():
            os.execv(str(interpreter), [str(interpreter), str(Path(__file__).resolve()), *sys.argv[1:]])
    sys.dont_write_bytecode = True
    raise SystemExit(main())
