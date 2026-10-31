# 本地检索与原文核对

## 入口和职责

- 主库：`~/projects/KnowledgeBase/personal-reading-wiki`，从 `src/prw/corpus.py` 的 `articles()` 读取当前版本 `Article.text`。包含得到专栏、书籍和其他已收录资料，篇章记录数不等于去重后的得到文章数。
- 可选书库：`~/book-rag/data/raw_texts/`，五本沟通书的页码原文。用于书中的具体看法与例子，不自动把任务改成沟通方法教学。
- `scripts/library.py` 不写库、不建索引、不读密钥、不发网络请求。每次重新加载当前本地资料。可用 `VIEWPOINT_CORPUS_ROOT`、`VIEWPOINT_BOOK_ROOT` 指定已经存在的库。
- 已知的旧 `search_cli.py` 需要本地 bge 模型；2026-10-24 实测缓存缺失。不要为一次观点查询自动下载模型或修复旧项目。
- 阅读库的现有 GBrain 混合检索配置曾使用云端向量。只有本次已确认相应费用与授权时才切换；工具名或 localhost 地址不是免费保证。本 Skill 的默认脚本完全不走那条路径。

## 命令

以下命令在本 Skill 目录运行。也可以用脚本的绝对路径从任意目录执行。

```bash
python3 scripts/library.py status
python3 scripts/library.py search --query '小众 平庸' --limit 8
python3 scripts/library.py search --query '替换成本' --query '用户 学习成本' --limit 6
python3 scripts/library.py search --query '边界 拒绝' --author '陈海贤' --match all
python3 scripts/library.py search --query '亲密关系' --title-only
python3 scripts/library.py search --source books --query '边界' --query '说服 需求'
python3 scripts/library.py read a-13df97888248dd01
python3 scripts/library.py read a-13df97888248dd01 --around '说“不”' --context 1500
python3 scripts/library.py read 'book:好好说话2:81'
python3 scripts/library.py read 'book:干得漂亮:full' --start 10000
python3 scripts/library.py verify a-13df97888248dd01 --quote '这些边界是怎么形成的呢？'
python3 scripts/library.py verify-card references/seed-viewpoints.json
```

`status` 分别报告文章记录、资料分组和可选书籍页数，不冒充去重文章数或观点数。主库不可用会明确报错；仍可单独用 `--source books`，不能说整个任务“没材料”。

《干得漂亮》的现有原文没有页码标记，作为完整书籍记录返回，使用字符位置续读；其余四本按原始页码读取。不从切片索引猜印刷页码。

书籍搜索结果的完整编号含文件标识，例如 `book:书名@文件标识:页码`，保存卡片时使用完整编号。上面命令中的短编号只在唯一匹配时可用；同书多版本会报歧义，不能默认读第一本。

`search` 一次最多 6 个 `--query`。**空格分开要匹配的词组**，例如 `'小众 平庸'`；每组先按词面相关性排序，默认任一词命中，`--match all` 要求该组全部词出现。不同 query 是独立路径，不要求全部同时成立。长整句不会自动进行语义理解，先由助手改写成短词组。可用 `--author`、`--collection` 缩小范围，`--title-only` 明确只查标题。搜索比较时兼容 Unicode 字形，并拼接中文词中间的单个硬换行；输出摘录始终来自原始字符片段，引用核对仍逐字比较。

每个结果有 article_id、标题、作者依据、专栏、日期、版本、全文 SHA-256、命中词和带字符位置的摘录。相同规范化全文折叠为一条并保留 copies；近似版本仍需人工识别，不能算多位老师的独立观点。排序分数只用于找原文，不表示观点正确、犀利或适配程度。

AI 等英文词组按字母数字边界匹配：可命中“AI写作”，不会因 Airbnb、mail 里有相同字母而命中。OpenAI、AIGC 等仍需作为单独检索词；这不是缩写扩展或语义搜索。

多组结果可能超过一次工具展示长度。先把该次完整 stdout 保存到本次临时文件，再精简显示标题、ID 和相关摘录，按需分段读保存结果；不要因显示截断而原样重搜。原文的 `has_more` 与工具输出截断是两回事。问答文章中的读者发言、作者回答仍要逐段识别，元数据 author 不代表摘录里的每句话都是作者主张。

`read` 默认最多 10000 字；输出 `start/end/total_chars/has_more/next_start`。如果 `has_more=true`，继续 `--start 上次的next_start`；不将第一页当全文。`--around` 返回首次精确出现处及上下文，出现多次会显示数量；用 `--occurrence 2` 读第二处。读到该论述结束和必要限制再决定采用。

书籍的页码记录中，`has_more=false` 只表示当前页已读完，不表示章节结束。跨页论述要继续读同一文件标识的相邻页，并逐页核对引用。当前 `verify` 不支持把多页合并为一段核验；不要据单页成功宣称整段已核对。也可在主阅读库中查找该书的完整文本条目。缺页或缺上下文时明确标出。

`verify` 逐字核对原话。长引文可保存成 UTF-8 临时文件，使用 `--quote-file`，文件按原样读取（包括换行）。避免把用户文字直接拼成 shell 命令。核对旧卡片时加 `--version` 和 `--sha256`；任何版本或字句不一致均不得说核验通过。成功退出 0；核对不通过退出 1；库不可用、编号/参数错误退出 2。

`verify-card` 接受 `{"cards":[...]}`、JSON 数组或单张 JSON 卡片。核对 `source.article_id/article_version/text_sha256`、`quote`、`reasoning_excerpt`、`cases[].excerpt`。它不裁定观点归属、论证强度和适配性。卡片中的概括与适用场景需要人工审核。

## 没找到时怎么扩大

先区分执行错误与正常零命中。正常零命中时尝试：

1. 拆掉平台、行业和工具名，改搜背后问题，例如“换工具”→“替换成本”。
2. 换相近表达和反向说法，必要时分别查观点和事例；不要把所有关键词塞进一个 all 查询。
3. 查作者、专栏或标题，再读文章中的相邻问题。书籍走页码入口。
4. 已有来源出现转述对象时追那位作者/那本书。只找到转述也能用，但注明转述层级。

一个主题经几条实质不同路径仍没有好候选时，交具体查阅范围与缺口；不因词面搜索漏检断言整个库没有，不无限换词。需外部补查时说明计划、渠道和费用，再沿当前授权处理。

## 数据瑕疵

部分条目可能同文异名、混合多讲、作者未知或只有图片占位。以正文自述与文章边界核对；标题或 speaker 只帮助定位。正文仍无法确定作者就标未记录，不能因搜了某位老师就安给他。图片里才有的观点不在文本里时，明确缺图，不自行补写。

`index_page` 只在本机索引文件确实包含当前全文时返回，可作为用户回查链接。缺失或旧版本时不要猜 URL；保留文章编号与 read 命令提供回查。获取库内原话不等于对其中历史数据或研究作了外部核验。
