# F5 实现计划：按项目、时间、主题浏览个人文件空间

- 日期：2026-10-14
- 状态：设计稿初稿，待评审
- 阶段：P4
- 共享契约：见 `2026-10-14-personal-file-space-program-design.md`（下称程序稿）。
- 本稿**不需要回改程序稿**：它消费的概念（`C-6`、`C-7`、`C-10`、`C-11`）与存储（`DS-1`、`DS-2`、`DS-5`）都已在契约中定义，且不新增概念。
- 组件定位：本稿拥有 `CP-4`（浏览面，P4）。上游是 `DS-1`、`DS-2`、`DS-5`，下游是 CLI、REST 与 MCP 三个出口。

## 1. 功能定义与验收标准

**功能**：不依靠提问，直接按维度查看文件空间：有哪些项目、每个项目里有什么、时间上怎么分布、都在讲哪些主题。

| 编号 | 判据 | 判定方式 |
|---|---|---|
| A5-1 | 按项目浏览：可分面列出项目与文档数，可按项目过滤 | 断言分面计数与逐个项目查询的行数一致 |
| A5-2 | 按时间浏览：按 `C-11` 给出年与月的分布，可按范围过滤 | 断言直方图总和等于文档总数 |
| A5-3 | 按主题浏览：命名主题可作分面，主题簇可作概览 | 断言分面读实体表，概览读社区表，两者不混用 |
| A5-4 | 分页确定：同一查询两次翻页不重不漏 | 遍历全部分页，断言收集到的 id 集合等于一次性查询 |
| A5-5 | 未归类与无日期的文档可见 | `project_id` 为空、`doc_date` 为空的文档进入显式桶，不被静默隐藏 |
| A5-6 | 手工标签与自动标签可分别过滤 | 两个过滤条件各一组用例 |
| A5-7 | 从任一文档出发可枚举四类关系 | 复用 F3 的读取面，断言四个入口都可用 |
| A5-8 | REST 与 MCP 返回同一结果集 | 同一过滤条件下比较两个入口的结果 |
| A5-9 | 空态可用：没有任何项目或标签时仍能浏览 | 空库上调用分面端点返回空列表而不是报错 |

## 2. 现状核对

已实现的部分：

- REST 共 7 个端点：`/health`、`/v1/status`、`/v1/corpus-manifest`、`/v1/documents`、`/v1/documents/{id}`、`/v1/query`、`/v1/answer`（`src/sci_rag/server/routers/`）。
- 文档列表支持三个过滤条件与分页：`search`（标题子串）、`source`、`license_class`，按 `ingested_at desc, id` 排序（`src/sci_rag/server/service.py:164-194`）。
- `sci-rag stats` 输出文档、分块、实体、关系、社区计数，外加许可证分布、嵌入版本分布、关系置信带分布。
- MCP 已暴露 8 个工具与 2 个资源，其中 `list_sources` 与 `corpus_stats` 承担了部分概览职责（`src/sci_rag/server/mcp_server.py:322,336`）。
- `sci-rag corpus license-report` 输出许可证维度的报告。

缺失的部分：

- **无项目维度**（`C-6` 由 F2 引入，本稿消费）。
- **无时间过滤**：列表按摄取时间排序，但没有任何按时间过滤或分组的入口；`publication_year` 对个人文件普遍为空，见 F4 §3.3。
- **无主题入口**：命名主题没有任何列表端点，只能通过 MCP 的 `search_entities` 按名字找；主题簇完全没有入口。
- **无标签入口**：`tags` 由 F2 引入，本稿前不存在。
- **无分面聚合**：所有概览都是全库计数，没有「按某维度分组」的能力。
- **无界面**：REST 之外没有任何浏览载体。

## 3. 设计

### 3.1「个人」的含义与边界

本稿说「个人文件空间」，指的是**单机单用户**形态：一个人在自己的机器上索引自己的文件。据此定下三条边界，避免实现阶段自行扩张：

1. **不做多租户**。没有用户表、没有行级隔离、没有共享空间。既有的 API key scope 机制继续存在，但它的维度是许可证与来源，不是用户。
2. **项目是过滤维度，不是权限边界**。`C-6 项目` 只用于分组与过滤，不用于访问控制。
3. **数据全部在本地库**。不上传、不调用外部服务，除非用户显式配置了模型凭据。

**第 2 条有一个必须记录的触发条件**：如果将来要做多用户共享实例，项目就从普通过滤维度变成权限边界，必须从 `RetrievalScope` 的「元数据过滤」一族迁到「权利」一族。这两族的语义在源码里是刻意相反的：权利维度里 `None` 表示不限制、空元组表示全部拒绝；元数据维度里空元组只表示没人提要求（`src/sci_rag/retrieve/types.py:27-59`）。迁移时若照抄元数据语义，会造成「限制到空集却看到全部」的越权。

### 3.2 浏览维度与承载

| 维度 | 概念 | 分面来源 | 过滤字段 |
|---|---|---|---|
| 项目 | `C-6` | `projects` 表与 `documents.project_id` | `projects` |
| 时间 | `C-11` | `documents.doc_date` 的年月直方图 | `date_min`、`date_max` |
| 命名主题 | `C-10` 的第一层 | `kg_entities` 中 `entity_type='Topic'` 的出现计数 | `entity_names` |
| 主题簇 | `C-10` 的第二层 | `kg_communities`，作为概览而非过滤 | 不参与过滤 |
| 标签 | `C-7` | `tags` 与 `auto_tags` 的出现计数 | `tags`、`auto_tags` |
| 来源 | 已有 | `documents.source` | `sources`（已有） |
| 权利 | 已有 | `documents.license_class` | `license_classes`（已有） |
| 解析器 | F1 | `extra["parser"]` | 需提升为列才可索引，本稿不提升，只在分面里给出分布 |
| 关系 | F3 | 相似、引用、版本 | 按文档维度枚举，不做全景分面 |

两处刻意的不对称：主题簇不做过滤，因为它没有逐条证据归属，用它过滤等于用一个模型生成的簇去切分用户可见的集合，而用户无法审计这个切分；解析器分布只做展示不做过滤，因为它是实现细节而不是用户语义，为它建索引不划算。

### 3.3 分面端点：一个端点支撑所有界面

新增 `/v1/corpus/facets`，一次返回全部维度的分布与计数。这是本稿的核心交付物：只要有一个聚合端点，任何界面（CLI 表格、MCP 工具、将来的网页）都能由它拼出来，不必为每种界面各写一套查询。

响应内容：每个维度返回取值与计数，并**显式包含空值桶**（未归类项目的文档数、无日期文档数、无标签文档数）。空值桶是 A5-5 的实现方式：个人文件空间的初期一定有大量未归类文档，把它们藏起来会让用户以为文件丢了。

### 3.4 服务层与两个门面

`RagService` 新增四个方法：`facet_counts()`、`list_projects()`、`browse_documents(filters, page)`、`topic_overview()`。REST 与 MCP 都调用同一组方法，保证 A5-8 成立。这是仓库的既有不变式：REST 与 MCP 必须走同一个服务，否则认证、范围、引用与错误会在两个门面之间漂移。

### 3.5 命令面

新增 `browse` 命令组，全部归 `Ask questions` 面板。

关于面板归属的一个明确决定：`browse`（本稿）与 `relate`（F3 §9 的开放问题）**都不新增面板**。`PANEL_ORDER` 与面板排序逻辑在 `src/sci_rag/cli/main.py:44-50`，新增面板属于对外呈现变更，而「六个面板对应新项目遇到命令的顺序」这个设计意图不需要第七个。浏览与关系读取都是对语料的读取查询，与同面板下的 `retrieve`、`answer`、`stats` 同类。

| 命令 | 用途 |
|---|---|
| `browse projects` | 项目清单与文档数，含未归类桶 |
| `browse timeline --by month\|year` | 按 `C-11` 的时间分布 |
| `browse topics` | 命名主题分面；`--overview` 切换为主题簇概览 |
| `browse tags --auto\|--manual` | 标签分面 |
| `browse documents --project X --since Y --tag Z` | 带过滤的列表，即 REST 列表端点的命令行投影 |

`stats` 保留并增加 `--by project|year|tag|topic|parser`，因为它已有的全库概览职责与分面不同：前者回答「库里有什么」，后者回答「按某维度怎么分布」。

### 3.6 排序与分页

列表排序改为 `doc_date desc nulls last, ingested_at desc, id`。当前是 `ingested_at desc, id`（`service.py:187`），也已经是确定的，但按 `C-11` 排序才符合「按时间浏览」的语义。

分页确定性由复合排序键保证：单独按 `doc_date` 排序时大量文档共享同一日期（同一天导入的整批文件），翻页会重漏。`id` 作最后的唯一 tiebreak，这一点与既有实现的做法一致，继续保留。

### 3.7 错误处理

- 过滤到空集：返回空列表与总数 0，与「条件非法」区分开。非法的项目名返回 404 语义的错误而不是空列表，否则用户分不清是没匹配还是名字打错。
- 分面在空库上返回各维度的空列表，不报错（A5-9）。
- 所有新端点沿用既有错误契约：稳定的错误码与 `application/problem+json`，并保持 `X-Request-ID` 行为。

### 3.8 性能

分面是聚合查询，代价随语料增长。可用手段按优先级：先确认 `project_id`、`tags`、`doc_date` 的索引存在（由 `M-0008` 提供）；再用覆盖率允许的索引扫描；最后才考虑物化视图。

**不引入缓存层**。仓库刻意没有 cache service（`docs/architecture.md` 的「刻意不做的东西」），个人文件空间的语料规模也不值得为它破例。若单次分面查询在目标语料上超过一秒，处理方式是加物化视图并在写入路径失效，而不是加缓存。

## 4. 数据模型与迁移

**本稿不新增表或列**。

检索侧需要新增作用域字段（与 F4 §4.3 共用同一组定义，不重复）：

| 字段 | 含义 |
|---|---|
| `projects` | 项目允许集 |
| `tags` | 手工标签允许集 |
| `auto_tags` | 自动标签允许集 |
| `date_min`、`date_max` | 按 `C-11` 的范围 |
| `entity_names` | 命名主题允许集 |

这五个字段都是元数据过滤一族（空元组表示没人提要求），**不属于权利一族**，理由见 §3.1。它们必须同步登记进 `RetrievalScope.is_unrestricted()`，否则社区层在受限请求下会错误参与。`tests/unit/test_retrieval_scope.py` 逐字段钉住该函数，改字段必须同时改测试。

## 5. 改动文件清单

| 文件 | 改动 |
|---|---|
| `src/sci_rag/browse.py` | 新增，分面聚合与浏览查询 |
| `src/sci_rag/server/service.py` | 新增四个方法，REST 与 MCP 共用 |
| `src/sci_rag/server/routers/documents.py` | `/v1/documents` 增加新过滤参数与排序 |
| `src/sci_rag/server/routers/meta.py` | 新增 `/v1/corpus/facets` |
| `src/sci_rag/server/schemas.py` | 分面响应模型 |
| `src/sci_rag/server/mcp_server.py` | 新增 `browse_corpus`、`list_projects` |
| `src/sci_rag/retrieve/types.py` | 五个新作用域字段；同步 `is_unrestricted()` |
| `src/sci_rag/cli/main.py` | 新增 `browse` 命令组（面板 `Ask questions`）；`stats --by` |
| `docs/` | 新增一页浏览指南；`docs/api.md` 与 `docs/cli.md` 同步（后者由 `make docs-reference` 生成） |

## 6. 测试计划

**单元测试**：

- 分面聚合：计数正确性、空值桶的存在性、空库返回空列表。
- 分页确定性：构造大量共享 `doc_date` 的文档，遍历全部页，断言与一次性查询的 id 集合相等。
- 排序：`doc_date` 为空者排在末尾（`nulls last`），不得排到最前。
- 主题两层不混用：分面读实体表，概览读社区表。

**集成测试**：

- 新过滤参数与既有参数叠加（例如项目加许可证加日期），断言与逐个条件手工求交一致。
- 项目过滤与 `unknown` 权利文档的关系：过滤不应绕过权利作用域。
- 分面计数与逐项查询的行数一致（A5-1）。

**契约测试**（`tests/server/`）：

- REST 与 MCP 在同一过滤条件下返回同一结果集（A5-8）。
- 新端点的错误信封、请求号、认证范围与既有端点一致。
- 非法项目名返回 404 语义，空匹配返回空列表。

**对抗性测试**：

- 受限作用域下不得因为分面聚合而泄漏被排除文档的存在（例如计数里出现被排除文档的数量）。
- 社区层在任一新增过滤字段生效时必须被禁用。

## 7. 验收命令

```bash
make db-up && uv run sci-rag db upgrade
uv run sci-rag browse projects
uv run sci-rag browse timeline --by month
uv run sci-rag browse topics
uv run sci-rag browse documents --project <slug> --since 2026-01-01
uv run sci-rag stats --by project
uv run sci-rag serve          # /docs 里查看 /v1/corpus/facets
uv run pytest tests/unit -q -k "facet or pagination or browse"
uv run pytest tests/server -q -k "documents or facets or parity"
make check
```

## 8. 风险与不做的事

| 编号 | 风险 | 处置 |
|---|---|---|
| R5-1 | 分页重漏 | §3.6 复合排序键，配遍历式测试 |
| R5-2 | 未归类与无日期文档被隐藏，用户以为文件丢了 | 空值桶显式返回（A5-5） |
| R5-3 | 将来做多用户时把项目当权限边界用错语义 | §3.1 记录触发条件与迁移路径 |
| R5-4 | 分面在大语料上变慢 | 先索引、再物化视图；不引入缓存层 |
| R5-5 | 主题簇被拿去当过滤维度 | §3.2 明确它只做概览；分面只读命名主题 |
| R5-6 | 新作用域字段漏改进 `is_unrestricted()` | 测试逐字段钉住，改字段必须改测试 |

**明确不做的事**：

- 不做 Web UI。本阶段以 CLI、REST 与 MCP 为载体，MCP 让本机 agent 直接当浏览界面，零前端成本。网页单列一个后续阶段。
- 不做多租户与用户隔离。
- 不做文件预览（PDF 渲染、缩略图）。
- 不做收藏、置顶、最近打开、标签云动画之类的工作台功能。
- 不做全文高亮与内置编辑器。
- 不把解析器维度提升为可索引的列。
- 不引入缓存层。

## 9. 依赖关系

**前置**：P0 清障；P1 的 `M-0008`；F2 提供 `C-6` 与 `C-7` 的写入方；F4 提供 `C-11` 与作用域字段的既有形态；F3 提供四类关系的读取面（A5-7）。

**后置**：无。本稿是依赖链的末端，功能 6 项在此闭合。

**开放问题**：

1. 分面端点是返回全部维度还是允许按维度挑选。倾向全部返回，个人语料的分面结果很小，一次取回比多次往返简单；若某维度取值数超过阈值再考虑分页。
2. `browse documents` 与既有 `sci-rag stats`、`corpus export` 的边界：三者都能列出文档。倾向 `browse documents` 只做带过滤的列表展示，`export` 保持导出职责，两者共用服务层方法而不共用命令。
3. 主题簇概览是否需要按项目切分。技术上可以，但会与「社区摘要在范围未知前就生成」这一既有约束冲突（社区层在受限请求下被禁用），因此先不做。
