# F2 实现计划：抽取关键实体、主题、项目、人物等信息

- 日期：2026-10-14
- 状态：设计稿初稿，待评审
- 阶段：P2（与 F1 并行）
- 共享契约：概念与存储编号见 `2026-10-14-personal-file-space-program-design.md`（下称程序稿），本稿引用而不重复定义。
- **已登记到程序稿**：本稿需要的 `project_source` 与 `auto_tags` 两列已并入程序稿 §4.2 的 `M-0008` 清单，类型与索引定义以那份为准；本稿只说明为什么需要它们。
- 组件定位：本稿拥有 `CP-2`（抽取面，P2）。上游是 `DS-1` 的分块，下游是 `DS-5` 与 `DS-1` 的 `project_id` / `tags`。

## 1. 功能定义与验收标准

**功能**：从已入库的文档中抽出四类信息：实体、主题、项目、人物。其中项目与人物是个人文件空间区别于科研文献语料的关键。

| 编号 | 判据 | 判定方式 |
|---|---|---|
| A2-1 | 出厂本体改为个人文件空间领域，且含 `Person` 与 `Project` 类型 | `sci-rag doctor` 报出的本体类型清单包含二者 |
| A2-2 | 人物可从正文抽出并带证据 | 断言存在 `entity_type='Person'` 的行，且其 `chunk_ids` 非空 |
| A2-3 | 文档级参与者与文中人物分开存放，不混为一谈 | 断言 `documents.authors` 与 `kg_entities` 里的人物是两组，且各有来源记录 |
| A2-4 | 项目归属可来自三条来源，优先级明确且可覆盖 | 三种来源各一个测试用例，断言优先级为人工 > 目录规则 > 推断 |
| A2-5 | 推断出的项目不会被后续重跑覆盖人工指派 | 先人工指派，再跑一轮推断，断言 `project_id` 与 `project_source` 不变 |
| A2-6 | 手工标签与自动标签分开存储 | 断言 LLM 产出的标签只进自动列，手工标签只进手工列 |
| A2-7 | 非法模型输出被丢弃且可见，不被猜测成有效值 | 注入未知 `entity_type`，断言该条被丢且计入报告 |
| A2-8 | 同名不同人是两条记录，合并必须留下审计行 | 构造两个同名人物，断言不静默合并；若合并则 `entity_resolution_audit` 有行 |

## 2. 现状核对

已实现的部分：

- 抽取机制完整。LLM 分批读分块并报出实体与关系，被 `domain.yaml` 的类型约束，未知类型与悬空端点被丢弃而不是猜测（`src/sci_rag/graph/extractor.py` 模块 docstring）。
- 实体按名规范化并累积证据指针：再次见到同一名字是给既有实体加 `document_ids` 与 `chunk_ids`，不产生重复行（`extractor.py` docstring；字段见 `src/sci_rag/db/models.py:179-201`）。
- 关系携带证据：引文原句加出处 chunk（`models.py:242-250`）。
- 抽取是增量的：每个处理过的 chunk 打 `graph_extracted_at` 戳，重跑只碰新材料，失败批次不盖章等下次重试（`models.py:121`）。
- 实体消解带审计：`EntityResolutionAudit` 逐次合并留行（`models.py:213-229`）。
- 主题簇已实现并带嵌入：`kg_communities` 的 `member_entity_ids`、`summary`、`summary_embedding`（`models.py:259-280`），对应本稿的 `C-10 主题`。
- 本体可草拟且校验：`sci-rag draft ontology --from-corpus` 与 `--refine`，产出经与加载器相同的 pydantic 模型校验。
- `doctor` 报本体规模与命名。

缺失的部分：

- **本体是农业领域**。`domain/domain.yaml` 的 9 个类型是 Feedstock、Crop、Region、ConversionProcess、Product、Property、Equipment、Policy、Organization。个人文件空间里没有 Feedstock，也**没有 Person**，更**没有 Project**。这是 P2 的前置项，不是可选项。
- **「项目」不是任何字段**。`Document` 的 16 个字段（`models.py:56-85`）里没有项目，`extra` JSONB 只装解析器名与摄取时间戳（`ingester.py:156-159`）加后续的 crossref 块。
- `Document.source` 已在承担「来源桶」角色（`domain/prompts/manifest_metadata.md` 里叫 source bucket，取值如 `county_ag_reports`、`journal_papers`）。它是文档从哪来，不是文档属于谁的哪件事，两者不得合并。
- **「主题」目前只有一层含义**，即社区簇。如果本体里再加一个 `Topic` 实体类型，就会产生两个都叫主题的东西。这一点必须在设计里先讲清，否则实现阶段必然出现术语漂移。

## 3. 设计

### 3.1 先解决术语歧义：主题的两个层次

个人文件空间里的「主题」有两种，它们是不同机制，不能用一个词指代两者：

| 名称 | 定义 | 载体 | 生成方式 | 用途 |
|---|---|---|---|---|
| 命名主题 | 文中被明确写出的主题词，例如「迁移学习」「合同评审」 | `KgEntity`，`entity_type='Topic'` | 抽取，受本体约束，带证据 chunk | 浏览时的主题分面、按主题过滤 |
| 主题簇 | 相关实体聚成的簇加一段摘要，对应 `C-10 主题` | `kg_communities` 行 | 聚类加摘要，无逐条证据归属 | 回答「这批文件都在讲什么」 |

写死两条规则：分面与过滤一律用命名主题；摘要与概览一律用主题簇。功能稿里出现「主题」时必须带限定词。

### 3.2 本体替换：交付一套个人文件空间领域

`domain/domain.yaml` 的 `entity_types` 换成下列十二类（本体允许 6 到 15 类，见 `domain/domain.yaml` 的注释）：

`Person`、`Organization`、`Project`、`Document`、`Event`、`Topic`、`Artifact`、`Technology`、`Place`、`TimePeriod`、`Metric`、`Decision`

`relation_types` 换成：`AUTHORED_BY`、`MENTIONS`、`PART_OF`、`PRODUCES`、`USES`、`PRECEDES`、`SUPERSEDES`、`RELATES_TO`、`LOCATED_IN`、`HAS_METRIC`、`DECIDED_IN`。

两处必须写清的区别：

1. `PART_OF` 是实体级的「属于某个项目」，可以连 `Person → Project`；文档级的项目归属走 `C-6 项目` 的列，不走图。两者不是一回事，文档级归属是过滤维度，需要索引。
2. `SUPERSEDES` 是内容级的「这份文档在内容上取代了那份」，由抽取判断；`C-4 版本链` 是同源文件的修订序列，由路径身份判定。前者可能跨文件，后者必定同源。不得互相推导。

配套内容：按仓库不变式，领域语义留在 `domain/`，不写进 Python（`src/sci_rag` 只放通用能力）。因此新本体进 `domain/domain.yaml`，新提示词进 `domain/prompts/`，两处都不用改包代码。

需要新增或改写的提示词：

| 文件 | 用途 |
|---|---|
| `domain/prompts/entity_extraction.md` | 改写为个人文件空间语境，保留现有的「只报文本确实陈述的」约束 |
| `domain/prompts/project_inference.md` | 新增，从文档头部推断所属项目 |
| `domain/prompts/tag_extraction.md` | 新增，抽取文档级关键词作为自动标签 |
| `domain/prompts/community_summary.md` | 语境改写，其余不变 |

### 3.3 人物：两个层次分开存

| 层次 | 含义 | 载体 | 来源 |
|---|---|---|---|
| 文档参与者 | 这份文件的作者、收件人、参会人 | `documents.authors`（已有列） | 清单声明、邮件头、文档属性 |
| 文中人物 | 正文里被提到的人 | `KgEntity`，`entity_type='Person'` | chunk 级抽取 |

分开的理由是可检索性：文档参与者是文档的属性，用于过滤与引用格式化；文中人物是语料内的实体，用于图检索与消解。把收件人塞进 `kg_entities` 会让每个人的收件箱变成一张巨大的关系网，而把被提到的人塞进 `documents.authors` 会让「谁写的」这个字段失去意义。

隐私约束：人名是敏感数据。既有的「轨迹必须无内容」不变式继续适用（`AGENTS.md` 的降级与轨迹条款），人名只落库、不进轨迹、不进日志。导出时受 scope 约束，与 F3 的导出规则一致。

### 3.4 项目：三个来源与一条优先级

| 优先级 | 来源 | 触发方式 | `project_source` 取值 |
|---|---|---|---|
| 1（最高） | 人工指派 | 清单字段，或 `sci-rag project assign <doc> <project>` | `manual` |
| 2 | 目录规则 | 用户自写的路径规则，`~/work/clientA/**` 映射到某项目 | `rule` |
| 3（最低） | LLM 推断 | `project_inference.md`，从文档头部判断 | `inferred` |

一条与许可证原则的**有意分歧**，必须写进文档以免后人误改：

- `license_class` **绝不推断**（`AGENTS.md` 的草拟器条款）。许可决定是法律判断，猜错有法律后果，且用户看不出模型猜了。
- 项目归属**可以推断**，但必须三重可见：来源写进 `project_source`、置信度写进 `extra["project_confidence"]`、人工指派后永久不被覆盖。

三点分歧的理由是后果可逆性：项目归错只影响分组与排序，用户扫一眼就能发现并改；许可猜错会把不该外发的内容放进外部可见范围，发现时已经晚了。所以前者可以自动、后者不可以。

实现顺序固定为：先应用目录规则，再跑推断，最后让人工指派覆盖一切。人工指派写入后，后续任何一轮推断或规则都不得改写该行的 `project_id` 与 `project_source`。

### 3.5 标签：手工与自动分开存

`tags` 只放人工标签，`auto_tags` 只放自动标签。分列而不是靠来源字段区分，理由是二者的信任级别不同，用户需要能一眼分辨，而混在一列里再怎么标来源都会在界面上丢失。

自动标签来自两条零额外成本或低成本的通路：本体内实体名在文档中的出现（无需 LLM），以及 `tag_extraction.md` 的关键词抽取（需凭据）。手工标签由清单声明或命令写入。

### 3.6 数据流

```
F1 解析产出分块
  → 摄取时应用清单与目录规则，写 project_id / project_source='rule'|'manual'
  → 文档级第二遍：项目推断 + 自动标签        （需要凭据；无凭据则整段跳过并声明）
  → chunk 级抽取：实体（含 Person、Topic）与关系   （需要凭据）
  → 实体消解（带审计）
  → 主题簇：社区摘要               （需要凭据）
```

无凭据时的行为沿用既有契约：图路径整体不可用，向量与关键字检索仍工作。个人文件空间的离线降级要明确写清产物少了什么，不能让用户以为跑完了就是全量。

### 3.7 错误处理

- 模型返回非法 `entity_type`、悬空关系端点、超出别名上限的名字：丢弃该条，计入抽取报告的丢弃计数（沿用 `extractor.py` 既有校验）。
- 推断失败或置信度缺失：`project_source` 落 `inferred`、置信度落 NULL，但**不写 `project_id`**。宁可不归类，也不要写一个来源不明的归属。
- 无凭据：文档级第二遍整体跳过，`doctor` 报告「未抽取文档数」。

## 4. 数据模型与迁移

本稿对契约的贡献已并入程序稿 §4.2，类型、默认值与索引定义以那份为准，不再重复。

### 4.1 为什么这两样需要成为列

判据见程序稿 §4.2.1（参与过滤、排序或唯一性约束的信息用列）。本稿的两项各自对应一条验收标准，且都需要被 SQL 直接断言：

- `project_source` 承载 `A2-5` 的优先级不变式。它记录归属来自 `manual`、`rule` 还是 `inferred`，人工指派后的锁定语义由它表达。若塞进 JSONB，`A2-5` 会退化成字符串匹配测试，而这条不变式恰恰是项目维度可信的前提。
- `auto_tags` 承载 `A2-6` 的分离要求。自动标签与人工标签分列而不是靠来源字段区分，因为二者信任级别不同，用户需要一眼分辨，混在一列里再标来源也会在界面上丢失。

`DS-5` 三张图表的 schema 不改：`KgEntity.entity_type` 已是文本列，新增 `Person` 与 `Project` 两个取值不需要迁移。这一点是本稿不使用迁移的主要原因，另一处元数据（`extra["project_confidence"]`）按判据留在 JSONB，因为它只在人工复核时看。

## 5. 改动文件清单

| 文件 | 改动 |
|---|---|
| `domain/domain.yaml` | 换本体：十二类实体、十一种关系、`query_classes` 改为个人文件空间的问句类别 |
| `domain/prompts/entity_extraction.md` | 语境改写 |
| `domain/prompts/project_inference.md` | 新增 |
| `domain/prompts/tag_extraction.md` | 新增 |
| `domain/prompts/community_summary.md` | 语境改写 |
| `domain/project_rules.yaml` | 新增，路径到项目的映射规则，由用户维护 |
| `src/sci_rag/graph/extractor.py` | 不改通过类型校验的逻辑；增加对 `Person`、`Topic` 的计数报告 |
| `src/sci_rag/projects.py` | 新增，规则匹配、优先级合成、人工指派、`manual` 锁定 |
| `src/sci_rag/tags.py` | 新增，实体名派生与关键词抽取两条通路 |
| `src/sci_rag/cli/main.py` | 新增 `project` 命令组（`assign`、`list`、`rules check`）；`doctor` 报本体类型与未抽取文档数 |
| `migrations/versions/0008_*.py` | 两列与一个索引（与程序稿的同一次迁移） |
| `docs/` | 本体页更新；新增一页说明项目优先级与许可证原则的分歧 |

## 6. 测试计划

**单元测试**：

- 本体校验：十二类与十一种关系全部可加载；注入未知类型断言被丢且计数 +1。
- 项目优先级：三种来源的两两组合各一组用例，断言合成结果与 `project_source`。
- 人工锁定：`manual` 之后跑规则与推断，断言不变。
- 标签分列：自动通路写入 `auto_tags`、人工通路写入 `tags`，互不污染。
- 人物两层次：文档参与者与 `Person` 实体分别落位，互不覆盖。
- 命名主题与主题簇不混用：断言分面查询读 `KgEntity`，摘要查询读 `kg_communities`。

**集成测试**：

- 小语料走完 3.6 的数据流，断言实体、`Person`、项目、标签的计数与来源分布。
- 无凭据路径：断言降级可见，`doctor` 报未抽取数。
- 幂等：同一语料跑两轮，实体行数不增，`auto_tags` 不重复。

**对抗性测试**：

- 两个同名人物：断言不被静默合并；若消解合并，必须有审计行。
- 文档头信息不足以判断项目：断言不写 `project_id`。
- 模型返回超出别名上限、超长实体名、非法关系类型：断言逐条拒绝且可见。

**隐私**：断言抽取轨迹里不含人物姓名、不含 chunk 文本。

## 7. 验收命令

```bash
make db-up && uv run sci-rag db upgrade
uv run sci-rag doctor                       # 本体类型清单应含 Person 与 Project
uv run sci-rag build /path/to/folder
uv run sci-rag project rules check           # 规则文件可加载、无冲突
uv run sci-rag stats                         # 实体、关系、主题簇计数
uv run pytest tests/unit -q -k "ontology or project or tags or entity"
uv run pytest tests/integration -q -k "extract or metadata"
make check
```

## 8. 风险与不做的事

| 编号 | 风险 | 处置 |
|---|---|---|
| R2-1 | 术语漂移：命名主题与主题簇被混用 | §3.1 写死分工；功能稿里出现「主题」必须带限定词 |
| R2-2 | 项目推断把不相关的文档并进同一项目 | 优先级保证人工可覆盖；`project_source` 与置信度可查；导出一份「按推断归类的文档」清单供人工复核 |
| R2-3 | 人名落库后的隐私面 | 不进轨迹与日志；导出受 scope 约束；本地单机形态下不外发 |
| R2-4 | 本体替换使既有 demo 语料抽取结果失真 | demo 语料本就是合成农业语料，换本体后它不再是有效样本；F4 的验收需要一套个人文件空间的合成语料，见 F4 |
| R2-5 | 文档级第二遍多一次凭据开销 | 只在文档头部若干字符上做，不重读全文；可按目录开关 |

**明确不做的事**：

- 不做人脸识别或从图片中识别人物。
- 不维护跨语料的全局人物词典，不做同名消歧的领域先验。
- 不抽取主张级事实（claim extraction），只到实体与关系。
- 不自动创建项目。项目必须由人工指派、规则映射或推断三选一产生，且推断结果可被一键清除。
- 不把 `source` 与 `project` 合并成一个字段。

## 9. 依赖关系

**前置**：P0 清障；P1 的 `M-0008`（含本稿 §4 的两列）；F1 产出的分块质量直接决定抽取质量，尤其是邮件正文与 Office 标题层级。

**后置**：F3 的 `C-8 相似度` 用实体的 `document_ids` 做候选集收敛；F5 的主题分面读命名主题，概览读主题簇；F5 的项目过滤读 `C-6`。

**开放问题**：

1. 目录规则的表达力：只做 glob 前缀匹配，还是要支持正则与优先级排序？倾向只做 glob，够用且可解释。
2. 文档级第二遍是否应为可选阶段，取决于它在真实语料上的耗时占比。
3. 项目推断用哪个模型档位。仓库已支持答案模型与评测模型分开配置，项目推断可以复用较低档位以省成本。
