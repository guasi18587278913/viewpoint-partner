#!/usr/bin/env python3
"""Read-only retrieval over an explicit Markdown/TXT folder or an optional corpus adapter."""
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

def configured_path(name):
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else None


FILES_ROOT = configured_path("VIEWPOINT_LIBRARY_DIR")
CORPUS_ROOT = configured_path("VIEWPOINT_CORPUS_ROOT")
BOOK_ROOT = configured_path("VIEWPOINT_BOOK_ROOT")
PAGE_ROOT = configured_path("VIEWPOINT_PAGE_ROOT")
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


def file_metadata(content):
    """Read optional, single-line metadata without interpreting executable YAML."""
    lines = content.splitlines(keepends=True)
    metadata_fields = {}
    body_start = 0
    if lines and lines[0].strip() == "---":
        closing = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if closing is None:
            raise ValueError("文件开头的元数据缺少结束的 ---。")
        for line in lines[1:closing]:
            field, separator, value = line.partition(":")
            if separator and field.strip() in {"title", "author", "date", "source_url", "collection"}:
                value = value.strip()
                if not value or value in {"|", ">", "null", "~"}:
                    raise ValueError("元数据字段 %s 需要一个非空单行值。" % field.strip())
                if value.startswith('"'):
                    value = json.loads(value)
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1].replace("''", "'")
                if not isinstance(value, str):
                    raise ValueError("元数据字段必须是文字。")
                metadata_fields[field.strip()] = value
        body_start = closing + 1
    return metadata_fields, "".join(lines[body_start:]), body_start + 1


@lru_cache(maxsize=1)
def folder_records(root):
    if root is None:
        raise RuntimeError("尚未指定资料文件夹。使用 --library /你的资料目录，或设置 VIEWPOINT_LIBRARY_DIR；可先用 --library examples/library 体验合成示例。")
    root = Path(root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("资料路径必须是目录。")
    records = []
    def fail_walk(error):
        raise error
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=fail_walk):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in {"node_modules", "__pycache__", "venv"})
        candidates = [Path(directory) / d for d in dirs]
        candidates += [Path(directory) / f for f in sorted(files)
                       if not f.startswith(".") and Path(f).suffix.lower() in {".md", ".txt"}]
        for path in candidates:
            if path.is_symlink():
                raise ValueError("资料目录包含符号链接，未读取链接目标：" + str(path.relative_to(root)))
        for path in candidates[len(dirs):]:
            if not path.is_file():
                raise ValueError("资料不是普通文件：" + str(path.relative_to(root)))
            relative = path.relative_to(root).as_posix()
            raw = path.read_bytes()
            try:
                content = raw.decode("utf-8-sig")
                fields, body, raw_line = file_metadata(content)
            except (UnicodeError, ValueError) as exc:
                raise ValueError("无法读取 %s：请使用 UTF-8 文本和单行元数据（%s）。" % (relative, type(exc).__name__)) from exc
            if not body.strip():
                raise ValueError("资料文件正文为空：" + relative)
            title = fields.get("title")
            if not title:
                heading = re.search(r"^#\s+(.+)$", body, re.M)
                title = heading.group(1).strip() if heading else path.stem
            file_hash = hashlib.sha256(raw).hexdigest()
            records.append({"article_id": "file:" + digest(relative)[:24], "title": title,
                            "author": fields.get("author"),
                            "author_basis": "file_metadata" if fields.get("author") else "not_provided",
                            "column": None, "collection": fields.get("collection", path.parent.relative_to(root).as_posix()),
                            "source_title": relative, "source_url": fields.get("source_url"),
                            "published_at": fields.get("date"), "article_version": file_hash,
                            "file_sha256": file_hash, "text": body, "source": "files",
                            "raw_file": str(path), "raw_line": raw_line})
    if not records:
        raise RuntimeError("资料目录没有可读取的 Markdown/TXT 正文；不是没有匹配观点。")
    return records


@lru_cache(maxsize=1)
def reading_records():
    if CORPUS_ROOT is None or not (CORPUS_ROOT / "src/prw/corpus.py").is_file():
        raise RuntimeError("阅读库不可用；不是没有匹配观点。检查 VIEWPOINT_CORPUS_ROOT。")
    if sys.version_info < (3, 10):
        raise RuntimeError("专用阅读库适配需要 Python 3.10 或以上；通用 --library 模式可使用 Python 3.9。")
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
    if BOOK_ROOT is None:
        raise RuntimeError("书籍适配未配置；请设置 VIEWPOINT_BOOK_ROOT，或使用 --library 读取普通 Markdown/TXT。")
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
    if source == "files":
        return folder_records(FILES_ROOT)
    return book_records() if source == "books" else reading_records()


def get_record(article_id):
    source = "files" if article_id.startswith("file:") else "books" if article_id.startswith("book:") else "reading"
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
    if record["source"] == "reading" and PAGE_ROOT is not None:
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
    p.add_argument("--library", type=Path, help="Explicit folder of UTF-8 Markdown/TXT files; no private corpus required")
    sub = p.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status")
    status.add_argument("--source", choices=["files", "reading", "books"], default="files")
    s = sub.add_parser("search")
    s.add_argument("--query", action="append", required=True)
    s.add_argument("--source", choices=["files", "reading", "books"], default="files")
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
    for command_parser in (status, s, r, v, c):
        command_parser.add_argument("--library", type=Path, default=argparse.SUPPRESS)
    return p


def main():
    global FILES_ROOT
    args = parser().parse_args()
    if args.library is not None:
        FILES_ROOT = args.library
    try:
        if args.command == "status":
            records = records_for(args.source)
            root = {"files": FILES_ROOT, "reading": CORPUS_ROOT, "books": BOOK_ROOT}[args.source]
            emit({"status": "ok", "engine": "local_lexical", "network_calls": 0,
                  "source": args.source, "corpus_root": str(root.resolve()), "article_records": len(records),
                  "collections": len(set(r["collection"] for r in records)),
                  "note": "记录可能包含重复来源，不是已提取观点数；其他资料源不会自动读取。"})
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
    sys.dont_write_bytecode = True
    raise SystemExit(main())
