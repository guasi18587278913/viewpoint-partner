# 本地检索与原文核对

## 默认：自己的 Markdown/TXT 文件夹

普通使用不依赖作者的得到库、Wiki 服务、向量模型或专用 Python 项目。准备一个资料文件夹，放入你有权使用的 UTF-8 `.md`、`.txt` 文件；子目录也会读取。图片、PDF 和 Word 需先由使用者转换为文字，脚本不会把它们当成已读取正文。

通过 `--library` 或 `VIEWPOINT_LIBRARY_DIR` 明确指定目录。脚本不自动扫描主目录、不读取其他项目、不联网、不建索引、不修改原文。未配置时报告缺项；不会偷偷改用演示资料或作者的私人库。

```bash
# 在本技能目录运行。这个例子只读随仓库提供的合成资料。
python3 scripts/demo.py
python3 scripts/library.py --library examples/library status
python3 scripts/library.py --library examples/library search --query '工具 学习 迁移' --match all
```

处理自己的资料时，将 `examples/library` 换成自己的目录。也可在其他位置使用脚本绝对路径；`--library` 相对路径以当前工作目录为准，含空格时加引号。`--library` 可放在子命令之前或之后。

搜索会返回 `article_id`、作者依据、相对文件名、原文位置、正文 SHA-256 与文件版本。拿到 `file:...` 编号后，继续使用同一个资料目录：

```bash
python3 scripts/library.py --library /你的资料目录 read 'file:搜索返回的编号'
python3 scripts/library.py --library /你的资料目录 verify 'file:搜索返回的编号' --quote '原文中的一句话' --version '搜索返回的article_version' --sha256 '搜索返回的text_sha256'
python3 scripts/library.py --library /你的资料目录 verify-card /你的工作目录/cards.json
```

上面带“搜索返回的……”的部分是占位符，必须替换；不要猜编号。文件 ID 由相对路径生成，同名不同目录可区分；移动整库不改 ID，重命名文件会改变 ID。文件内容或元数据变化会改变版本，旧卡必须重新核对。

### 可选元数据

没有元数据也能读。标题使用第一个一级 Markdown 标题或文件名；没有作者字段时标“未提供”，不从正文提到的人名猜作者。Markdown/TXT 均可在开头使用以下单行字段：

```text
---
title: 文章标题
author: 原文作者
source_url: https://example.com/article
date: 2026-10-31
collection: 我的读书笔记
---
这里开始是正文。
```

这是有限的单行元数据格式，不支持多行 YAML、对象或数组。值可用普通文字、JSON 双引号字符串或单引号字符串；不支持行尾注释。正文原样读取，元数据不参与引文匹配；`raw_line` 指出正文从原文件第几行开始。作者字段是资料提供者填写的信息，不证明正文每句话都属于这个作者。书评、读者提问和转述仍需逐段判断。

文件按 UTF-8 解码，允许 UTF-8 BOM；正文换行保持原样。非 UTF-8、空正文、无法读取的目录或文件会明确报错，不在部分文件失败后声称全库查完。跳过隐藏文件／目录、`node_modules`、`__pycache__`、`venv` 及非 MD/TXT 文件。目录中的符号链接会报错，不跟随链接读取外部资料；根路径显式指定为链接时，以其解析出的目录为所选根。

## 检索、回读与引用

`search` 一次最多 6 个 `--query`，每条用空格分隔词组，例如 `'小众 平庸'`；默认任一词命中，`--match all` 要求该组词全部出现。多条 query 是不同路径，不要求全部成立。长整句不会自动做语义理解，应先改写成短词组。可以用 `--author`、`--collection` 和 `--title-only` 缩小范围。

搜索结果只是词面候选，不是已经提取的观点或适配结论。同文副本会折叠并保留 `copies`，同标题不同正文不合并；近似版本仍要人工辨认。AI 等英文词按字母数字边界匹配，不会因 Airbnb、mail 中包含相同字母而命中。搜索兼容 Unicode 字形及中文词中间的单个硬换行；返回摘录、逐字引文核对不改写原文。

`read` 默认最多 10000 字；查看 `has_more`，为真时继续用 `--start` 读取 `next_start`，直到读完相关完整论述。`--around '原字' --context 1500` 定位片段，`--occurrence 2` 选择第二次出现；片段阅读不能冒充全文。大结果可保存到本次任务目录后分段读，工具显示截断和脚本分页是两件事。

引用使用 `verify` 或 `verify-card`。长引文可放在 UTF-8 文件中使用 `--quote-file`，文件含换行时按原样比较。版本和正文指纹最好一起传入；只匹配到了文字，不能证明作者立场、历史事实正确或适合当前文本。原句成功退出 0，不匹配退出 1，缺库、编码或参数错误退出 2。

`verify-card` 支持单张卡、卡数组、或 `{"cards":[...]}`；每张卡含 `source.article_id`、`source.article_version`、`source.text_sha256`、`quote`、`reasoning_excerpt`，以及可选 `cases[].excerpt`。原句、论述及事例分别核验。无独立事例时用空 `cases`，不要为过检查编造材料。

## 可选：已有专用阅读库

只有已经拥有以下数据结构并愿意接入的人才用这些适配；仓库不提供相应私有数据，也不会自动下载或导入。

- `--source reading`：显式设置 `VIEWPOINT_CORPUS_ROOT`，指向包含 `src/prw/corpus.py` 的可信阅读库。此模式会导入该库的 Python 代码，需要 Python 3.10+；只对你自己的可信项目启用。`articles()` 返回记录需具备当前脚本读取的字段。不是任意文章文件夹的入口；普通文件夹使用 `--library`。
- `--source books`：显式设置 `VIEWPOINT_BOOK_ROOT`，指向包含 `data/raw_texts/` 的旧版五本沟通书库根目录，支持 `===== 第 N 页 =====` 页码标记。普通书籍 TXT 可直接用通用文件夹模式。
- `VIEWPOINT_PAGE_ROOT` 可选：仅在 `reading` 模式需要本机索引链接时指定；未配置不扫描相邻目录。

```bash
python3 scripts/library.py status --source reading
python3 scripts/library.py search --source reading --query '用户 替换成本'
python3 scripts/library.py status --source books
python3 scripts/library.py search --source books --query '边界 拒绝'
```

`read` 和 `verify` 根据所给编号识别来源；`file:` 需要同一 `--library`，`book:` 需要书库配置，其他阅读库 ID 需要显式配置的 `VIEWPOINT_CORPUS_ROOT`。不会在不同数据源间偷偷改查。书籍有多版本时用搜索返回的完整 ID，不猜简写；单页读完不代表整章读完，没有页码的全文不虚构页码。

## 没找到时

先区分执行错误和成功零命中。正常零命中可以换场景词、关系词、相反说法，或查作者／标题再读完整文章；不要只重复行业名称。多条路径仍没好候选时，交已查范围、最近材料、差异和下一步，不硬塞万能观点。需要外部补查时说明渠道、计划和费用，沿用当前授权执行。
