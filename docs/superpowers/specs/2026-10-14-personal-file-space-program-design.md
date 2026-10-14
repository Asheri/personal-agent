# 个人文件空间改造：程序级设计契约

- 日期：2026-10-14
- 状态：设计稿初稿，待评审（尚未实现任何代码）
- 定位：`sci-rag-kit` 的**自有 fork**，改造为个人文件空间产品。不承担上游兼容义务，可自由加列加表，并可推翻仓库已记录的架构决策（须以 ADR 显式 supersede）。
- 范围：本稿只定义六个功能共享的部分。每份功能稿引用本稿的编号，不重复定义。

## 关联稿

| 编号 | 功能 | 稿子 |
|---|---|---|
| F1 | 自动读取并解析不同类型的本地文件 | `2026-10-14-multi-format-parsing-design.md` |
| F2 | 抽取关键实体、主题、项目、人物 | `2026-10-14-metadata-extraction-design.md` |
| F3 | 建立相似、引用、版本、所属项目关系 | `2026-10-14-document-relations-design.md` |
| F4 | 自然语言检索与跨文件问答 | `2026-10-14-nl-retrieval-qa-design.md` |
| F5 | 按项目、时间、主题浏览文件空间 | `2026-10-14-personal-space-browsing-design.md` |
| F6 | 随新文件出现持续更新已有知识 | `2026-10-14-incremental-update-design.md` |

## 1. 六项功能的现状判定

判定依据是 `main` 分支 `26cd433` 的源码，加上一条未合并的分支（详见 §6）。

| 编号 | 判定 | 一句话理由 |
|---|---|---|
| F1 | 部分实现 | 白名单只有 6 种后缀（`src/sci_rag/ingest/parsers.py:54`），无 Office、无 OCR、无邮件 |
| F2 | 部分实现 | 抽取机制完整且受本体约束，但出厂本体 9 类里没有 Person，且「项目」不是任何字段 |
| F3 | 部分实现 | 只有 DOI 引用一种关系（`src/sci_rag/db/models.py:150-164`），相似、版本、项目三项缺失 |
| F4 | 已实现 | 五路融合检索加带编号引用的答案，本轮不新增功能，只做验收与加固 |
| F5 | 部分实现 | 无项目维度、无按年过滤，REST 只有 7 个端点，无浏览界面 |
| F6 | 已实现未合并 | `feature/incremental-reconcile` 分支完成（`src/sci_rag/reconcile.py` 442 行），未合入 `main` |

## 2. 阶段划分

| 阶段 | 内容 | 为何排在这里 |
|---|---|---|
| P0 | 清障：合并 F6 分支、重编号 ADR、解决 `AGENTS.md` 冲突 | 不先合并，`C-4 版本链` 要改 `reconcile.py` 的 `updated` 语义，会在两个分支上各改一遍 |
| P1 | 共享底座：`M-0008` 迁移与元数据模型（§4） | F1 写元数据、F2 落项目、F3 建边、F5 过滤，全部依赖它 |
| P2 | F1 与 F2，可并行 | 二者互不依赖，都是底座的写方 |
| P3 | F3 关系层 | 需要 F2 的实体产出与底座 |
| P4 | F5 浏览层 | 需要 F3 的边作为浏览维度 |

F4 无阶段：它在 P4 之后做一次验收，确认底座改动没有破坏既有行为。

## 3. 概念索引

每个概念在此定义一次，功能稿只写「见 C-x」。

### C-1 文档身份（document identity）

- 定义：一篇文档在语料中的稳定身份，是它的源文件绝对路径。同路径即同文档，路径变化视为删旧增新。与 `content_hash` 的区别是：哈希回答「内容是否相同」，路径回答「这是不是同一个东西」。
- 数学形式：`id(d) = canonical_abs_path(source(d))`，等价类为同路径文件的集合。
- 指代：`Document.extra["path"]`，实现于 `src/sci_rag/ingest/fingerprint.py:path_from`。

### C-2 变更指纹（source fingerprint）

- 定义：判断源文件是否值得重新解析的廉价信号。它不是内容证明，只用于跳过。
- 数学形式：`fp(d) = (size, mtime_ns) ∈ ℕ × ℕ`。
- 指代：`Document.extra["source_fingerprint"]`，实现于 `src/sci_rag/ingest/fingerprint.py:SourceFingerprint`。

### C-3 内容哈希（content hash）

- 定义：分块文本的确定性摘要，是唯一性 backstop。指纹移动后由它裁决究竟是内容变了还是仅仅被重新保存。
- 数学形式：`H(d) = digest(concat(chunk_texts(d)))`。
- 指代：`Document.content_hash`，列定义在 `src/sci_rag/db/models.py:78`，唯一约束 `uq_documents_content_hash` 在 `:92`，实现于 `ingester.py:content_hash_for`。

### C-4 版本链（version chain）

- 定义：同一 `C-1 文档身份` 的历次修订构成的有向链。每个节点最多一个后继（后继关系 `version_of` 指向上一版本），因此结构是链而不是树。这条链与 F6 现有的「删旧插新」语义互斥，是本改造对既有实现最大的语义变更。
- 数学形式：链 `v₁ → v₂ → … → vₙ`，其中 `v_{k+1}.version_of = v_k.id`；入度 ≤ 1 且出度 ≤ 1，故为路径而非一般有向图。
- 指代：`Document.version_of`、`Document.version_seq`，由 `M-0008` 新增（§4.2），写入逻辑在 `reconcile.py` 的 `updated` 分支（§4.3）。

### C-5 当前版本（current version）

- 定义：链尾节点，即检索默认可见的那一个版本。历史版本在库中保留但默认不可见。
- 数学形式：`is_current(d) = 1 ⟺ ∄ d' : d'.version_of = d.id`。
- 指代：`Document.is_current`，由 `M-0008` 新增；过滤落在 `scope_conditions()`（§4.4）。

### C-6 项目（project）

- 定义：文档的归属容器，代表用户自己的一个工作单元（课题、客户、课程、长期项目）。与 `Document.source` 的区别是：`source` 是**来源桶**（文档从哪来），项目是**归属**（文档属于谁的哪件事），两者语义不同，不得合并。
- 数学形式：多对一映射 `π: Document → Project ∪ {⊥}`，`⊥` 表示未归类。
- 指代：`documents.project_id` 与新的 `projects` 表，见 §4.2。

### C-7 标签（tag）

- 定义：用户或抽取赋给文档的自由主题词，与项目不同，一篇文档可以有任意多个，且无需预先登记。
- 数学形式：`tags(d) ⊆ T`，`T` 为标签全集；与其他文档共享标签即 `tags(a) ∩ tags(b) ≠ ∅`。
- 指代：`documents.tags: text[]`，见 §4.2。

### C-8 文档相似度（document similarity）

- 定义：两篇文档在语义上的接近程度，由各自的居中向量余弦相似度给出。居中向量是该文档所有分块向量的加权平均方向，因此它丢失「一篇文档覆盖多个话题」的信息，这是为换取可索引而付出的代价。
- 数学形式：`ē_d = (Σᵢ wᵢ·eᵢ) / ‖Σᵢ wᵢ·eᵢ‖`，`sim(a,b) = cos(ē_a, ē_b) = (ē_a · ē_b) / (‖ē_a‖‖ē_b‖) ∈ [-1, 1]`。默认权重 `wᵢ = 1`，表格块可加权（见 F3）。
- 指代：新表 `document_embeddings`，见 §4.2。

### C-9 提及引用（mention citation）

- 定义：当文档 A 的正文里出现文档 B 的标题或文件名主干时，建立的引用边。它补的是 DOI 引用在个人文件上的失效面：私人文档、Office 文件、邮件、扫描件不会有 DOI。
- 数学形式：边 `(a → b)` 存在 `⟺ ∃ c ∈ chunks(a), ∃ k ∈ keys(b) : k ⊆ text(c)`，其中 `keys(b) = {title(b)} ∪ {stem(path(b))}`。
- 指代：`document_citations` 表的 `source`（取值 `mention`）、`evidence_chunk_id` 与 `confidence` 列，见 §4.2。

### C-10 主题（topic）

- 定义：一组相关实体的簇及其摘要，用于回答「这批文件都在讲什么」。它不是标签（标签是人或抽取赋的标注），而是聚类结果。
- 数学形式：`topic = (M, s)`，`M ⊆ KgEntity` 为成员集合，`s = summarize(M)` 为摘要文本，且 `s` 有独立嵌入 `emb(s)`。
- 指代：`kg_communities` 表，`src/sci_rag/db/models.py:259-280`。

### C-11 文档日期（document date）

- 定义：文档在**实际时间轴**上的位置，用于范围过滤与排序。与 `publication_year` 的区别是，后者是文档自己声明的出版年（学术语义），前者是资源本身的时间点（文件语义）。两者可能都存在且不同，不得合并。个人文件里 `publication_year` 绝大多数为空，因此时间维度的过滤必须建立在本文档日期上。
- 数学形式：`doc_date(d) = first_non_null(σ₁(d), σ₂(d), σ₃(d), σ₄(d))`，其中 `σ₁` 为邮件 Date 头，`σ₂` 为文档属性里的修改时间，`σ₃` 为文件系统 mtime，`σ₄` 为摄取时间。
- 指代：`documents.doc_date` 与 `documents.doc_date_source`，见 §4.2；消费方为 F4 的时间过滤与 F5 的时间浏览。

## 4. 共享底座契约

本节是 `M-0008` 与版本链语义的**唯一定义处**。功能稿一律引用本节的编号。

### 4.1 设计取舍

元数据不继续塞进 `Document.extra` JSONB。F6 的分支证明了 JSONB 可以做到零迁移，但那是因为它存的是一对一标量。本改造新增的三样东西都需要数据库能力：`C-5 当前版本` 要在五路检索的 SQL 里做条件，`C-6 项目` 要能改名与枚举，`C-8 相似度` 要 pgvector 的 HNSW 索引。JSONB 也能做，但要写表达式索引并放弃引用完整性，收益为负。

项目用独立表加单值外键，不建多对多。触发升级的条件写在 F3 §8：如果确认一篇文档要同时属于多个项目，再引入 `document_projects` 关联表。

本节的列清单**由功能稿反哺而成**，登记在案以免后人以为它是凭空定的：`project_id`、`tags`、`version_*`、`is_current` 来自程序级设计；`project_source`、`auto_tags` 由 F2 要求；`doc_date`、`doc_date_source` 与 `C-11` 由 F4 要求；`document_citations` 的两处修正由 F3 发现。功能稿只要求扩写本节，不得在别处另立定义。

### 4.2 迁移 M-0008

`documents` 新增列：

| 列 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `project_id` | `text` | NULL | 外键指向 `projects.id`，`ON DELETE SET NULL` |
| `project_source` | `text` | NULL | 取值 `manual`、`rule`、`inferred`；NULL 表示未归类。`manual` 之后不得被后续规则或推断改写（F2 A2-5） |
| `tags` | `text[]` | `'{}'` | 人工标签，配 GIN 索引 |
| `auto_tags` | `text[]` | `'{}'` | 自动标签，与人工标签分列，因为二者信任级别不同（F2 A2-6） |
| `version_seq` | `integer` | 1 | 链上序号，从 1 起 |
| `version_of` | `text` | NULL | 自引用外键指向 `documents.id`，`ON DELETE SET NULL` |
| `is_current` | `boolean` | true | 配部分索引 |
| `doc_date` | `date` | NULL | `C-11` 的统一日期，配 btree 索引 |
| `doc_date_source` | `text` | NULL | 取值 `email_header`、`doc_property`、`file_mtime`、`ingested_at` |

新增表 `projects`：`id`（pk）、`name`（唯一）、`slug`（唯一）、`description`（可空）、`created_at`、`updated_at`。

新增表 `document_embeddings`：`document_id`（pk，外键 `documents.id`，级联删除）、`embedding vector(EMBEDDING_DIM)`、`embedding_version`（text）、`updated_at`。索引：`HNSW (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)`，与现有 `ix_chunks_embedding_hnsw` 参数一致。

`document_citations` 的两处改动：

1. **复用既有 `source` 列承载「谁建的这条边」**，取值扩为 `crossref` 与 `mention`。本稿早前版本曾提议新增 `detected_by` 列，核对源码后撤销：`source` 已经在表达同一语义（`src/sci_rag/db/models.py:163`，默认 `crossref`），再加一列会让同一概念有两处定义。
2. **`cited_doi` 改为可空**，并加一条 CHECK 约束把两种检测器各自的不变式钉住：

```sql
ALTER TABLE document_citations ALTER COLUMN cited_doi DROP NOT NULL;
ALTER TABLE document_citations ADD CONSTRAINT ck_document_citations_detector CHECK (
  (source = 'crossref' AND cited_doi IS NOT NULL)
  OR (source = 'mention' AND cited_document_id IS NOT NULL)
);
```

原因：`cited_doi` 当前非空（`models.py:162`），而提及引用通常没有 DOI（F3 §4.2）。约束同时表达了「未解析的 DOI 指针合法」与「提及引用必须指向语料内文档」，且可被 SQL 直接断言，因此能写成测试。

新增列：`evidence_chunk_id`（text，可空）、`confidence`（float，可空）。

索引清单：`ix_documents_project_id`、`ix_documents_tags_gin`（GIN）、`ix_documents_auto_tags_gin`（GIN）、`ix_documents_is_current_partial`（`WHERE is_current`）、`ix_documents_version_of`、`ix_documents_doc_date`、`ix_document_citations_source`。

### 4.2.1 列与 JSONB 的判据

后续功能反复争论同一件事没有意义，因此把判据写死一次：

> 需要参与**过滤、排序或唯一性约束**的信息用列；纯描述性、仅供人读的信息用 `extra` JSONB。

`doc_date_source` 用列而 `project_confidence` 停在 JSONB，就是这条判据的应用：前者可能被用来筛「哪些文档的日期来自邮件」，后者只在人工复核时看一眼。按同一条判据，F5 明确不把 `extra["parser"]` 提升为列，因为它不参与过滤。

`upgrade()` 与 `downgrade()` 都必须是可逆的：`downgrade()` 删除上述列、两张表与全部索引，并先删除索引再删列。回滚后 `is_current` 的语义自动等效于全 true，检索行为与今天一致，因此回滚不需要数据修复。迁移文件的写法沿用 `migrations/versions/0007_embedding_dimension.py`：`revision = "0008"`、`down_revision = "0007"`，docstring 里写明运行前必须备份。

### 4.3 版本链对 reconcile 语义的变更

既有实现（`feature/incremental-reconcile`，`src/sci_rag/reconcile.py` 模块 docstring）的分类表里：

```
updated   content differs   -> delete old, then ingest
```

本改造把这一行的动作改为：

```
updated   content differs   -> 旧行 is_current=false, 该行 version_of 回指旧行, version_seq = 旧行 + 1, 然后摄取新行
```

其余分类（`added`、`unchanged`、`verify`、`metadata_only`、`removed`、`out_of_scope`、`no_path_recorded`、`failed`）保持不变。三个必须守住的性质：

1. `version_seq` 只增不减，且新行的 `version_of` 必须指向同一 `C-1 文档身份` 的上一版，不得跨文档连链。
2. `failed` 仍然保留旧文档，不产生新版本节点。版本链只在内容确实被成功替换时前进一格。
3. 一次 reconcile 里，任一文档身份最多产生一个新版本节点，保证中断重跑后的收敛性。

### 4.4 检索侧的 scope 收口改动

`C-5 当前版本` 的过滤落在 `scope_conditions()`（`src/sci_rag/retrieve/types.py:83`）。它是五路检索的唯一收口（`vector.py:26`、`keyword.py:29`、`graph.py:207`、`retriever.py:406`），改一处即全覆盖。

改动方式：在 `RetrievalScope` 上新增字段 `include_superseded: bool = False`，`scope_conditions()` 在它为假时追加 `Document.is_current.is_(True)`。

两条不可省略的连带改动：

1. `RetrievalScope.is_unrestricted()` 必须同步把 `include_superseded` 纳入判断。它现在的语义是「任何限制都关闭社区层」（`types.py:61-80`），而要求包含历史版本同样改变了社区摘要的成立前提，因此必须算作非 unrestricted。`tests/unit/test_retrieval_scope.py` 逐字段钉住了这个函数，新字段必须在那里登记。
2. 这是一次 scope 规则变更。按仓库规范，必须配对抗性测试，证明历史版本不会经任何一层进入候选或答案，包括有界候选池与社区层两条间接路径。

## 5. 所有功能稿共同遵守的约定

1. **每份稿的结构固定九节**：功能定义与验收标准、现状核对、设计、数据模型与迁移、改动文件清单、测试计划、验收命令、风险与不做的事、依赖关系。
2. **新增命令必须声明面板归属**。`src/sci_rag/cli/main.py:44-50` 定义了六个面板，新命令或命令组必须落在其中之一，帮助串一行、现在时、一个动作。
3. **测试分层与声明**。单元测试放纯逻辑，集成测试放数据库行为，`tests/server` 放 REST 与 MCP 契约。任何跑不了而被跳过的检查必须在交付说明里显式声明，跳过的集成测试不构成通过证据。
4. **不做的事要写明**。每份稿的第八节必须列出明确不做的项，避免范围在实现阶段自行膨胀。
5. **依赖编号**。功能稿之间用 `F1` 到 `F6` 互指，跨稿概念用 `C-1` 到 `C-11` 指 §3，存储用 `DS-*` 指 §6 的清单。

## 6. 存储与组件清单

### 数据存储

| 编号 | 载体 | 承担的概念 | 状态 |
|---|---|---|---|
| DS-1 | `documents` | C-1, C-2, C-3, C-4, C-5, C-6, C-7 | 扩列（M-0008） |
| DS-2 | `projects` | C-6 | 新建（M-0008） |
| DS-3 | `document_embeddings` | C-8 | 新建（M-0008） |
| DS-4 | `document_citations` | C-9 | 扩列（M-0008） |
| DS-5 | `kg_entities` / `kg_relationships` / `kg_communities` | C-10 与实体关系 | 不改 |

### 组件索引

上游指输入来自谁，下游指输出给谁。

| 编号 | 组件 | 上游 | 下游 | 阶段 | 落点 |
|---|---|---|---|---|---|
| CP-1 | 解析面 | 源文件（C-1） | DS-1、F2 | P2 | `src/sci_rag/ingest/parsers.py` |
| CP-2 | 抽取面 | DS-1 的分块 | DS-5、DS-1 的 project/tags | P2 | `src/sci_rag/graph/extractor.py` |
| CP-3 | 关系面 | DS-1、DS-3、DS-5 | DS-3、DS-4、F5 | P3 | 新增 `src/sci_rag/relate/` |
| CP-4 | 浏览面 | DS-1、DS-2、DS-5 | CLI、REST、MCP | P4 | `src/sci_rag/server/`、`src/sci_rag/cli/` |
| CP-5 | 增量面 | 源文件、DS-1 | DS-1（含 C-4 写入） | P0 | `src/sci_rag/reconcile.py` |
| CP-6 | scope 收口 | `RetrievalScope` | 五路检索 | P1 | `src/sci_rag/retrieve/types.py:83` |

## 7. 清障项（P0）

### 7.1 ADR 编号冲突

`docs/adr/0012` 被两个决策各占一次：`main` 上是 `0012-modelscope-deepseek-providers.md`，分支上是 `0012-document-level-reconcile.md`。

按既有 spec 自己写下的规则（`docs/superpowers/specs/2026-10-08-incremental-reconcile-design.md:218-219`）：谁先落地谁用 0012，后落地顺延为 0013。`main` 的 0012 已落地且被 5 处文档引用（`docs/choosing-sci-rag-kit.md:65`、`docs/extend.md:179`、`docs/faq.md:114,147,163`），并被 `tests/unit/test_docs_style.py:451-471` 与 `tests/unit/test_docs_shipped_defaults.py:292` 按编号钉死。因此：

- `0012-modelscope-deepseek-providers.md` 保持不动。
- 分支的 reconcile ADR 重命名为 `0013-document-level-reconcile.md`，并修正 `title`、`# H1`、正文自指编号。
- 该 spec 第 216 行的「新增 `docs/adr/0012-document-level-reconcile.md`」必须一并改为 0013，否则合并后自相矛盾。

### 7.2 未提交改动与分支的冲突

`main` 工作区有一份未提交的 `AGENTS.md` 重写（+278 / −109），而分支对同一文件有 3 行改动。合并前需要先决定：先提交重写再合并，并以重写的版本为语义基准去对齐那 3 行改动。

## 8. 风险登记

| 编号 | 风险 | 触发条件 | 处置 |
|---|---|---|---|
| R-1 | 版本链变更波及五路检索的 scope 语义 | `is_current` 过滤写错或 `is_unrestricted()` 漏改 | §4.4 的对抗性测试为放行门槛；先补测试再改实现 |
| R-2 | 旧语料没有 `C-1 文档身份` | 早期行只有 `source_ref` | 既有实现已把这类行报为不可 reconcile 而不是猜测（`fingerprint.py:path_from`），新版本链字段对它们保持 NULL 且 `is_current=true` |
| R-3 | `M-0008` 不可回滚 | 迁移写了不可逆 DDL | §4.2 要求 `downgrade()` 完整可逆，并在一次性数据库上验证双向 |
| R-4 | 本体与真实语料错配 | 出厂本体是农业领域 | F2 要求把 domain 换成个人文件空间领域，这是 P2 的前置 |
| R-5 | 英文默认提示词不适合中文个人文件 | 中文语料 | 复用仓库已有的 `domain/prompts/prompt_localization.md` 路径，见 F4 |

## 9. 撤销条件

出现下列任一情况，回到本稿修改而不是继续实现：

- `M-0008` 的回滚在一次性数据库上无法通过，说明底座设计有不可逆部分，需要重新拆迁移。
- 对抗性测试无法证明历史版本被隔离，说明把 `is_current` 放进 scope 收口不足以覆盖间接路径，需要改为在每个 stage 显式过滤。
- 个人文件语料上本体抽取的准确率低到目录规则与人工指派成为唯一可用来源，说明 F2 的推断部分应当降级为可选项。
