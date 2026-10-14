# F4 实现计划：自然语言检索与跨文件问答

- 日期：2026-10-14
- 状态：设计稿初稿，待评审
- 阶段：无独立阶段。功能已实现，本稿是**验收与加固计划**，不新增检索能力
- 共享契约：见 `2026-10-14-personal-file-space-program-design.md`（下称程序稿）。
- **已登记到程序稿**：本稿需要的概念 `C-11` 与两列已并入程序稿 §3 与 §4.2，定义以那份为准；本稿只说明为什么需要它们。
- 组件定位：本稿不新增组件。它验收程序稿 P1 交付的 `CP-6`（scope 收口）连同五路检索在底座改动后的既有行为。

## 1. 功能定义与验收标准

**功能**：用自然语言提问，得到一份只依据语料内证据、带编号引用、跨多篇文档的答案。

本功能在 `main` 上**已经可用**，因此本稿的验收标准针对的是「换成个人文件空间语料与中文之后，它是否还成立」。

| 编号 | 判据 | 判定方式 |
|---|---|---|
| A4-1 | 五路检索在个人文件语料上均能出候选，或明确声明降级 | 每路断言有候选或有非 `success` 的轨迹状态 |
| A4-2 | 中文提问能命中关键字层，或明确记录该层对中文无效并给出替代路径 | 中文样本集上测关键字层命中率，低于阈值则必须走 §3.2 的决策 |
| A4-3 | 跨文件问答的引用指向至少两篇文档 | 多文档问题的答案断言引用文档数 ≥ 2 |
| A4-4 | 无答案时报告缺口，不用模型先验填空 | 保留并在新语料上重建 `unanswerable` 探针 |
| A4-5 | 答案的每条引用可回溯到具体 chunk | 断言引用编号能映射到检索结果 |
| A4-6 | 历史版本与被 scope 排除的文档不出现在候选或答案中 | 与 F3 共用的对抗性测试 |
| A4-7 | 非流式与流式聚合同一事件流 | SSE 与非流式两条路径返回同一序列，回归测试 |
| A4-8 | 空补全按失败处理而不是当成答案 | 既有行为的回归测试 |
| A4-9 | 时间范围过滤对个人文件有效 | 用 `C-11` 过滤能筛出预期文档数 |

## 2. 现状核对

已实现且有源码依据的部分：

- 五路检索：`vector`、`keyword`、`graph`、`community`、`hyde`，定义于 `src/sci_rag/retrieve/types.py:24`。
- 融合与权重：`domain/domain.yaml` 的 `retrieval.weights`（vector 1.5、keyword 1.0、graph 0.8、community 0.6、hyde 1.2）与 `rrf_k`、`candidate_limits`。
- 配置档与路由：`interactive`（向量加关键字）、`deep`（全部五路）、`auto`（按问题路由），`sci-rag retrieve --profile` 与 `--explain-routing` 可选（`src/sci_rag/cli/main.py:530-560`）。
- 分阶段耗时：`sci-rag profile` 输出每层 p50 与 p95，并声明各层并发因此耗时不相加。
- 引用的答案：从检索到的段落生成，逐条编号；无答案时报告缺口。
- 问句感知压缩：`src/sci_rag/answer/compress.py`，模型输出只作优化提示，绝不作为新证据；摘要缺失或非法时回退到完整文本。`domain/domain.yaml` 里 `compression.relevance_floor` 为 0.0，即只摘要不丢弃。
- 脱敏式降级：某一层超时或失败时该层不出候选但请求继续，轨迹写明状态。轨迹不含内容。
- 空补全按失败处理（不是零成本兼容）。
- HyDE 只作检索探针，永不作为证据或引用来源。
- REST `/v1/query`、`/v1/answer`（含 SSE），MCP `search_corpus`、`answer_question`，共用同一服务层。
- 检索侧已有元数据过滤：`year_min`、`year_max`、`authors`、`journals`、`exclude_dois`、`exclude_retracted`（`src/sci_rag/retrieve/types.py:44-56`）。
- 撤回感知的默认值是有意不一致的：检索侧默认关闭，答案路径打开，因为「引用一篇已撤稿论文当活证据」才是真正致命的失败（`types.py:52-56`）。

## 3. 设计与加固项

### 3.1 个人文件语料使评测基座失效

`data/demo/` 是五篇合成的农业残留物文档。F2 换掉本体之后，这批语料不再是有效样本：它的实体类型与新本体不匹配，抽取结果会大面积落到「未知类型」丢弃分支。

因此本稿的第一项交付物是一套**新的合成语料**，放在 `data/demo-personal/`，要求：

- 覆盖 F1 的全部七类文件，含至少一封邮件与一张扫描件。
- 含三篇内容相近的文档与一篇不相关的文档，供 F3 的相似度验证复用。
- 含一个需要跨两篇以上文档才能回答的问题。
- 含至少一个 `unanswerable` 探针。
- 全部为合成内容且无第三方权利，遵循 `data/demo/` 的既有做法。

### 3.2 中文关键字层失效（本稿最实质的缺口）

`chunks.search_tsv` 是 Postgres 生成列，表达式写死为 `to_tsvector('english', content)`（`src/sci_rag/db/models.py:124-127`）。中文没有空格分词，`english` 配置对中文段落的切分结果几乎没有可用词元，关键字层在中文语料上基本不出候选。这直接违反 A4-1 与 A4-2。

中文检索的候选方案与权衡：

| 方案 | 做法 | 代价 |
|---|---|---|
| A 改 `simple` 配置 | 把生成列换成 `to_tsvector('simple', content)` | 切分只在空白与标点处发生，中文长句成为一整个词元，召回仍然很差；且改生成列必须删列重建并 reindex |
| B 加 `pg_trgm` 通路 | 启用 `pg_trgm` 扩展，用 GIN 三元组索引支持中文子串匹配 | `pg_trgm` 属 contrib，但需确认 CI 用的 `pgvector/pgvector:pg16` 镜像里可用；三元组对短查询的选择性一般 |
| C 装中文分词扩展 | 如 `zhparser`、`pg_jieba` | 镜像与部署都要带这个扩展，破坏「一个官方镜像即可跑」的现状，CI 与本地需同步 |
| D Python 侧先分词 | 用 `jieba` 之类把正文切成空格分隔的词元存进另一个列，再对该列建 `simple` 的 tsv | 保住 vanilla Postgres；但 `search_tsv` 不再是数据库维持的生成列，丢失「Postgres 自己保持同步」这条既有的简单性 |
| E 只作文档 | 声明关键字层对中文降级，中文检索靠向量与图两层 | 明确、便宜、诚实，但放弃「关键词能抓住嵌入会模糊的标识符」这个关键字层存在的理由 |

**推荐 B 加 D 的组合路径**，先做 B：`pg_trgm` 不需要非标准扩展、不改变现有 `search_tsv` 生成列、对中文子串（人名、编号、专有名词）恰好是强项，与关键字层「抓标识符」的原始目的吻合。D 作为 B 不达阈值时的第二步。

这一条**必须先用 spike 定夺**，不能凭推断。spike 内容：在新合成语料上构造一组中文查询（含专有名词、编号、长句各若干），量三个候选的召回与 p95 延迟，再决定。选型结果回填本节。

### 3.3 时间过滤对个人文件失效

`year_min` 与 `year_max` 过滤的是 `publication_year`（`types.py:92-95`），而个人文件里这个字段绝大多数为空：邮件、笔记、合同、扫描件都不声明出版年。结果是时间范围过滤对个人语料几乎筛不出东西，A4-9 不成立。

需要一个新的时间概念，它必须统一，否则会出现多个都叫「时间」的东西：

- 定义见程序稿新增的 `C-11 文档日期`。
- 取值优先级：邮件 Date 头、文档属性里的修改时间、文件系统 mtime、摄取时间。取第一个非空者。
- 与 `publication_year` 是两个概念，不得合并。`publication_year` 是文档**声明**的出版年（学术语义），`C-11` 是资源**实际**的时间点（文件语义）。同一份个人文件可能两者都有且不同。

### 3.4 提示词与答案的语言

仓库把「英文中心」列为明确的取舍（`docs/choosing-sci-rag-kit.md` 的 concessions 一节）。中文个人文件空间需要把这些提示词本地化。仓库已经有这条通路：`domain/prompts/prompt_localization.md`。本稿要求：

- 对该提示词走一遍本地化流程，产出中文版本。
- 答案语言跟随提问语言，而不是固定英文。
- 压缩提示词同样处理，否则中文 chunk 会被英文摘要指令处理，压缩产出质量不可控。

### 3.5 检索层与关系层的衔接

`domain/domain.yaml` 的 `retrieval.graph.include_citations` 为 `false`，即引用关系**不参与检索**。F3 建好引用数据之后，是否打开它属于检索行为变更，需要同语料的前后消融。本稿把它列为可选步骤并明确：未做消融则保持关闭，交付说明必须写明这一点。

同理，`HyDE` 与 `community` 两层的开启与否都受 `is_unrestricted()` 影响（`types.py:61-80`）。F3 与 F5 若给 `RetrievalScope` 新增字段，`is_unrestricted()` 必须同步更新，否则社区层会在受限请求下错误地参与，把跨文档聚合的摘要泄漏给不该看到它的调用方。

### 3.6 跨文件问答的能力边界

仓库明确不提供 per-question 的 agent 循环（`docs/choosing-sci-rag-kit.md` 的 concessions：一个问题走一条检索管线加一次答案生成）。本稿不改这一点。个人文件空间的跨文件问答因此是**单轮**的：靠五路检索的候选广度覆盖多文档，而不是靠迭代追问。

代价要写清楚：需要多跳推理的问题（先找到 A，再据 A 找 B）不在本管线能力内。补偿手段是把图层的多跳能力用足（`graph.py` 已支持沿实体关系扩展），以及在 F5 的浏览层提供人工沿关系跳转的入口。若将来要做 agent 循环，应当置于本管线之上，而不是改本管线。

### 3.7 错误处理

沿用既有契约不变：某层超时或失败时该层不出候选、请求继续、轨迹写明状态；轨迹只含阶段名、状态、耗时与计数，绝不含查询文本、chunk 文本、密钥或私有文档数据。

## 4. 数据模型与迁移

本稿对契约的贡献已并入程序稿，此处只记录**为什么**需要，具体的类型、默认值与索引定义见程序稿 §4.2，不在此重复。

### 4.1 为什么需要文档日期

`year_min` 与 `year_max` 过滤的是 `publication_year`（`src/sci_rag/retrieve/types.py:92-95`），而个人文件里这个字段绝大多数为空：邮件、笔记、合同、扫描件都不声明出版年。因此需要一个基于资源实际时间点的替代维度，即程序稿的 `C-11 文档日期`，承载列为 `doc_date` 与 `doc_date_source`。

取值优先级（四种来源取第一个非空者）与它和 `publication_year` 的区别都定义在程序稿 `C-11`。本稿强调其中不可省略的一点：**两者不得合并**。同一份个人文件可能既有声明的出版年，又有实际的文件时间，语义不同，合并会让「按时间浏览」的含义变得不可预测。

### 4.2 为什么需要列而不是 JSONB

判据见程序稿 §4.2.1。`doc_date` 的理由是它要参与范围过滤与排序，必须有索引；`doc_date_source` 的理由是它可能被用来筛「哪些文档的日期来自邮件」。若按 F5 的做法把 `extra["parser"]` 停在 JSONB，两者就是同一条判据在不同场景下的两个结论。

### 4.3 检索侧新增 scope 字段

`RetrievalScope` 增加 `date_min`、`date_max`（过滤 `C-11`），并在 `is_unrestricted()` 里同步登记，因为 `tests/unit/test_retrieval_scope.py` 逐字段钉住该函数。与 F5 的浏览过滤共用同一组字段，不重复定义。

## 5. 改动文件清单

| 文件 | 改动 |
|---|---|
| `data/demo-personal/` | 新增合成语料与清单（§3.1） |
| `domain/eval_seed_questions.jsonl` | 换成本人语料的问题集，含多文档问题与 `unanswerable` 探针 |
| `domain/eval_calibration_labels.jsonl` | 人工重标，因为问题集换了 |
| `domain/prompts/answer.md` 等 | 中文本地化（§3.4） |
| `src/sci_rag/db/models.py` | 新增两列；`search_tsv` 是否扩充取决于 §3.2 的 spike |
| `migrations/versions/0008_*.py` | 两列与一个索引（与程序稿同一次迁移） |
| `src/sci_rag/retrieve/types.py` | 新增 `date_min`、`date_max`，同步更新 `is_unrestricted()` |
| `src/sci_rag/retrieve/stages/keyword.py` | 若走 §3.2 的 B 或 D，增加中文通路 |
| `src/sci_rag/cli/main.py` | `retrieve` 与 `eval` 增加 `--date-min`、`--date-max` |
| `tests/unit/test_retrieval_scope.py` | 登记新字段 |

## 6. 测试计划

**单元测试**：

- `C-11` 取值优先级：四种来源的两两组合各一组用例；全空时落 NULL 而不是摄取时间之外的猜测。
- 作用域：新字段进入 `is_unrestricted()`，社区层在任一日期限制下被禁用。
- 事件流一致性：非流式与流式聚合出同一序列（A4-7）。

**集成测试**：

- 新语料上的端到端：`make demo` 级别的离线路径与带凭据的完整路径。
- 跨文件问答：断言引用文档数 ≥ 2（A4-3）。
- 无答案探针：断言报告缺口且不编造（A4-4）。
- 时间过滤：用 `C-11` 筛选出预期文档数（A4-9）。
- 中文关键字命中率：按 §3.2 的 spike 结论设定阈值，未达阈值则该层必须显式报告降级。

**对抗性测试**：

- 历史版本、被 scope 排除的文档、`unknown` 权利的文档，都不得出现在候选或答案中。
- 社区层在受限请求下必须被禁用，不得通过摘要泄漏跨文档聚合内容。
- 有界候选池下，scope 外的文档不得因为在池内被挤出而间接出现在答案里。

**必须声明的跳过**：中文关键字层的阈值只有在 spike 完成后才有意义。spike 未做之前，A4-2 必须标为未验证，不得以「检索整体可用」代替。

## 7. 验收命令

```bash
make db-up && uv run sci-rag db upgrade
uv run sci-rag ingest --manifest data/demo-personal/manifest.jsonl
uv run sci-rag retrieve "一个需要跨两篇文档回答的问题" --profile deep --explain-routing
uv run sci-rag answer "同一问题"
uv run sci-rag eval retrieval --ablation
uv run sci-rag eval answers
uv run sci-rag profile            # 各层 p50 与 p95
uv run pytest tests/unit -q -k "scope or event or date"
uv run pytest tests/integration -q -k "retrieve or answer or demo"
make check
```

## 8. 风险与不做的事

| 编号 | 风险 | 处置 |
|---|---|---|
| R4-1 | 换本体后旧 demo 语料失去意义，评测基座事实上重建 | §3.1 明确把它列为交付物而不是附录 |
| R4-2 | 中文关键字层的选型凭印象决定 | §3.2 要求先 spike；选型结果回填本稿 |
| R4-3 | 新增 scope 字段漏改 `is_unrestricted()`，社区层泄漏 | 该函数被 `tests/unit/test_retrieval_scope.py` 逐字段钉住，改字段必须同时改测试 |
| R4-4 | 压缩提示词未本地化，中文被英文指令摘要 | 与答案提示词一并处理，纳入 §3.4 |
| R4-5 | 把 `C-11` 与 `publication_year` 混用 | 两者定义写在程序稿，本稿明确不可合并 |
| R4-6 | 压缩的默认值随语料变化而不再成立 | `domain/domain.yaml` 明确写着「携带到另一个语料前要重跑闸门」。新语料上必须重跑成对评测，不能沿用 0.0 这个结论 |

**明确不做的事**：

- 不做 per-question 的 agent 循环（仓库明文取舍）。
- 不做重排器的默认开启。它默认关闭，开启需消融证据。
- 不改融合权重。权重变更需同语料前后消融。
- 不做 OCR 文本的二次版面理解（属 F1 边界）。
- 不把 HyDE 产出做成可选证据来源。

## 9. 依赖关系

**前置**：P0 清障；P1 的 `M-0008`（含 §4 的两列）；F1 全部七类文件可解析，否则 §3.1 的合成语料无法齐备；F2 的新本体，否则抽取在新语料上大面积失败。

**后置**：F5 复用本稿的 scope 字段与 `C-11`；F3 的对抗性测试与本稿共用一套；F6 不依赖本稿，但本稿的验收要在 F6 合并后重跑一次，确认 reconcile 没有改变检索结果。

**开放问题**：

1. 中文关键字通路选 A 到 E 中的哪一个，待 spike。
2. `C-11` 在邮件场景下取 Date 头是否总是优于文件 mtime。转发或导出的邮件 mtime 是导出时间，会失真，因此优先级取 Date 头；但要确认 Date 头缺失或格式非法时的回退顺序。
3. 新合成语料的规模。太小则评测置信区间宽到无意义，太大则每次 `make check` 变慢。倾向与现有 demo 同量级，另留一套更大的语料供 `make benchmark` 使用。
