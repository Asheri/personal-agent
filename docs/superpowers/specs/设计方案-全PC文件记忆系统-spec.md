# 全 PC 文件管理记忆系统（PC-Mem）完整设计规格

- 日期：2026-10-14
- 状态：spec v1.1，独立审查判定「修订后放行」（P0=1/P1=7/P2=8），P0 与 P1 已在本版修订，
  审查全文与修订记录见 `设计方案-全PC文件记忆系统-spec审查.md`
- 定位：**sci-rag-kit 自有 fork（知识库底座）× GenericAgent（Agent 运行时与记忆面）** 的联合系统，
  面向「帮助 Agent 的全 PC 文件管理记忆」。不承担 sci-rag-kit 上游兼容义务；对仓库既有架构决策的
  推翻一律以 ADR 显式 supersede，不改写历史。
- 与既有文档的关系：
  - 取代并吸收 `设计方案-全PC文件记忆系统.md`（2026-10-14 早前方案，概念层合并进本稿）。
  - 吸收 `sci-rag-kit/docs/superpowers/specs/2026-10-14-*.md` 七份旧稿（程序稿 + F1-F6）的设计资产，
    **并按其评审报告（`2026-10-14-spec-review-report.md`）的 6 个阻断根因与主要 P1 修正**；
    未逐条收口的 P1 项（失败统计持久化、抽取丢弃计数、draft 采样面、命令面板归属、
    document_projects 触发条件等）已补入正文或列管于审查报告修订记录。
    旧稿中被评审推翻的结论一律不采用，采用处标注来源（`[沿用 F-x]`）。
- 证据纪律：`[代码实证]` 带 `文件:行号`，本轮亲自读取命中；`[评审实读]` 来自旧评审报告主审实读；
  `[沿用 F-x]` 来自旧稿（经评审修正）；`[推演]` 为本稿新设计，无代码证据。

---

## 0. 需求映射（验收总表）

原始需求六项 + 可探索难点，映射到本稿组件与验收编号：

| # | 需求 | 承载 | 验收 |
| :--- | :--- | :--- | :--- |
| 1 | 自动读取并解析不同类型的本地文件 | 解析面（§4.1） | A1-1 ~ A1-7 |
| 2 | 抽取关键实体、主题、项目、人物 | 抽取面（§4.2） | A2-1 ~ A2-8 |
| 3 | 建立相似、引用、版本、所属项目关系 | 关系面（§4.3） | A3-1 ~ A3-9 |
| 4 | 自然语言检索和跨文件问答 | 检索问答面（§4.4） | A4-1 ~ A4-9 |
| 5 | 按项目、时间、主题浏览 | 浏览面（§4.5） | A5-1 ~ A5-9 |
| 6 | 随新文件出现持续更新已有知识 | 增量面（§4.6） | A6-1 ~ A6-9 |
| 难点 | 长期记忆更新与遗忘、过期信息 | 记忆面（§4.7） | A7-1 ~ A7-2 |
| 难点 | Agent 何时主动调用哪些记忆 | 记忆调用路由（§4.7 第 2 项） | A7-3 |
| 难点 | 版本识别 / 跨文件实体对齐 / 自动项目归类 | §4.3（版本链）/ §4.2（同名合并）/ §4.2（项目归属） | A3-6 / A2-8 / A2-4 |
| 难点 | 多模态文件理解 | §4.1（OCR 起步） | A1-3 |
| 难点 | 从文件搜索升级为理解长期工作历史 | 研究项 R8（§6 P6 研究） | 研究验收（§7 研究豁免条款） |

每条验收判据的机械断言全文见**附录 A**。

**验收通则**（沿用旧稿 §5 并加强）：每条判据必须可机械断言（计数、状态枚举、退出码、SQL 断言），
禁止「公告/可用/合理」类非断言词；阈值类判据拆「机制项（立即可判）+ 效果项（spike 回填）」；
任何跑不了而被跳过的检查必须在交付说明里显式声明，跳过的集成测试不构成通过证据。

---

## 1. 系统概述

```
┌────────────────────────────────────────────────────────────────┐
│               GenericAgent 运行时（记忆面 + 执行侧）              │
│  agent_loop · 9 原子工具 · plugins/hooks · reflect/scheduler      │
│  L0-L4 分层记忆 · SOP 自进化 · 记忆调用路由（§5.7.3）              │
└──────────┬─────────────────────────────────▲───────────────────┘
      CLI/MCP 调用（code_run → sci-rag CLI；插件 → RagService）      │ 经验固化 / 主动注入
┌──────────▼─────────────────────────────────┴───────────────────┐
│                    服务面（sci-rag-kit server）                    │
│   RagService 单一门面 → REST + MCP（既有 8 工具 + browse/relate）   │
│   scope 收口：基线谓词 is_current + 权利/元数据过滤（§6）            │
└──────────┬─────────────────────────────────▲───────────────────┘
┌──────────▼─────────────────────────────────┴───────────────────┐
│              知识库底座（Postgres 16-18 + pgvector）               │
│  ingest(解析/切块/去重) → documents/chunks → graph(实体/社区)       │
│  → relate(相似/引用/版本/项目) → retrieve(五路融合) → answer(引用)   │
└──────────┬─────────────────────────────────▲───────────────────┘
┌──────────▼─────────────────────────────────┴───────────────────┐
│           文件感知层（新增薄层）：增量 reconcile + 触发器            │
│  Agent scheduler 定时 + hooks 事件 + OS 轮询兜底（§5.6.4）          │
└────────────────────────────────────────────────────────────────┘
                    C:\Users\<user>\ 下的异构文件
```

三层职责一句话：**文件感知层发现变化；知识库底座持有可检索、可追溯的事实；记忆面持有经验、
偏好与「何时查什么」的路由知识**。知识库是外部事实层（Postgres），GenericAgent L0-L4 是工作
记忆与经验层，两层不互相替代：知识库回答「文件世界里有什么」，记忆面回答「这个用户怎么工作」。

---

## 2. 共享概念（一次性定义，其余章节只引用编号）

每个概念给：通俗解释 → 形式定义 → 落点指代。**任何功能章节不得在别处另立定义。**

### C-1 文档身份（复合身份，评审 R-4 修正版）

- 通俗：一篇文档「是同一个东西」的判据。
- 形式：`id(d) = (canonical_abs_path(source(d)), member_key(d))`；
  单文档文件 `member_key = ""`；多成员文件（mbox、未来的压缩包）成员键 = 稳定成员标识
  （邮件优先 `Message-ID`，缺失时用「宿主内序号」兜底且**不迁移**：删中间一封不重排序号）。
  哈希回答「内容是否相同」，身份回答「这是不是同一个东西」。
- 落点：`Document.extra["path"]` + `Document.extra["source_member"]`（`source_member` 仅作
  应用层内存分组键，不建索引、不参与 SQL 过滤：显式决策，见 §4.2 三级判据第二档的例外说明）。
- 连带约束（评审 R-2/R-4 一并解决）：
  1. reconcile 的分桶键 = `(path, source_member)`；
  2. 宿主变更探针按成员聚合：`sha256("\n".join(sorted(member_hashes)))`，否则只改第 2..N 封
     邮件恒判未变；
  3. 版本链的「至多一个新版本节点」不变式作用于 `(身份, member_key)` 对。

### C-2 变更指纹 / C-3 内容哈希（沿用程序稿，评审无异议）

- 指纹 `fp(d) = (size, mtime_ns)`，不是内容证明，只用于跳过（`extra["source_fingerprint"]`）。
- 内容哈希 `H(d) = digest(concat(chunk_texts(d)))`，唯一性 backstop。
  **唯一约束修正（评审 R-3）**：`uq_documents_content_hash` 从全局唯一改为
  `CREATE UNIQUE INDEX uq_documents_content_hash_current ON documents (content_hash) WHERE is_current;`
  ingester 预检同步加 `.where(Document.is_current.is_(True))`。
  理由：保留历史后旧行哈希永久占位，「改回旧内容」（A→B→A）会被判 `skipped_duplicate` 静默出错。
  同内容不同路径的两份文件：按 `(content_hash, path)` 各自成文（全 PC 复制粘贴极常见，
  折叠会让用户看不到第二份文件且每轮重复解析击穿 A6-1）。

### C-4 版本链 / C-5 当前版本（沿用程序稿定义，写入通道按评审 R-2 重写）

- 版本链：同一 `(身份, member_key)` 的历次修订构成有向链，`version_of` 指上一版，入度 ≤ 1、
  出度 ≤ 1。允许因删除中间节点产生的 `version_seq` 空洞，只要求严格递增（评审 P1-02）。
- 当前版本：`is_current(d) = 1 ⟺ ∄d' : d'.version_of = d.id`。历史版本留库但默认不可见。
- **单一写入方规则（修订版）**：`reconcile.py` 决定、`ingester.py` 执行。版本三列
  （`version_of`/`version_seq`/`is_current`）除这条通道与删除通路外，任何模块读而不写。
  「违反会出现两个当前版本或断链，而这类不一致没有任何测试能事后发现」。
- 入度 ≤ 1 由部分唯一索引强制，不依赖应用层检查：
  `CREATE UNIQUE INDEX ix_documents_version_of ON documents (version_of) WHERE version_of IS NOT NULL;`
- **同事务不变式**：前驱降级（`is_current=false`）与后继插入在同一数据库事务内
  （ingester `session_scope()` 内先 flush 新行、再降级前驱）。任何时刻每个身份至少一个
  `is_current=true`。崩溃注入测试为放行门槛（评审 P1-06）。

### C-6 项目 / C-7 标签（沿用 F2/F5，评审 P1-48/49 修正落法）

- 项目：文档的归属容器（课题/客户/课程/长期项目）。`source` 是来源桶（文档从哪来），
  项目是归属（文档属于谁的哪件事），两者不得合并。多对一 `π: Document → Project ∪ {⊥}`。
- 标签：自由主题词，一篇文档任意多个。`tags` 只放人工、`auto_tags` 只放自动，分列存放
  （分列理由按 §4.2 三级判据第二档：承载应用不变式与审计，不只是「信任级别」）。
- 项目三来源优先级：`manual > rule > inferred`，`project_source` 为列（承载锁定不变式）；
  人工指派写入后任何规则或推断轮次都不得改写 `project_id` 与 `project_source`；
  推断失败或置信度缺失时**不改动**原有归属，只在报告计失败（评审 P1-48）。
- 项目表定型（评审 P1-17）：`projects.id` 为稳定标识（URL 与过滤参数用，复用 `new_id()`），
  `slug` 为人读别名（`slugify(name)`，冲突加序号），可随改名变；过滤参数统一接受 id，
  slug 为人读便利；未知标识报 `404 project_not_found`。

### C-8 文档相似度（沿用 F3，评审无异议部分）

- 居中向量 `ē_d = normalize(Σᵢ eᵢ)`（权重默认全 1，加权属精化项默认关闭，开启需消融证据）；
  `sim(a,b) = cos(ē_a, ĕ_b)`。无向量文档不写行，**绝不用零向量冒充**；旧版本不参与邻居但保留向量。
- 相似不存边，查询期现算，天然随语料更新。

### C-9 提及引用（沿用 F3，评审 P1-18/19/20 修正）

- 文档 A 正文出现文档 B 的标题或文件名主干（键集 = 标题 ∪ 路径主干）即建边。
- 参数：键归一化（casefold、去扩展名、折叠空白分隔符）；键长下限 8 字符；自引用排除；
  置信度（标题全匹配 1.0、仅文件名主干 0.6）；证据 chunk 写 `evidence_chunk_id`。
- 消歧（评审 P1-20，取保守方案）：命中多个候选即判歧义，不建边，计入 `unmatched`。
- 对账键（评审 P1-18）：mention 通路用 `(citing_document_id, cited_document_id)`，按
  `source == detector` 过滤 existing；配部分唯一索引
  `uq_document_citations_mention ... WHERE source='mention'`。
- 检测器冲突（评审 P1-19，取前置条件方案）：mention 候选阶段跳过已存在 crossref 边的对，
  C-9 判据加前置「且不存在 crossref 边」。
- 未解析 DOI 指针（crossref 通路）合法保留，目标入库后重跑解析（沿用既有 `citations.py` 语义）。

### C-10 主题簇 / 命名主题（术语消歧，评审 P1-43 修正归属）

- **命名主题**：文中明确写出的主题词，`KgEntity(entity_type='Topic')`，抽取产生、带证据 chunk。
  分面与过滤**一律**用命名主题。
- **主题簇（C-10 仅指此）**：`kg_communities` 的实体簇 + 摘要 + 摘要嵌入，无逐条证据归属。
  概览与摘要**一律**用主题簇；**不做过滤**（用模型生成的簇切分用户可见集合不可审计）。
- 行文出现「主题」必须带限定词。

### C-11 文档日期（沿用 F4）

- `doc_date(d) = first_non_null(邮件 Date 头, 文档属性修改时间, 文件系统 mtime, 摄取时间)`。
- 与 `publication_year`（学术语义）严格二分，不得合并。`doc_date` 参与范围过滤与排序故为列，
  `doc_date_source` 取值 `email_header|doc_property|file_mtime|ingested_at`。
- 时间过滤的 NULL 语义（评审 P1-15）：`or_(Document.doc_date.is_(None), Document.doc_date >= date_min)`，
  无日期文档不被静默排除（照 `exclude_dois` 先例）。

### C-12 记忆层映射（本稿新增，旧稿无）

- 知识库（外部事实层）与 GenericAgent L0-L4（经验层）的对应：

| GA 记忆层 | 载体 | 与知识库的关系 |
| :--- | :--- | :--- |
| L0 元规则 | `assets/sys_prompt*.txt` + `memory/memory_management_sop.md` | 不变；写记忆前必读 |
| L1 索引 | `memory/global_mem_insight.txt`（≤30 行硬约束） | 索引「项目名→project_id、常用查询、记忆路由表」，只留指针 |
| L2 事实 | `memory/global_mem.txt` | 用户环境事实（目录布局、文件约定、常用项目 slug） |
| L3 SOP | `memory/*.md`、`memory/*.py` | 文件记忆系统操作 SOP（何时查知识库、用哪个命令、典型坑） |
| L4 归档 | `memory/L4_raw_sessions/` | 会话归档；文件原文归档在知识库，L4 只存会话指针 |

- 形式：记忆是「指针层」，知识库是「事实层」。L1-L3 只允许存「经行动验证且跨会话复用」的内容
  （GA 记忆公理「No Execution, No Memory」），文件级细节一律指针化到 `documents.id / project_id`。

### C-13 访问热度与新鲜度（本稿新增）

- 热度信号：GenericAgent 的 `file_access_stats.json`（`ga.py:158-166` [代码实证] 记录 memory 文件
  访问次数与最近日期，本稿扩展到知识库查询日志）+ 查询命中记录。
- 新鲜度：`stale` 判定 = 被新版本替代（C-4）∨（一年无访问 ∧ 存在同主题新文件）。
  **只标记不删除**（GA 记忆公理「神圣不可删改」：可压缩、可迁移层级，不可丢失）。

---

## 3. 存储契约（M-0008-R：评审修正版迁移）

### 3.1 列与 JSONB 三级判据（评审 P1-21 两级化后再补一级）

> 1. 参与**过滤、排序或唯一性约束**的信息 → 列 + 索引；
> 2. 承载**应用不变式或审计**但不进 SQL 谓词 → 列，不建索引；
> 3. 纯描述性、仅供人读 → `extra` JSONB。

应用：`doc_date`（第 1 档，btree 索引）；`project_source`（第 2 档，锁定不变式 A2-5 的断言载体）；
`project_confidence`、`extra["ocr"]`（第 3 档）。`source_member` 显式例外：仅应用层内存分组键，
不建索引（若未来参与 SQL 唯一性，按第 1 档提升为列并入同次迁移）。

### 3.2 `documents` 新增列

| 列 | 类型 | 默认 | 说明 |
| :--- | :--- | :--- | :--- |
| `project_id` | `text` | NULL | FK → `projects.id`，`ON DELETE SET NULL` |
| `project_source` | `text` | NULL | `manual`/`rule`/`inferred`；NULL=未归类；manual 后锁定 |
| `tags` / `auto_tags` | `text[]` | `'{}'` | 人工/自动标签分列，各配 GIN |
| `version_seq` | `integer` | 1 | 链上序号，允许空洞，严格递增 |
| `version_of` | `text` | NULL | 自引用 FK；`ON DELETE SET NULL` 仅兜底，删除必须走 §5.3.4 重连逻辑 |
| `is_current` | `boolean` | `true` | 部分索引 `WHERE is_current` |
| `doc_date` / `doc_date_source` | `date` / `text` | NULL | C-11 |

新表：`projects`（§C-6 定型）、`document_embeddings`（居中向量，HNSW `m=16, ef_construction=64`
与既有 chunk 索引一致）、`file_events`（扫描事件，供增量回溯）。

`document_citations` 扩列：`evidence_chunk_id`、`confidence`；**`cited_doi` 放开非空**并加 CHECK：

```sql
ALTER TABLE document_citations ALTER COLUMN cited_doi DROP NOT NULL;
ALTER TABLE document_citations ADD CONSTRAINT ck_document_citations_detector CHECK (
  (source = 'crossref' AND cited_doi IS NOT NULL)
  OR (source = 'mention' AND cited_document_id IS NOT NULL)
);
```

（复用既有 `source` 列承载「谁建的边」，不新增 `detected_by`：同一概念不两处定义，沿用程序稿的撤销决策。）

### 3.3 迁移纪律

- `downgrade()` 可逆但**数据不可逆**（评审 P1-08）：回滚前必须 `sci-rag corpus snapshot`；
  `downgrade()` 内先折叠版本链（每身份保留 `max(version_seq)` 一行、删其余并写审计），
  再按「索引 → 外键 → 列 → 表」顺序删除。
- 旧语料回填：`server_default` 保证 `is_current=true`；验收断言 `count(is_current=true) == count(documents)`。
- 向量维度漂移（评审 P1-45）：维度变更脚本的表清单必须含全部三张向量表
  （`chunks`、`document_embeddings`、`kg_communities.summary_embedding`），配一致性断言。
- ADR 产出物（评审 P2-7）：M-0008-R 落地须产出 ADR（0014 起，四节形状：context、decision、
  consequences、reversal conditions），至少覆盖版本链决策、`content_hash` 约束改写、
  `is_current` 基线谓词三条；旧稿（2026-10-08 reconcile 稿）受影响节只加修订说明，不改写历史。

---

## 4. 功能设计

### 4.1 解析面（F1，`ingest/`）

**复用**：`Block`/`ParsedDocument` 共享块模型（`parsers.py:37,44` [代码实证]）为唯一中间表示，
所有新解析器只做「源文件 → `list[Block]`」；PDF 双路（Docling 优先、pypdf 回退）；
切块 `chunk_document`。

**新增 API（旧稿 F1 设计，仓库尚无此函数，属新增而非复用）**：`parse_file_many(path) -> list[ParsedDocument]`
最窄开口，`parse_file` 保留为「返回第一个」保证兼容。

**新增**：

| 模块 | 输入 | 要点 |
| :--- | :--- | :--- |
| `ingest/office.py` | docx/xlsx/pptx | 表格转 pipe table 整块（`is_table`）；Excel 每 sheet 500 行上限，截断写 `extra["truncated"]` 可见；公式取缓存值，绝不猜测；加密文件按失败（原因 `encrypted`），不做口令尝试 |
| `ingest/email_parser.py` | .eml/.mbox | 标准库零新依赖；一封一文档，成员键按 C-1；日期头喂 C-11 |
| `ingest/ocr.py` | 图片/扫描 PDF | `OcrEngine` 协议（`text_from_image -> (text, confidence)`），假引擎可注入测试；扫描版判定：PDF 双路皆低于每页字符阈值；引擎缺失按失败（`ocr_unavailable`），不静默跳过 |
| 代码/脚本 | py/js/shell 等 | 头注释+符号签名 → 精简块；全文走 `search_tsv` |

- `extra` 键（零迁移）：`parser`（值域列全：`text|html|pypdf|docling|docx|xlsx|pptx|eml|mbox|ocr_scan|ocr_image`，
  扫描版 PDF 与图片可分辨）、`source_member`、`truncated`、`ocr`、`formulas_unevaluated`。
  写入通路：解析器只写 `metadata`，`ingester` 全量透传（评审 P2 指出旧稿只搬 `parser` 一个键）。
- **占位文件（OneDrive/按需文件）唯一 owner = 解析层**（评审 P1-38 收口）：Windows 属性位检测，
  统一失败原因枚举（`placeholder_skipped` / `not_synced`），增量层只透传原因 + `doctor` 单列计数。
  reconcile 分类表加第 10 项 `placeholder_skipped`，`STATUSES`、行色表、计数测试三处同步（评审 P1-39）。
- 依赖：`office`/`ocr`/`ocr-tesseract` 三组 optional-dependencies，重依赖一律可选。
- 隐私（评审 P1-44）：邮件与 Office 正文默认 `license_class='unknown'`（fail-closed），
  是否送外部 LLM 抽取必须显式声明；`doctor` 汇报「N 篇文档的正文会送外部模型」。
- 失败统计持久化（评审 P1-23）：`ingest` 结束打印 `parser=x ok=n failed=m` 汇总表，
  `m>0` 时退出码 1；A1-5 判据绑定该表与退出码（解析失败不落库，不能靠 doctor 报数）。
- 白名单扩容的下游审计（评审 P1-36）：`draft/sampling.py`、`draft/manifest.py` 消费后缀
  白名单，限定为原六种（`DRAFT_SUFFIXES`）或把解析失败从抛错改为「记跳过并继续」，
  避免语料里一张截图使 `sci-rag draft manifest` 整体失败。

### 4.2 抽取面（F2，`graph/`）

**复用**：LLM 分批抽取 + 本体约束 + 非法输出丢弃（`graph/extractor.py:79` `parse_extraction`
[代码实证] 校验未知类型）；增量抽取（`Chunk.graph_extracted_at`，`db/models.py:121` [代码实证]）；
实体消解 + 审计（`EntityResolutionAudit`）；社区摘要；本体外置 `domain/domain.yaml`
（`extractor.py:89` 读 `domain.entity_type_names` [代码实证]）。

**本体**（个人文件空间域，12 实体 / 11 关系，沿用 F2）：
实体 `Person、Organization、Project、Document、Event、Topic、Artifact、Technology、Place、TimePeriod、Metric、Decision`；
关系 `AUTHORED_BY、MENTIONS、PART_OF、PRODUCES、USES、PRECEDES、SUPERSEDES、RELATES_TO、LOCATED_IN、HAS_METRIC、DECIDED_IN`。
三层消歧写死：`PART_OF` 是实体级归属（文档级项目归属走列不走图）；`SUPERSEDES` 是内容级取代
（可跨文件），C-4 版本链是同源修订序列（必同源），**不得互相推导**；`Document` 实体类型指
正文提到的他人文档，与 C-1 文档身份同名异物，行文以「文档实体/文档行」区分。

**同名实体（评审 R-6 收口）**：采用「同名必须合并 + 每次合并留审计收据」方案：
抽取期 exact-name 命中即写 `EntityResolutionAudit(method='exact', confidence=1.0)`；
判据 A2-8 相应改写为「同名实体合并且审计表有收据」；非目标写明「本阶段不区分同名人物」。
触发升级条件：若实测通讯录/邮件场景同名误并造成可见损失，再引入 `disambiguator` 列 +
三元唯一约束（属 DS-5 迁移，单独 ADR）。

**Person 两层次**：文档参与者（`documents.authors`：邮件头/文档属性/清单声明）与文中人物
（`KgEntity Person`：chunk 级抽取）分开存、互不覆盖。

**项目归属**：三来源（manual>rule>inferred）。目录规则给可实现定义（评审 P1-49）：
`domain/project_rules.yaml` 有序列表、先匹配先赢、字段 `project/include/exclude/priority`、
只做 glob 不支持正则、匹配对象为 C-1 身份路径、`rules check` 把「同一路径命中多个不同
project」报为冲突。推断用 `project_inference.md` 提示词（文档头部）；失败不写不改（P1-48 修正）；
推断产出库里不存在的项目时**不自动创建项目**（§9），只在报告计一次失败并建议人工建项。
配套（评审 P1-25/P1-40）：`ExtractionStats` 增丢弃计数字段（A2-7 断言绑定）；`doctor` 逐条
打印 `entity_type` 名称（A2-1 断言绑定）；`project` 命令组（`assign`/`list`/`rules check`）
归 `Build your knowledge base` 面板并各给一行现在时 help。

**license 与项目的分歧**（保留 F2 论证，防后人误改）：`license_class` 绝不推断（法律判断，
猜错有法律后果且用户看不出）；项目可推断但三重可见（`project_source` + `extra["project_confidence"]`
+ manual 永久锁定）。判据是后果可逆性。

**本体换代重建路径**（评审 P1-31/32/33）：换本体 = 对 DS-5 三表清空重建，命令序列写死
`graph gc --apply → graph extract --all（必须，extractor 只处理未盖章 chunk）→ graph resolve-entities --apply
→ graph communities`；抽取统计打印 `domain_digest`；graph-replay 重录 + Makefile 哈希文件名更新 +
写死旧本体的测试夹具更新列为可勾选清单；长期可加 `kg_meta(domain_digest, ontology_version, applied_at)`。

**隐私**：人名/机构/项目/地点全部适用「只落库、不进轨迹、不进日志」；导出受 scope（§6）。

### 4.3 关系面（F3，`relate/` 新包）

**四类关系各用最适落点，不建通用边表**（沿用 F3 三条论证：代价不同、基数不同、已有实现；
触发条件：出现第五类关系或需跨类统一「相关条目」查询时，加物化视图，不加新表）：

| 关系 | 落点 | 写入时机 | 参与检索 |
| :--- | :--- | :--- | :--- |
| 相似（C-8） | `document_embeddings`，查询期现算 | 摄取完成时；重嵌入按 `embedding_version` 同列陈旧条件（P1-03） | 否 |
| 引用（C-9） | `document_citations` 扩列 | 离线批处理，默认 dry-run | 否；开启需消融证据 |
| 版本（C-4/C-5） | `documents` 三列 | reconcile 决定、ingester 执行（§C-4） | 是（历史版本默认排除） |
| 项目（C-6） | `documents.project_id` | 摄取/规则/推断/人工 | 是（过滤维度） |

**版本链维护语义**（评审 P1-01/02/07/09 修正）：
1. 删中间节点 → 后继重连到前驱（报告显式声明；允许 `version_seq` 空洞）；
2. 批量删除 → 先删集合内节点，再取 `max(chain − deleting, key=version_seq)` 提升，链空则不置；
3. `delete_documents(..., reason="user" | "source_removed")` 两语义分开：`source_removed` 删整链、
   只对链头出一行报告；`user` 才做重连与提升。禁止共用「提升前驱」（否则用户删掉的文件被
   上一版复活，与 reconcile 来回震荡）；
4. doctor 不变量：每个身份 `count(is_current)=1` 且不存在 `is_current=false` 却无后继的行；
5. 派生数据处置（评审 P1-04）：新版本行摄取完成后重算居中向量；引用边与图证据在下次
   `graph citations` 与抽取时对当前版本重建；相似查询默认过滤 `is_current`；
6. `metadata_only` 不产生新版本节点、不推进 `version_seq`（与 `failed` 同类，评审 P1-05 配测试）；
7. 版本链与图层失效对接：历史版本 chunks 保留但被基线谓词排除；`graph_evidence_changed`
   触发图按新语义改写并显式声明降级是否触发 gc。

**读取面**（`relate similar|versions|citations|projects` + MCP `get_related_documents`、
`get_document_versions`）：**所有入口接受 `RetrievalScope`，边两端文档与证据 chunk 都必须过
`scope_conditions()`**（评审 P1-13）；对抗测试「以 `source=A` 为 scope 调各读取入口，A 外文档的
标题/id/数量均不出现」。REST 与 MCP 走同一 `RagService` 方法。

### 4.4 检索问答面（F4）

**复用**：五路检索（vector/keyword/graph/community/hyde）+ 融合 + 路由 + 带编号引用答案
（`AnswerEngine`，`answer/generator.py:75` [代码实证]）+ 可见降级 trace
（`retrieve/types.py:123` [代码实证]）+ 压缩（模型输出只作优化提示，绝不作新证据）+ HyDE
只作检索探针永不作证据。

**中文检索 spike 预注册**（评审 R-5 收口，阻塞项）：
- 样本：24 条中文查询随 `data/demo-personal/` 提交（专有名词 8、编号标识符 8、长句 8）。
- 指标：keyword 层 `hit@20`（标识符类）与 `p95` 延迟。
- 通过判据：标识符类 `hit@20 ≥ 0.75` 且 `p95 ≤ 300ms` 且不劣于同语料 `vector_only`。
- 决策规则：候选顺序 B（`pg_trgm` 三元组 GIN）→ D（Python 侧 jieba 预分词列）→ E（声明降级，
  中文走向量+图两层）；首选不过测则测备选；全不过选 E 并把 A4-2 标「已声明降级」。
- 产物：`docs/spikes/zh-keyword-spike.md` 含原始命中矩阵，作为 A4-2 判定证据。
- 改造面三处一并列管（评审 R-5 第 2 点）：`keyword.py` 查询侧 `websearch_to_tsquery` 语言配置、
  `router.py` 英文正则、`domain.py` `[a-z0-9]+` 切词。
- 诚实声明：spike 完成前 A4-2 标「未验证」，不得以「检索整体可用」代替。

**中文提示词**（评审 P1-47）：路线是新建中文 `domain/` 目录（中文 `domain.yaml` + 手写中文提示词，
`SCI_RAG_DOMAIN_DIR` 切换），不走 `draft prompts`（`prompt_localization.md` 是领域用词改写而非
语言本地化；`snippet_compression` 在 `REFUSED_PROMPTS` 中）。压缩提示词中文化后必须重跑成对闸门。

**判据修正**（评审 P1-28）：A4-1 改为 `trace.status == "success" ∧ candidate_count > 0`，
或 status ∈ {timeout, error, disabled, skipped} 且显式声明降级；**`empty` 一律判失败**。

**能力边界**（沿用 F4）：单轮管线（一条检索管线 + 一次答案生成），多跳推理不在能力内；
补偿 = 图层多跳用足 + 浏览层人工沿关系跳转 + GenericAgent 在其上做追问循环（记忆面职责，
不改本管线）。unanswerable 探针必须保留，无答案报告缺口不用模型先验填空。

### 4.5 浏览面（F5）

**复用**（含三处刻意不对称）：单机单用户三条硬边界（不做多租户/项目只是过滤维度非权限边界/
数据全本地）；一个聚合端点 `/v1/corpus/facets` 支撑所有界面；空值桶（未归类项目/无日期/无标签
显式可见，「把它们藏起来会让用户以为文件丢了」）；复合排序键 `doc_date desc nulls last,
ingested_at desc, id` 分页确定性；主题簇不过滤；解析器维度只展示不提升列；不引入缓存层
（慢则物化视图 + 写入路径失效）。

**评审修正**：
- 分面硬约束（P1-10）：`facet_counts()`/`browse_documents()`/`topic_overview()` 每条聚合 SQL 以
  `where(*scope_conditions(scope))` 起头，共用 `types.py:83` [代码实证] 单一收口，禁止在分面模块
  另写 where；对抗测试「受限 scope 下 facet 计数 == 逐文档同 scope 查询行数」。
- 浏览默认 `is_current`（P1-11）：直方图判据写死为「桶之和 + 空日期桶 == 当前版本且 in-scope 的文档数」。
- `entity_names` 过滤（P1-12）：写死 EXISTS 条件形态
  (`kg_entities → unnest(chunk_ids) → chunks → documents`)，同样由 `scope_conditions()` 产出。
- 维度注册表（P1-52）：分面维度由声明式清单驱动，新增维度 = 清单加一行（无索引补同级迁移）。
- MCP 签名落定（P1-37）：`browse_corpus(dimension, by=None, filters=None) -> dict`、
  `list_projects() -> dict`、`topic_overview()` 由 `GET /v1/corpus/topics` 承载；REST 与 MCP 同源。
- 排序变更是行为变更（P1-53）：`docs/api.md` 记明 + 契约测试钉住 `doc_date desc nulls last`。

### 4.6 增量面（F6，`reconcile.py`）

**复用**：两阶段分类（added/unchanged/verify/removed/out_of_scope/no_path_recorded +
metadata_only/updated/failed）；指纹跳过（unchanged 零解析）；中断自愈；fail-closed 删除范围。

**评审修正**：
- **写入通道**（R-2）：`Plan.pending: list[PendingIngest(entry, predecessor_id, version_seq, is_current)]`
  包装交接（不污染用户手写 JSONL 模型 `CorpusEntry`）；`cli/main.py` 的 `ingest_entries` 改收该类型；
  「reconcile 决定、ingester 执行」。`updated` 分支删除「删旧插新」，改为 C-4 版本链写入；
  `_newest_first` 排序键改 `(is_current, ingested_at)` 降序；stale-duplicate 循环加
  `if not other.is_current: continue`（前驱保留，只删真重复行）；加载**全部行**不在加载处过滤
  （否则源文件删除留孤儿链）；删除报告整链只对链头出一行。
- **判据改写**（P1-27）：A6-2 改为「`is_current=true` 行数不变、`documents` 总行数 +1、
  `version_seq` 严格递增、`version_of` 指同身份上一版、恰一个 `is_current`」；A6-6 拆源侧/库侧两条。
- **触发方式（本稿修订 W3）**：三通道并行：
  1. **Agent scheduler 定时**（GenericAgent `reflect/scheduler.py` / `--reflect` 模式，`agentmain.py:280-324`
     [代码实证]）驱动增量 reconcile，失败通知进 Agent 记忆/`ask_user`，不只写日志；
  2. **hooks 事件触发**（`plugins/hooks.py` `tool_after` file_write/file_patch，`hooks.py:17` [代码实证]）：
     Agent 经手的文件即时增量；
  3. **OS 轮询兜底**（cron/schtasks 低频）：覆盖 OneDrive 同步、手动改动等 Agent 看不到的变更。
  三通道共用 `pg_advisory_lock` 单实例（随连接释放、崩溃稳健；测试断言第二实例启动即退出且
  不修改数据库）。不做常驻监听进程；推翻条件：实测轮询延迟不可接受或网络目录成本失控时
  再引入监听，届时新 ADR 并解决「监听崩溃后补齐遗漏变更」。
  「轮询边际成本 = 一次目录遍历 + 每文件一次 stat」须在真实语料实测后回填数字（旧稿
  「一万个文件亚秒级」为未实测断言，本稿标 `[待实测]`）。
- 失败可见性三件套：日志追加、失败退出码被调度方记录、可分辨失败原因 + doctor 分类计数。

### 4.7 记忆面（F7，GenericAgent 侧，本稿新增）

**原则**：不改 GenericAgent 种子代码（`agent_loop.py`/`ga.py`/`agentmain.py`/`llmcore.py`）；
集成走两条既有通道：`code_run` 调 `sci-rag` CLI（零新增工具），与 `plugins/hooks.py` 插件。

1. **知识库访问 SOP（L3）**：新增 `memory/pcmem_sop.md`：何时查知识库、用哪个命令
   （`sci-rag retrieve/answer/browse/relate`）、典型坑（中文 spike 未过时 keyword 层降级、
   无日期文档在时间过滤下的 NULL 语义、历史版本不可见）。按 GA 记忆纪律：极简「关键前置+典型坑」，
   只 patch 不 overwrite。
2. **记忆调用路由（R6，A7-3）**：插件 `plugins/pcmem_router.py`，注册 hooks 事件：

| 触发 | 调用什么 | 走什么 |
| :--- | :--- | :--- |
| 任务开始（`agent_before`） | 项目上下文（`project_mode.py:79` 同构对接 project_id）+ 该项目主题簇概览 | `browse_corpus`/`list_projects` |
| 检索型提问 | 全库混合检索 + 带引用回答 | `answer_question`/`search_corpus` |
| 写文件（`tool_after` file_write/file_patch） | 该文件版本组与归属；触发增量 | `relate versions` + 增量通道 2 |
| 长任务收尾（`start_long_term_update`，`ga.py:527`） | 提纯用户偏好/项目事实 → L2，指针化到 project_id | GA 记忆提纯流程 |
| 定时（scheduler） | 增量 reconcile、社区重建、stale 标记、热度汇总 | 增量通道 1 |

   路由表本身是可进化的（GA SOP 自进化：把「什么任务用什么查询」固化为 L3）。
3. **遗忘与新鲜度（R4/R5，A7-1/A7-2）**：热/温/冷三层：热层 = L1 索引（≤30 行）随访问热度
   （C-13）重排；温层 = 知识库全量；冷层 = stale 版本与旧项目（`is_current=false` + 长期无访问）。
   **不物理删除**；过期事实带 `valid_from/valid_to`（第 3 档 JSONB），问答优先给现行事实、
   历史事实标注「已过期，可能仍反映历史工作」。
4. **工作历史理解（R8，研究项）**：`browse timeline`（C-11 直方图）+ 主题簇 + L4 会话归档 +
   项目归档 → 时序叙事生成（「我去年都在忙什么」）。P3 研究项，人工评分验收。
5. **Agent 工具面契约**：既有 MCP 8 工具（`mcp_server.py:51-336` [代码实证]）+ 新增
   `browse_corpus`、`list_projects`、`get_related_documents`、`get_document_versions`。
   GenericAgent 经 MCP client 或 CLI 调用；REST/MCP 同源（`RagService`）。

---

## 5. scope 与隐私（安全契约）

### 5.1 基线谓词（评审 R-1 修正版，最高优先级不变式）

- **`is_current` 是所有检索/读取/导出/分面阶段无条件施加的基线谓词**，不是 scope 的一个维度。
  `include_superseded: bool = False` 只是显式豁免开关。
- 实现要点：`_WALK_SQL` 的 `:unrestricted OR ...` 再与 `(:include_superseded OR ranked_document.is_current)`
  相与；`graph.py`/`community.py` 的 `is_unrestricted()`（消费点：`retriever.py:200`、`community.py:29`、
  `graph.py:202` [评审实读]）不得再被用作「可跳过文档过滤」的依据；社区摘要只由
  `is_current=true` 的文档构建（二选一里取此方案）；导出（`export.py:148` [评审实读]）默认同样排除。
- **非 walk 路径落点写死（评审 P1-6 收口）**：facet/browse/list/关系读取面的基线谓词统一由
  `scope_conditions()` 产出并强制注入每条聚合/查询 SQL（与 §4.5 分面硬约束同一收口），
  不在各模块另写 where。
- 既有测试处置：`tests/unit/test_retrieval_scope.py:40-53` 的 `scope_conditions(...) == []` 与
  `== 1` 两条断言改写为「`include_superseded=True` 时条件为空/无副作用」与「该维度条件存在」；
  `RESTRICTIONS` 手工枚举不可持续：加遍历 `dataclasses.fields(RetrievalScope)` 的元测试兜底。

### 5.2 scope 字段总表（评审 P1-16，单一登记处）

| 字段 | 语义族 | SQL 形态 |
| :--- | :--- | :--- |
| `include_superseded` | 基线豁免 | `Document.is_current` |
| `date_min`/`date_max` | 元数据 | `or_(doc_date IS NULL, doc_date >=/<= ...)` |
| `projects` | 元数据 | `Document.project_id = ANY(...)` |
| `tags`/`auto_tags` | 元数据 | `Document.tags && ...` |
| `entity_names` | 元数据 | EXISTS（kg_entities→chunk_ids→chunks→documents） |
| 既有 license/source/exclude 等 | 权利 | 不变 |

规则：任何功能只引用本表；`is_unrestricted()` 与测试一次性登记全部字段；
权利族与元数据族语义相反（`None`=不限制 vs 空元组=无要求/全拒），将来多用户把项目迁到权利族时
必须重写语义（触发条件记录在案，评审 P1 收口）。

### 5.3 隐私条款

- 个人文件默认 `license_class='unknown'` → fail-closed：出站（外部 LLM 提示词、导出、外部 MCP
  调用）默认全拒；显式声明可出境的目录才进白名单语义（`EXTERNAL_SAFE_CLASSES`，`licensing.py:46`
  [代码实证] 同机制）。
- 人名/机构/项目/地点：只落库、不进轨迹、不进日志；trace 只含阶段名/状态/耗时/计数。
- `doctor` 汇报「N 篇文档的正文会送外部模型」。
- 导出即再分发：实体仅当来源文档全部 in-scope 才导出；社区/主题簇不导出。

---

## 6. 阶段划分与依赖

| 阶段 | 内容 | 依赖 |
| :--- | :--- | :--- |
| P0 清障 | 合并 `feature/incremental-reconcile`；ADR 0012→0013 重编号；`AGENTS.md` 冲突先提交重写再合并 | 无 |
| P1 底座 | M-0008-R 迁移（含全部评审修正）；C-1 复合身份贯通 reconcile/指纹/版本链；scope 字段总表 + 基线谓词 + 对抗性测试先行 | P0 |
| P2 写方并行 | 解析面（Office/邮件/OCR + 占位文件 owner）∥ 抽取面（本体换代 + 项目/标签） | P1 |
| P3 关系面 | relate/ 四类关系 + 读取面 scope | P2 |
| P4 检索浏览 | 中文 spike（可提前）+ 浏览面 + MCP 扩展 | P1（spike）/P3（浏览） |
| P5 记忆面 | GenericAgent SOP + 路由插件 + 遗忘/热度 + scheduler 接线（`--reflect` 启动形态写入部署文档） | P4 |
| P6 研究 | R8 工作历史叙事、多模态增强、消融研究 | P5 |

**并行机会**：Office/邮件解析器实现、中文 spike、本体提示词起草不依赖 P1 的落库部分。

---

## 7. 测试计划与验收

**分层**：单元=纯逻辑（身份/指纹/版本链状态机/规则匹配/分面聚合）；集成=DB 语义
（迁移双向、版本链不变式、幂等、中断自愈）；server=REST/MCP 契约与 parity；docs=呈现。

**预注册对抗性测试（放行门槛，先补测试再改实现）**：
1. 历史版本经任何一层（vector/keyword/graph/community/HyDE/引用边/分面/导出/读取面）不进候选或答案；
   有界候选池下不挤占当前版本；
2. scope 排除文档不因提及边、社区摘要、分面计数间接泄漏；
3. revert（A→B→A）产生新当前版本（`test_revert_creates_a_new_current_version`：行数 3、恰一个 current）；
   同内容不同路径的两份文件各自成文且第二份不重复解析（A6-1 关联用例，评审 P1-4）；
4. 崩溃注入（降级与插入之间中断）后每身份恰一个 `is_current`；
5. 同名实体合并留审计收据；
6. 同一 citing 文档 3 条 mention 边两轮重建收敛 0/0 且仍 3 行；
7. 受限 scope 下 facet 计数 == 逐文档同 scope 行数；
8. 中文 keyword 层按 spike 判据，`empty` 状态判失败；
9. 多成员文件：只改 mbox 第三封邮件，宿主被判 `UPDATED` 且只该成员推进版本链
   （`test_member_change_detected`，评审 P1-5）。

**验收命令（只引用本阶段可跑目标，评审 P1-29 教训）**：每阶段附 `uv run pytest <精确目标> -q`
与 `make check` 等价裸命令（本机无 make，见 skill `sci-rag-kit-windows-host`）；本机既有 14 个
环境失败按「不新增失败」口径；迁移验收含一次性库上 `alembic upgrade head` / `downgrade -1` 双向断言。

**必须声明的跳过**：Windows 占位文件属性位 CI 不可验（仅本地验证，不构成通过证据）；
中文 spike 未完成前 A4-2 标未验证；OCR 未装 extra 时 A1-3b 未验证；无生成凭据时图路径整体降级须声明。

**研究豁免条款（评审 P2-5）**：P6 研究项（R8 工作历史叙事等）的验收为人工评分报告，
不适用「机械断言」通则，但必须给出评分协议（评分维度、样本量 ≥ 20 问、评分人），
且不得用研究项的主观评分充当功能验收证据。

---

## 8. 风险登记与撤销条件

| 编号 | 风险 | 处置 |
| :--- | :--- | :--- |
| R-1 | 基线谓词漏改一处（graph/community/export/读取面/分面） | 对抗测试为放行门槛 + fields 元测试 |
| R-2 | 版本链与 reconcile 删除逻辑互斥残留 | P1 通道重写 + 崩溃注入 + doctor 不变量 |
| R-3 | content_hash 唯一性残留全局约束 | 部分唯一索引 + revert 用例 |
| R-4 | 复合身份在某处被当单路径 | 分桶键/探针/版本不变式三处一致性测试 |
| R-5 | 中文检索凭印象选型 | spike 预注册判据，未过即声明降级 |
| R-6 | 本体换代后旧行吞新抽取 | 清空重建路径 + domain_digest 打印 |
| R-7 | 隐私面（邮件/Office/人名出境） | fail-closed + doctor 汇报 + 轨迹无内容测试 |
| R-8 | 向量三表维度漂移 | 维度脚本表清单 + 一致性断言 |
| R-9 | 三触发通道并发冲突 | pg_advisory_lock + 第二实例测试 |
| R-10 | 记忆层自我污染（推测写成事实） | GA L0 公理 + 只 patch + 指针化 |

**撤销条件**（回本稿修改而不是继续实现）：
1. M-0008-R 回滚在一次性库上不可逆 → 重新拆迁移；
2. 对抗性测试证明基线谓词不足以隔离历史版本 → 改为每 stage 显式过滤；
3. 项目推断准确率低到目录规则与人工成为唯一来源 → 推断降级为可选（须给可判定阈值：
   人工抽样 100 篇、推断准确率 < 60% 即触发）；
4. 中文 spike 三个候选全不过 → 按保底方案 E 落地并重写 A4-2 期望。

---

## 9. 明确不做的事

- 不建通用边表；不做 git 式 diff/三方合并；不自动合并文档内容；不做图中心性分析。
- 不区分同名人物（同名视为同一实体，合并留审计收据；同名消歧升级另立 DS-5 迁移 + ADR）。
- 不做多租户/用户隔离/权限边界（项目只是过滤维度）。
- 不做常驻文件监听进程（触发条件见 §4.6）；不做 chunk 级复用；不做跨机器语料同步。
- 不做人脸识别/图片人物识别；不维护全局人物词典；不做 claim 级事实抽取。
- 不自动创建项目（manual/rule/inferred 三选一）；不合并 `source` 与 `project`。
- 不打开 `include_citations` 与重排器默认值（开启需消融证据）；不把 HyDE 做成证据源。
- 不做 Web UI、文件预览、收藏置顶等工作台功能；不引入缓存层、任务队列、图 sidecar。
- 不解析旧二进制 `.doc/.xls/.ppt`（先转存新格式）；不做音视频转写（P3 研究项另立）。
- 不把 `SUPERSEDES` 与版本链互相推导；不把主题簇当过滤维度。
- GenericAgent 种子代码不改；记忆文件不 overwrite。

---

## 10. 证据边界（审计声明）

**本轮已实读**（`[代码实证]`）：`ingest/parsers.py:37,44,54,63`、`ingest/manifest.py:33,74,117`、
`ingest/ingester.py:55`、`db/models.py:47-154`（Document/Chunk/DocumentCitation 部分）、
`retrieve/types.py:28,123`、`retrieve/retriever.py:85,120`、`retrieve/rerank.py:67,95,143`、
`graph/extractor.py:79,89,176,342`、`server/mcp_server.py:51-336`、`server/service.py:32`、
`answer/generator.py:75`、`licensing.py:46`，以及 GenericAgent 侧 `agent_loop.py`、`agentmain.py`、
`ga.py`、`memory/memory_management_sop.md`、`plugins/hooks.py`、`plugins/project_mode.py` 全文。

**引自旧评审报告主审实读**（`[评审实读]`，本轮未重复核验）：`models.py:92,207`、
`types.py:83-107`、`graph.py:202-211`、`community.py:29`、`reconcile.py:228-248,316`（worktree 分支）、
`export.py:148`、`test_retrieval_scope.py:40-53`、`keyword.py:24`、`draft/prompts.py` 等。

**未核验**：`snapshot.py` 摘要算法、`resolve.py` 合并算法细节、`planner.py` 失效判据、
`feature/incremental-reconcile` 分支文件（仅评审报告口径）、GenericAgent `conductor.py`/`subagent.md`
内容。轮询成本数字 `[待实测]`；OCR 引擎选型 `[待 spike]`；中文检索判据 `[待 spike]`。

**跨稿引用闭合**：本稿概念 C-1..C-13、功能 §4.1-§4.7、验收 A1-A7 均在本稿内定义（判据断言
全文见附录 A），无悬空指针；旧稿编号仅作出处标注，不作为定义依赖。审查发现的
章节号错位与「58 条 P1」过满声明已在 v1.1 修正，修订记录见审查报告。

---

## 附录 A：验收判据表（机械断言全文）

> 每条 = 判据 + 可机械判定方式。旧稿已有的判据按评审修正版收录（A2-8、A3-2、A3-9、
> A4-1、A6-2、A6-6 为修正版），A7 为本稿新增。

### A1 多格式解析（§4.1）

| 编号 | 机械断言 |
| :--- | :--- |
| A1-1 | 七类样本（PDF/MD/TXT/HTML/Office 三件套/图片或扫描件/邮件）各一，`build` 后 `documents` 行数 == 样本数 |
| A1-2 | 每个含表格样本存在 `is_table=true` 的 chunk 且内容含表头字段 |
| A1-3a | 机制项：注入假 OCR 引擎，断言 `extra["ocr"].engine=="fake"`、`pages==1`、该文档 chunks 行数 > 0 |
| A1-3b | 效果项（spike 回填）：产出字符数 ≥ ⌈p·N⌉ 且单页耗时 ≤ t·2（p、t 由引擎 spike 给出） |
| A1-4 | 含 3 封邮件的 mbox 产出 3 行 `documents`，`extra["source_member"]` 各不相同 |
| A1-5 | `ingest` stdout 打印 `parser=x ok=n failed=m` 汇总表；`m>0` 时退出码 == 1 |
| A1-6 | 超行数上限的 sheet：`extra["truncated"].rows` == 实际丢弃行数 |
| A1-7 | `make check` 等价裸命令通过，且 `git status` 无新增二进制样本 |

### A2 元数据抽取（§4.2）

| 编号 | 机械断言 |
| :--- | :--- |
| A2-1 | `doctor` 逐条打印 `entity_type` 名称，清单包含 `Person` 与 `Project` |
| A2-2 | 存在 `entity_type='Person'` 行且其 `chunk_ids` 非空 |
| A2-3 | `documents.authors` 与 `kg_entities` 中 Person 是两组记录，`extra` 含来源键 |
| A2-4 | manual/rule/inferred 三来源各一用例，合成结果与 `project_source` 断言为 manual>rule>inferred |
| A2-5 | 人工指派后跑规则 + 推断，`project_id` 与 `project_source` 不变 |
| A2-6 | 自动通路只写 `auto_tags`、人工通路只写 `tags`，互不污染 |
| A2-7 | 注入未知 `entity_type`：该条被丢且 `ExtractionStats` 丢弃计数 +1 |
| A2-8 | 同名实体：`kg_entities` 恰一行且 `entity_resolution_audit` 存在 `method='exact'` 收据 |

### A3 文档关系（§4.3）

| 编号 | 机械断言 |
| :--- | :--- |
| A3-1 | 合成语料（两近一远）：`relate similar` 近邻排序中相近对排在不相关对之前 |
| A3-2 | 摄取新文档后 `relate similar` 返回集合含该文档，且调用记录中无 `embed reindex` |
| A3-3 | 断言存在 `source='crossref'` 与 `source='mention'` 两类行 |
| A3-4 | 每条 mention 边 `evidence_chunk_id` 非空且该 chunk 文本含被引文档的键 |
| A3-5 | 先建边得未解析行 → 摄取目标 → 重跑后该行变为已解析 |
| A3-6 | 版本链：`is_current=true` 行数 == 1、`version_seq` 严格递增、`version_of` 指同身份上一版 |
| A3-7 | 历史版本经 vector/keyword/graph/community/HyDE/引用边/分面/导出/读取面均不进候选或答案 |
| A3-8 | 删中间节点重连且报告声明；批量删取 `max(chain−deleting)` 提升；`source_removed` 整链删、链头一行报告 |
| A3-9 | 拆四条：crossref/mention 边可答「谁建的+证据」；版本链 doctor 不变量成立；项目有 `project_source`；相似为查询期现算（无持久边，可答「由哪次查询产生」） |

### A4 检索问答（§4.4）

| 编号 | 机械断言 |
| :--- | :--- |
| A4-1 | 每路 `trace.status=="success" ∧ candidate_count>0`，或 status∈{timeout,error,disabled,skipped} 且文档显式声明；`empty` 一律判失败 |
| A4-2 | spike 判据：标识符类 `hit@20≥0.75 ∧ p95≤300ms ∧ 不劣于 vector_only`；spike 未完成标「未验证」 |
| A4-3 | 跨文件问题的答案引用文档数 ≥ 2 |
| A4-4 | unanswerable 探针：报告缺口，无模型先验填空 |
| A4-5 | 答案每条引用编号可映射回检索结果的 chunk |
| A4-6 | 历史版本与 scope 排除文档不出现在候选或答案（同 A3-7） |
| A4-7 | SSE 与非流式聚合同一 typed 事件序列 |
| A4-8 | 空补全按失败处理（非零成本兼容） |
| A4-9 | `date_min`/`date_max` 筛出预期文档数；`doc_date IS NULL` 文档按保留语义不被排除 |

### A5 空间浏览（§4.5）

| 编号 | 机械断言 |
| :--- | :--- |
| A5-1 | 项目分面计数 == 逐项目查询行数之和 |
| A5-2 | 时间直方图桶和 + 空日期桶 == 当前版本且 in-scope 的文档数 |
| A5-3 | 命名主题分面读 `kg_entities`、主题簇概览读 `kg_communities`，两条查询不混用 |
| A5-4 | 遍历全部分页收集的 id 集合 == 一次性查询 id 集合 |
| A5-5 | 未归类项目/无日期/无标签文档进入显式空值桶，计数 > 0 时可见 |
| A5-6 | `tags` 与 `auto_tags` 过滤各一组用例，互不串 |
| A5-7 | 从任一文档出发四类关系入口均可用且带 scope |
| A5-8 | 同一过滤条件下 REST 与 MCP 返回同一结果集 |
| A5-9 | 空库上调用分面端点返回各维度空列表，退出码 0 |

### A6 增量更新（§4.6）

| 编号 | 机械断言 |
| :--- | :--- |
| A6-1 | 第二轮运行解析调用次数 == 0；同内容不同路径两文件各自成文且均只解析一次 |
| A6-2 | 修改文件：`is_current=true` 行数不变、`documents` 总行数 +1、`version_seq` 严格递增、`version_of` 指同身份上一版、恰一个 `is_current` |
| A6-3 | 源文件删除：整链与图证据清理，构建根外文档不受影响（fail-closed 范围测试） |
| A6-4 | 解析失败：旧文档保留、版本号不变、`failed` 计数 +1 |
| A6-5 | 崩溃注入后重跑终态 == 一次性运行终态；每身份恰一个 `is_current` |
| A6-6 | 源侧计数（added+unchanged+verify+placeholder_skipped+...）== 扫描文件数；库侧计数独立断言 |
| A6-7 | 不可追踪文档进 `no_path_recorded` 计数并被 `doctor` 报告，无猜测归类 |
| A6-8 | scheduler/hooks/轮询三通道各跑通一轮且结果一致；第二实例启动即退出且不修改数据库 |
| A6-9 | 历史版本隔离（同 A3-7）；写入方只对 `is_current` 写入正确性负责 |

### A7 记忆面（§4.7）

| 编号 | 机械断言 |
| :--- | :--- |
| A7-1 | stale/冷迁移后 `documents` 行数不减（只标记/降冷）；`global_mem_insight.txt` 行数 ≤ 30 |
| A7-2 | 时点查询优先返回现行事实；历史事实响应中带「已过期」标注 |
| A7-3 | 触发表五场景（任务开始/检索型/写文件/收尾/定时）各实测一次，调用记录断言命中对应接口 |
| A7-4 | memory 文件变更均为 patch（git diff 抽查无整文件 overwrite）；抽查无「推测写成事实」条目 |
| A7-5 | 完成 ≥3 个同类任务后 L3 出现对应 SOP，且新会话能一句话调用该 SOP 完成同类任务 |
