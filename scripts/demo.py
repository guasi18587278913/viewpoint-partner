#!/usr/bin/env python3
"""Run the bundled synthetic example without personal data, credentials or network."""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
import library


def main():
    root = Path(__file__).resolve().parents[1] / "examples/library"
    records = library.folder_records(root)
    hits = library.search_records(records, ["工具 学习 迁移"], match="all")[0]
    record = hits["results"][0]["record"]
    quote = "新工具省下的时间，要扣掉换工具的学习和迁移成本。"
    check = library.verify_quote(record, quote, record["article_version"], library.digest(record["text"]))
    assert check["ok"]
    print(json.dumps({"status": "ok", "example_kind": "synthetic",
                      "network_calls": 0, "files_read": len(records),
                      "source": library.metadata(record), "quote": quote,
                      "full_text": library.read_slice(record)["text"], "verification": check,
                      "note": "演示检索、回读和逐字核对；观点是否适合当前文本仍由使用者判断。"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
