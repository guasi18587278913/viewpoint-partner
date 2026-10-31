# Wiki 在本 Skill 中的用途

观点内容先从得到及阅读书库取。Wiki 在需要时帮助挑切入、组织论据或把观点接入文本，不替代观点原文。

- **只找作者原话、观点和事例**：不必增加 Wiki 方法阅读。
- **话题还很宽、需要探索切入问题**：读 `workflows/creation_teacher`、`workflows/topic_planning`、`methods/playbook/playbook-topic-divergence`；只为当前问题找不同入口，不自动另选题或写整稿。
- **将观点接入现稿、改写表达**：读 `workflows/creation_teacher`、`concepts/body_expression_quick`，然后只读采用的条目及 `concepts/body_expression#不照学`。

本轮最常用的定向入口：

| 要解决的事 | 页面 |
|---|---|
| 观点有论据、理由不重复 | `concepts/body_expression#13` |
| 保留成立条件 | `concepts/body_expression#17` |
| 正面回应可能的反对理由 | `concepts/body_expression#20` |
| 素材确有反差时点破 | `concepts/body_expression#34` |
| 表达判断且不超出材料 | `concepts/body_expression#51` |

用 `gbrain_sc_media.get_page`（Claude Code 里同一个库叫 `sc-media-kb`，即 `mcp__sc-media-kb__get_page`）读当前页，不直接读 wiki-v2 正本文件；同一会话已读且未变的不重复读。用户要求离线或 MCP 不可用时，可用本 Skill `wiki-snapshots.json` 的完整选中条目，交代快照日期，不冒充实时核验；没有适合条目也可以按原材料继续，明确是本次应用判断。

快照用于有限方法的离线回查，不代表全库方法覆盖，也不含可冒充用户事实的事件。快照保留原始正文与 content_hash；后续维护必须通过 get_page 更新，不偷偷将助手概括替换原文。

真正改稿后，按当前 Wiki 的要求附简短“这次用了什么”：所用写法 → 改了哪句 → 为什么。只查观点时交出处和适配理由即可，不把回复扩成方法课。
