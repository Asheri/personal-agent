# F3 实现计划：建立文件之间的相似、引用、版本、所属项目关系

- 日期：2026-10-14
- 状态：设计稿初稿，待评审
- 阶段：P3
- 共享契约：见 `2026-10-14-personal-file-space-program-design.md`（下称程序稿）。
- **已登记到程序稿**：本稿发现的两处冲突已并入程序稿 §4.2 的修正说明，SQL 定义以那份为准；本稿只说明发现过程与原因。
- 组件定位：本稿拥有 `CP-3`（关系面，P3），上游是 `DS-1`、`DS-3`、`DS-5`，下游是 `DS-4` 与 F5。`C-5 当前版本` 的过滤由程序稿 P1 交付的 `CP-6`（scope 收口）承担，不在本稿实现，本稿只负责不产生两个当前版本。

## 1. 功能定义与验收标准

**功能**：把「文件之间有什么关系」做成可查询、可浏览、可追溯的一等公民。四类关系各有不同的性质、更新时机与代价，不能用一个模型硬套。

| 编号 | 判据 | 判定方式 |
|---|---|---|
| A3-1 | 相似：内容相近的文档互为邻居 | 合成语料上，`relate similar` 把内容相近对的排名置于不相关对之前 |
| A3-2 | 相似随语料变化自动反映，无需全库重建 | 新增一篇文档后重查，公告其邻居变化且未跑批量重建 |
| A3-3 | 引用：两条检测通路都能建边 | 断言存在 `source='crossref'` 与 `source='mention'` 两类行 |
| A3-4 | 提及引用带可审计证据 | 断言每条 `mention` 边有 `evidence_chunk_id`，且该 chunk 文本确实含被引文档的键 |
| A3-5 | 未解析的 DOI 指针保留并在目标入库后自动解析 | 先建边得到未解析行，再摄取目标文档，重跑后该行变为已解析 |
| A3-6 | 版本链可双向遍历，序号单调，恰好一个当前版本 | 断言 `is_current=true` 的行数为 1，`version_seq` 严格递增 |
| A3-7 | 历史版本默认不进检索 | 与程序稿 §4.4 共用对抗性测试，五路逐一验证 |
| A3-8 | 删除版本节点后链仍自洽 | 删中间节点后链不断；删当前版本后前驱被提升为当前版本 |
| A3-9 | 每条关系可追溯来源与证据 | 断言四类关系都能回答「这条边谁建的、依据是什么」 |

## 2. 现状核对

| 关系 | 现状 | 证据 |
|---|---|---|
| 引用 | **部分实现，仅 DOI 一条通路** | `DocumentCitation`（`src/sci_rag/db/models.py:150-164`）：`citing_document_id` 必填、`cited_document_id` 可空、`cited_doi` 非空、`source` 默认 `crossref`。构建入口 `build_citation_edges`（`src/sci_rag/citations.py:57-62`），命令 `sci-rag graph citations` 默认 dry-run，MCP `get_citations` 双向查询（`src/sci_rag/server/mcp_server.py:221-228`） |
| 相似 | **完全缺失** | 只有 chunk 级向量近邻（`retrieve/stages/vector.py:26`）。全文检索 `similar_document`、`related_document` 在 `src/` 下零命中 |
| 版本 | **完全缺失，且与现有 reconcile 语义冲突** | `Document` 无任何版本字段（`models.py:56-85`）。而 `reconcile.py` 的 `updated` 动作是「删除旧行再摄取新行」，不保留历史 |
| 项目 | **完全缺失** | 无 project 字段；`Document.source` 是来源桶，语义不同 |

两点对设计有决定作用的既有事实：

1. 未解析的引用是一条**指针而不是边**。`citations.py:57-62` 明确写着：目标为空的行使目标入库后重跑即可解析。这说明引用表天然支持「先建后补」，提及引用可以复用同一模式。
2. 引用关系当前**不参与检索**：`domain/domain.yaml` 的 `retrieval.graph.include_citations` 为 `false`。

## 3. 设计

### 3.1 为什么不建通用的边表

四类关系看似都能塞进一张 `document_edges(source, target, kind)`，本稿明确不这么做，理由三条：

1. **代价不同**。相似度是派生值，可重算，每次摄取后自动变；版本是权威值，只能由写入方维护；引用是证据值，必须逐条可追溯；项目是单值属性，需要索引参与过滤。统一成一张表会让前者的重算成本波及后三者。
2. **基数不同**。项目是每文档一个值，相似是每文档 k 个邻居，引用是稀疏且可能有未解析目标，版本是链。
3. **已有实现**。`document_citations` 已经承担引用并已被 MCP 消费，重构成通用边表要动公开契约。

因此四类关系各用自己最合适的落点，见 §3.2。**引入通用边表的触发条件**写在 §8：若出现第五类关系，或 F5 需要一个跨四类关系的统一「相关条目」查询，则加物化视图而不是新表。

### 3.2 四类关系的落点

| 关系 | 落点 | 写入时机 | 是否参与检索 |
|---|---|---|---|
| 相似 | 新表 `DS-3 document_embeddings` 存居中向量，查询期算近邻 | 该文档摄取完成时；重嵌入时重建 | 否，由命令与浏览层消费 |
| 引用 | 既有 `DS-4 document_citations`，扩两列 | 离线批处理，默认 dry-run | 目前否；打开需先做消融实验，见 §3.4 |
| 版本 | `DS-1 documents` 的 `version_of`、`version_seq`、`is_current` | 只有 `reconcile.py` 与删除通路可写 | 是，历史版本被默认过滤 |
| 项目 | `DS-1 documents.project_id` | 摄取、规则、推断、人工指派 | 是，作为过滤维度 |

一条必须写死的**单一写入方**规则：`version_of`、`version_seq`、`is_current` 三列只允许两个地方写，即 `src/sci_rag/reconcile.py` 与文档删除通路。其他任何模块读而不写。违反这条会出现两个当前版本或断链，而这类不一致没有任何测试能事后发现。

### 3.3 相似：居中向量

居中向量的定义见程序稿 `C-8`。本稿补充实现细节：

- **权重默认全部为 1**。表格块加权更高看似合理，但按仓库规范，任何影响检索排序的改动都需要同语料的前后消融证据（`AGENTS.md` 的检索与评测条款）。因此权重作为一个可选精化项，默认关闭，开启需附消融结果。这与 `domain.yaml` 里重排器默认关闭的处理方式一致。
- **距离算子用余弦**，与既有 `ix_chunks_embedding_hnsw` 一致（`vector_cosine_ops`）。索引参数同样取 `m = 16, ef_construction = 64`（写法见 `migrations/versions/0007_embedding_dimension.py:67-72`）。
- **单分块文档**的居中向量即该分块向量，不做特殊处理。
- **无向量的文档**不写入 `document_embeddings`，并在 `doctor` 里计入一行计数。绝不能写入零向量冒充有效值。
- **查询默认排除自身**，返回带分数的前 k 个邻居，`min_score` 由调用方给，默认不设阈值。理由是个人语料规模小，过早阈值会把有用的弱关系切掉，而阈值应当由用户在看过分数分布后决定。
- **旧版本不参与相似邻居**，但它的居中向量保留，避免删除历史时还得连带处理派生表。

### 3.4 引用：两条检测通路

**通路一，`source='crossref'`**：既有实现不动。它要求文档有 DOI，对学术 PDF 有效，对个人文件基本无效。

**通路二，`source='mention'`**：新增。判据见程序稿 `C-9`，即文档正文中出现另一篇语料文档的标题或文件名主干。实现要点：

- 键归一化：casefold、去掉扩展名、折叠空白与常见分隔符。键长下限是关键参数，默认 8 个字符；低于下限的标题（例如 `notes`）不参与检测，否则误报会淹没有用信号。
- 自引用排除：文档提到自己的标题不建边。
- 置信度：标题完整匹配记 1.0，仅文件名主干匹配记 0.6。数值写进 `confidence`，供后续过滤。
- 证据：命中的 chunk 写进 `evidence_chunk_id`，命中的片段写进既有的 `evidence` 通路口径下可查的位置（`document_citations` 无 `evidence` 列，因此只存 chunk 引用与置信度，片段由 chunk 本身提供）。
- 幂等：与 `crossref` 通路一样逐次重建并对账，报告复用 `CitationBuildReport` 的形状（`documents_scanned`、`references_found`、`matched`、`unmatched`、`rows_written`、`rows_removed`）。
- 命令：`sci-rag graph citations --detector mention`，默认 dry-run，与既有默认一致。

**是否让引用参与检索**：本稿不改 `include_citations` 的默认值。打开它会改变图层的候选集，属于检索行为变更，需要同语料前后消融。把它列为可选步骤，附证据要求。

### 3.5 版本：链的维护

`C-4` 与 `C-5` 的定义在程序稿，本稿补充三处运维语义：

1. **删除中间节点**：`sci-rag corpus delete` 删掉一个有后继的版本时，把后继的 `version_of` 重新指向被删节点的前驱，保持链不断、序号无空洞。这一重新连接必须出现在删除报告里。
2. **删除当前版本**：删掉链尾节点时，把它的前驱提升为当前版本（`is_current=true`）。否则会出现「有历史版本但没有当前版本」的状态，检索将看不到这篇文档的任何版本，而用户以为自己只是删了一版。
3. **重嵌入**：`sci-rag embed reindex` 改变向量维度时，`document_embeddings` 必须一并失效并重建，与既有 `chunks.embedding` 的处理保持一致，避免出现两种维度的居中向量同时存在。

### 3.6 关系的读取面

| 入口 | 形态 |
|---|---|
| CLI | 新增 `relate` 命令组：`relate similar <doc> --top-k`、`relate versions <doc>`、`relate citations <doc> --detector`、`relate projects` |
| MCP | 扩展既有 `get_citations`；新增 `get_related_documents`（相似）与 `get_document_versions`（版本），一并暴露证据与来源 |
| 浏览层 | 由 F5 消费，本稿只保证四类关系都能按文档维度枚举 |

四个入口都走同一个服务层，避免 REST 与 MCP 之间的行为漂移。

### 3.7 错误处理

- 相似度计算失败（向量缺失、维度不符）：不写行，计入报告，不静默跳过。
- 提及检测的键集合为空（文档无标题且路径不可得）：计入 `unmatched` 而不报错。
- 版本链写入时发现同一身份已有更多后继：拒绝写入并报错，因为那意味着链变成了树，属于数据损坏。

## 4. 数据模型与迁移

本稿**不新增**超出程序稿的表或列。它在起草过程中发现两处与既有实现冲突的提案，结论已并入程序稿 §4.2；具体的列定义、约束 SQL 与索引清单以那份为准，此处只记录问题本身，以免后人重犯。

### 4.1 撤销 `detected_by` 列

程序稿早前版本提议给 `document_citations` 加 `detected_by` 记录「谁建的这条边」。核对源码后发现**该表的 `source` 列已经在表达同一语义**（`src/sci_rag/db/models.py:163`，默认值 `crossref`）。若照提案实现，「谁建的这条边」会有两个字段，属于同一概念两处定义。结论是复用 `source`，取值扩为 `crossref` 与 `mention`。

这条是本稿最有价值的产出：它是「起草阶段回源核对」拦下的一次重复定义，而不是实现阶段才暴露的返工。

### 4.2 `cited_doi` 必须放开非空约束

`cited_doi` 当前是 `nullable=False`（`models.py:162`），而提及引用通常没有 DOI，因此这一列必须放开。同时需要一条 CHECK 约束把两种检测器各自的不变式钉住，否则放开之后无法区分「合法的未解析 DOI 指针」与「写坏了的行」。约束的完整 SQL 见程序稿 §4.2。

这条约束值得写成测试：它同时表达了两件事，即未解析的 DOI 指针合法，以及提及引用必须指向语料内文档。两件事都能用 SQL 直接断言，因此都能进回归测试。

### 4.3 本稿需要的其余列

`evidence_chunk_id` 与 `confidence` 沿用程序稿 §4.2 的提案。`evidence_chunk_id` 是 `A3-4` 的实现方式，`confidence` 是提及引用分层置信度的载体（§3.4）。

## 5. 改动文件清单

| 文件 | 改动 |
|---|---|
| `src/sci_rag/relate/__init__.py`、`similar.py`、`versions.py`、`mentions.py` | 新增，四类关系的实现 |
| `src/sci_rag/ingest/ingester.py` | 文档写入完成后计算并写入居中向量 |
| `src/sci_rag/citations.py` | 抽出检测器接口，新增 `mention` 通路；`CitationBuildReport` 复用 |
| `src/sci_rag/corpus.py` | 删除通路维护链：重新连接后继、提升前驱、报告写明 |
| `src/sci_rag/reconcile.py` | `updated` 动作改为版本链写入（见程序稿 §4.3） |
| `src/sci_rag/embed/planner.py` | 重嵌入时一并失效 `document_embeddings` |
| `src/sci_rag/cli/main.py` | 新增 `relate` 命令组（面板归 `Ask questions` 或新增分组，见 F5 §5 的统一决定） |
| `src/sci_rag/server/service.py`、`mcp_server.py` | 三个读取入口；REST 与 MCP 同源 |
| `migrations/versions/0008_*.py` | 两处修正与其余列合并进同一次迁移 |
| `docs/` | 引用与关系页更新 |

## 6. 测试计划

**单元测试**：

- 居中向量：单分块退化、多分块加权、零向量拒绝、维度不符拒绝。
- 提及检测：标题完整匹配、仅文件名匹配、低于键长下限被跳过、自引用被排除、键归一化的边界（全角半角、大小写、多空格）。
- 版本链：正常推进、删除中间节点后重连、删除尾节点后提升、出现分叉时拒绝。
- 优先级与幂等：同一语料跑两轮引用重建，`rows_written` 与 `rows_removed` 收敛到零。

**集成测试**：

- 相似：合成三篇文档，两篇内容相近、一篇不相关，断言邻居排序符合 A3-1。
- 引用：先摄取引用方，再摄取被引方，断言未解析指针变为已解析（A3-5）。
- 版本：连续三次修改同一文件并重跑 ingest，断言链长、`version_seq` 与唯一当前版本。
- 删除：三种删除位置各一组用例，断言链自洽。

**对抗性测试**（与程序稿 §4.4 共用）：

- 历史版本不得经任何一层进入候选或答案，逐路验证向量、关键字、图、社区、HyDE。
- 提及检测不得把被 scope 排除的文档重新引入候选或答案。
- 有界候选池下，历史版本不得因为池子变小而挤占当前版本的位置。

**必须声明的跳过**：若未做消融，则 `include_citations` 保持关闭，交付说明必须写明引用未参与检索，不得以「引用数据已建好」暗示检索已用上。

## 7. 验收命令

```bash
make db-up && uv run sci-rag db upgrade
uv run sci-rag build /path/to/folder
uv run sci-rag relate similar <doc_id> --top-k 5
uv run sci-rag relate versions <doc_id>
uv run sci-rag graph citations --detector mention        # dry-run
uv run sci-rag graph citations --detector mention --apply
uv run sci-rag relate citations <doc_id>
uv run pytest tests/unit -q -k "relate or similar or mention or version"
uv run pytest tests/integration -q -k "relation or citation or version"
make check
```

## 8. 风险与不做的事

| 编号 | 风险 | 处置 |
|---|---|---|
| R3-1 | 提及检测误报：同名或标题过短 | 键长下限加自引用排除加置信度分层；证据 chunk 可人工审计 |
| R3-2 | 版本链写入出现分叉 | §3.7 的拒绝写入；`doctor` 增加「链完整性」检查，断言每篇文档至多一个当前版本 |
| R3-3 | 居中向量对覆盖多个话题的长文档失真 | 这是 `C-8` 明说的代价。缓解手段是分块级相似作为补充查询，但本稿不做，列为后续项 |
| R3-4 | 相似度随语料变化而无人知晓 | 相似不存边，天然随写入更新；每次查询现算，代价是查询期一次近邻检索 |
| R3-5 | 删除版本节点破坏链 | §3.5 的三条语义加删除报告的显式声明 |

**明确不做的事**：

- 不建通用边表。
- 不做 git 式的内容差异（diff）与三方合并，版本链只回答「哪一版是当前版、上一版是谁」。
- 不做跨文档的自动内容合并。
- 不做基于图结构的路径分析或中心性计算（架构文档已列为刻意不做的东西）。
- 不打开 `include_citations` 的默认值。
- 不把 `SUPERSEDES`（实体级内容关系，F2 的本体）与 `C-4 版本链` 互相推导。

**引入通用边表的触发条件**：出现第五类关系，或 F5 需要一个跨四类关系的统一「相关条目」查询时，加物化视图，不加新表。

## 9. 依赖关系

**前置**：P0 清障（版本链要改 `reconcile.py` 的 `updated` 语义，必须先合并 F6 分支）；P1 的 `M-0008`（含 §4 的两处修正）；F1 的分块质量影响提及检测的命中率；F2 的本体提供 `Project` 实体，用于与 `C-6 项目` 对照。

**后置**：F5 的全部浏览维度都来自本稿的边；F4 的验收需要本稿的对抗性测试证明历史版本被隔离。

**开放问题**：

1. 居中向量的表格块加权是否需要。取决于消融结果，默认关闭。
2. 提及检测能否从「标题与文件名」扩展到「文档内声明的别名」。候选做法是读 `documents.extra` 或 `KgEntity.aliases`，但会扩大误报面，先不做。
3. `relate` 命令组归哪个面板。与 F5 的新命令一起决定，避免两处各定一次。
