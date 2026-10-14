# 增量更新设计：文档级 reconcile

- 日期：2026-10-08
- 状态：已批准（分 5 节逐节确认）
- 决策：**自研 reconcile，不接入 CocoIndex**
- 范围：`sci-rag-kit` 的摄取路径（`sci-rag ingest` / `sci-rag build`）
- 规模：1 个新模块 + 报告数据类 + 两处接线 + 测试 + ADR + 文档；**零依赖、零迁移、零新进程**

---

## 1. 目标与非目标

### 目标

批量 on-demand 形态下的增量更新：反复运行 `sci-rag build <folder>` 时，只处理语料中真正变化的部分。

- 未变的文件：**不解析、不嵌入、不算图**（当前每次全量重解析）
- 新增的文件：整篇摄取
- 修改的文件：替换（而不是像现在这样留下一条重复文档）
- 删除的文件：连同其图证据一起清理（现在会永远留在库里）

### 非目标

- 不做常驻进程 / 文件监听（用户已明确选批量 on-demand）
- 不做 chunk 级复用（用户已明确选文档级粒度）
- 不动 scope 规则、融合权重、答案提示词、评测方法、本体
- 不改 schema，不加迁移，不加依赖
- 不动 enrichment（Crossref 自带 30 天过期窗，`src/sci_rag/enrich.py:109`），仍走独立命令

---

## 2. 决策依据：调研与 PoC 实测

两条候选路线都做了源码研读，**接入 CocoIndex 的路线跑了 10 项实测**（一次性 Postgres 16 + pgvector，装入 kit 的真实 Alembic schema：8 张表、`alembic_version` 到 0006）。

### 证据出处（重要）

- **探针跑在 PyPI `cocoindex==1.0.25`**（2026-10-08 安装到独立 venv，未污染 kit 的 `.venv`）。
- 本地检出 `C:\Users\12062\OneDrive\Desktop\items\cocoindex`（HEAD `8c3c93ea`，2026-09-28）与它**不是同一份代码**：`python/cocoindex/connectors/postgres/_target.py` 里查不到 `_array_literal` 与 `typcategory`（只存在于编译产物 `.pdb`）。因此第 6 号探针的机制说明标注为 **1.0.25 site-packages 行号**，本地检出无此代码路径。
- 两处一致、可直接引用本地检出的：`connectorkits/statediff.py:128`、`connectors/postgres/_target.py:5`（"Table level: Creates/drops tables"）、`_target.py:1050`（`DROP TABLE IF EXISTS`）。

### CocoIndex 的模型

声明式（`TargetState = Transform(SourceState)`）：你声明目标状态，引擎自己检测源变更并同步增删；`@coco.fn(memo=True)` 跳过未变的函数；状态存在自己的 LMDB 库；live 模式可常驻监听。Postgres 连接器支持 `managed_by` 两种模式。

### 实测结果

| # | 探针 | 结果 |
|---|---|---|
| 1 | USER 模式写 kit 的 `documents`（8 个必填列齐备） | 插入 2 行，**schema diff 为空**，kit 自己写的行原样保留 |
| 2 | 二次运行少声明一行 | 未声明的行**被删除**，外来行保留，仍无 DDL |
| 3 | 只声明 4 个"自然会想到的"列 | `NotNullViolationError: null value in column "authors"`；`ingested_at` 的 `now()` 服务端默认值被正确采用 |
| 4 | SYSTEM 模式（CocoIndex 默认）对已存在的 kit 表 | `DuplicateTableError: relation "documents" already exists`，不删数据、不改 schema |
| 5 | 写 kit 的 `chunks`（`vector(1536)` + FK + 生成列） | 行插入、`dims=1536`；HNSW(`m=16,ef=64`)/GIN/FK 全在；**生成列 `search_tsv` 自动填充** |
| 6 | `text[]` 列 | `TypeError: a list is expected for an array column, got 'str'`（`from_class` 把 `list[str]` 映射成 jsonb 并编码，而库里真实列是 `text[]`）；用 `PgType("text[]")` override 后通过 |
| 7 | 状态存储 | LMDB 目录 52K，**确认是第二个持久化存储** |
| 8 | SYSTEM 模式，CocoIndex 自己拥有的表，非主键列变更 | **ALTER**：OID `16840 → 16840` 不变，列就地替换；被删列的数据销毁 |
| 9 | 同表，**主键变更** | **DROP + CREATE**：OID `16840 → 16847`，行 `2 → 1` |
| 10 | 删除 `documents` 行后 kg 证据状态 | **全部悬空**：`kg_entities.document_ids` 仍指已删文档、`kg_entities.chunk_ids` 仍指已被 FK 级联删掉的 chunk、`kg_relationships` 出处同样失效、社区仍称其"基于该证据"；`evidence chunks still referenced by kg: 0` |

**机制定位**：

- CocoIndex 从 `pg_catalog` 读**真实列类型**判断是否为数组（1.0.25 site-packages `connectors/postgres/_target.py:741-749`），再对值调 `_array_literal()`（同文件 `:960`），所以"声明类型"与"真实列类型"不一致时**以数据库为准**。探针 3 的 `varchar(32)` 拒绝 `text` 声明也是同一机理。
- USER 模式零 DDL 的依据是 `connectorkits/statediff.py:128`：user-managed 直接返回 `None`（本地检出与 1.0.25 一致）。
- 探针 9 的 DROP 走 `_target.py:1050` 的 `DROP TABLE IF EXISTS`，触发条件是主键签名变化（`statediff` 的 `replace` 动作）；非主键列变更只走 `ALTER`，证据是 OID 不变。

### 为什么排除接入（方案 A）

- **它替不掉真正难的那半边**（探针 10）：`kg_entities.document_ids/chunk_ids` 是 ARRAY、`kg_relationships.document_id/chunk_id` 是裸 `varchar(32)`，都不是外键（`db/models.py:190-191, 248-249`），没有任何级联会到达它们。`sci_rag.corpus.delete_documents` 的证据擦除、关系删除、社区丢弃一行都省不掉，而它正是接 CocoIndex 后必须额外挂的钩子。
- **它只能替掉便宜的那半边**：源侧变更检测、行级增删、并行调度。批量 on-demand 下文件指纹扫描的价值有限（live 模式已排除）。
- **额外代价**：LMDB 第二存储（违反 `docs/architecture.md:166-171` 的"刻意不做的东西"与 README 的"一个东西要跑、要备份"）；行类必须覆盖 8 个 `NOT NULL` 且无服务端默认值的列；2 处类型 override；必须用 USER 模式（SYSTEM 冷库报错，接管成功后会 ALTER 或 DROP）；按路径身份会推翻 README 已文档化的按内容去重语义。

### 排除方案 C（混合）

自研 reconcile 为主线、CocoIndex 只做 memo 跳过薄层：拿不到删除传播（没有 target 就没有"路径消失→清理"），仍要自研；为此引入 Rust 原生扩展 + LMDB + 生命周期管理，只换来 `os.walk` + 一个 dict 的能力。**新增复杂度大于所获收益。**

---

## 3. 架构与数据流

新模块 `src/sci_rag/reconcile.py`（对齐既有的 `corpus.py` / `enrich.py` / `snapshot.py` 单职责平铺模块），只在摄取步骤之前调用一次。

```
sci-rag build <folder>
      │
      ▼
 ┌─ reconcile(源侧语料, 库中该作用域下的文档) ─────────┐
 │  未变   → 跳过（不解析、不嵌入、不算图）              │
 │  新增   → 待摄取                                     │
 │  仅元数据变 → 解析比对后只更新指纹，不嵌入             │
 │  变更   → 解析比对 → delete_documents(旧) → 待摄取   │
 │  消失   → delete_documents(该id)                    │
 └──────────────┬──────────────────────────────────────┘
                ▼
      ingest_entries(仅"新增+变更"两批)      ← 现有代码不动
                ▼
      graph extract / communities           ← NULL 过滤天然只处理新块
```

**注意**：图中"变更"一行**刻意**是"先解析比对、再删旧文档"的顺序，理由见 6.1，解析失败必须只记 `failed` 而不删任何东西。

### 不动的东西

`retrieve/` 的 scope-before-ranking、`answer/` 的引用契约、`evals/` 的评测方法、`domain/` 语义文件、已有 6 个迁移。**不改 schema，因此不需要新迁移。**

### 顺带修一处文档/行为落差

`build` 的 docstring 写 "Re-running only processes new chunks."（`src/sci_rag/cli/main.py:445`），但按 `ingest/ingester.py:125-137`，改过内容的文件会作为一条新文档整体重摄、删掉的文件其文档永远留在库里。本功能让这句话在摄取层也成立，docstring 需同步改写。按 `AGENTS.md:19-21`，这类落差必须显式指出并做最小一致修正。

---

## 4. 身份与变更判定

**身份 = 源文件的绝对路径。**

库里现在没存路径：`source_ref = entry.url or path_str`（`ingest/ingester.py:144`），文件夹摄取时它就是路径，但 manifest 带 `url` 时路径就丢了。所以摄取时把解析后的路径写进已有的 `Document.extra["path"]`（JSONB，**不需要迁移**），旧数据回退用 `source_ref` 匹配；**匹配不到的旧文档如实报为 `no_path_recorded` 并跳过，不猜。**

**变更信号 = 指纹**（同样写进 `extra["source_fingerprint"]`：文件 `size` + `mtime_ns`）。只比路径不够；比内容 hash 又必须先解析 PDF。指纹让"未变"这条路径一次解析都不用做。

| 判定 | 条件 | 代价 |
|---|---|---|
| 未变 | 路径在库 + 指纹相同 | 0 次解析、0 次嵌入 ← 收益来源 |
| 仅元数据变 | 指纹变，但解析后 `content_hash` 与库中相同 | 解析+分块，不重嵌入、不动图 |
| 真变更 | 指纹变 且 `content_hash` 不同 | `delete_documents(旧)` → 整篇重摄 |
| 新增 | 路径不在库 | 整篇摄取 |
| 消失 | 库中有、源侧无 | `delete_documents(该id)` |

**为什么用路径而不是内容做身份**：内容身份无法在不解析全部文件的前提下判断"某个文件被删了，但同内容还在别处"。`content_hash` 唯一约束**保持不变**，仍是并发与重复内容的兜底（`ingest/ingester.py:178-183` 的 `IntegrityError` 分支继续有效），变的只是"哪条路径代表这条文档"。

**首跑一次性全量**：升级前的老文档没有指纹，必须解析一次比对 `content_hash`，之后补上指纹，从第二轮开始才走 0 解析快路。这条会在输出里明说，不装作一开始就是增量的。

---

## 5. 图层失效

`delete_documents` 已经做对了大部分，且是单事务原子的（`corpus.py:73-76`，一次 commit）：删引用指针 → 删关系（`:108`）→ 擦实体的 `document_ids`/`chunk_ids`（`:131`）→ 删受影响社区（`:139`）→ 删文档（chunks 由 FK 级联）（`:148`），区间 `corpus.py:94-148`。

它**故意不做**两件事，reconcile 要接手：

1. **`graph gc`**：证据被擦空的实体行还留着。gc 的顺序是"先删无证据实体（其关系随之级联）→ 再删端点缺失的关系 → 再删成员消失的社区"（`corpus.py:170-172`），默认 `--dry-run`（`cli/main.py:2041-2042`）。
2. **社区重建**：`delete_documents` 只删受影响社区，留下覆盖洞；`build_communities` 是全量重建：`delete(KgCommunity)` 后全部重算，一个社区一次 LLM 调用（`graph/communities.py:113-121`），且它读的是全部 `KgEntity`（`:97`），所以无证据实体也会被聚进去。

```
graph_evidence_changed?   ← 本轮有文档被删除或被替换
  ├ 否（仅新增/未变/仅元数据变）→ 不动图；现有 NULL 过滤已足够
  └ 是 + 有凭据 → graph extract(新块) → graph gc --apply → graph communities(全量)
       └ 无凭据 → 打印 kit 现有那句可操作提示，不静默降级
```

**关键顺序：`gc` 必须在 `communities` 之前**，否则重建出的社区会包含刚被擦空证据的实体。`build` 现在只跑 extract（`:471`）→ communities（`:475`），从不调 gc（`cli/main.py:471-475`）。

**`graph gc --apply` 的自动范围**：`build` 只对**本轮刚被自己删空的实体**自动 `--apply`（这些实体的证据是本轮删除造成的，不是历史遗留），并在报告里打印删了多少；历史遗留的 gc 仍只在用户显式跑 `graph gc` 时处理。这样避免 `build` 变成"会悄悄删历史数据的命令"，又不会每轮都留下新的空实体。

**实现前提（否则该承诺不可测）**：`delete_documents` 目前只返回**计数**（`DeleteOutcome.entities_scrubbed: int`，`corpus.py:49`；赋值在 `:131`），拿不到实体 id，因此无法区分"本轮擦空的"和"历史上就空的"。需要给 `DeleteOutcome` 增加一个 `affected_entity_ids: list[str]` 字段（现有字段不动，属加法变更），reconcile 再从中筛出证据已为空的那些，**只删这个集合**。给 `graph_gc` 增加一个 `only_entity_ids` 过滤参数，而不是在 reconcile 里重写一遍 gc 的三段清理顺序（`corpus.py:165-172`）。

---

## 6. 安全顺序、作用域、报告与幂等

### 6.1 逐文件顺序：解析必须先于删除

如果文件此刻解析失败就先删了旧文档，等于用一次读取错误换来内容丢失。正确顺序是**逐文件**：

```
per changed file:  parse ──✗ fail──▶ keep old, status=failed   (不删)
                     │ ok, hash == 库中 → metadata_only: 只更新指纹
                     ▼ ok, hash 不同
                delete_documents(old) → embed → insert
```

**消失**的文件没有可解析的对象，直接删即可（仍在删除阶段最前执行，使"改名"在同轮内自愈：删掉 P 的文档后，Q 的内容在库里已无对应行 → 被当新增重新摄取）。

### 6.2 删除作用域（fail-closed）

`sci-rag build data/raw/只放了三个文件的子目录` 不能把其它 200 篇全删掉。

规则：**只对"本轮构建根目录之下"的文档考虑删除**，文件夹模式根目录 = 传入的 folder，manifest 模式 = manifest 所在目录；根目录之外的文档一律**不删，只计入 `out_of_scope` 计数**。路径天然给出一个不会越界的删除范围，符合 `AGENTS.md:297-311` 的 scope/fail-closed 规则。

（备选方案"manifest 即整个语料的权威清单、根目录外也删"被否决：用户只 lint 或局部更新 manifest 时删得更狠。）

### 6.3 报告与退出码

新增 `ReconcileReport`，状态枚举（8 种）：

`unchanged / metadata_only / updated / added / removed / out_of_scope / no_path_recorded / failed`

与现有 `IngestReport`（`ingest/ingester.py:39-52`）并列打印成一张 rich 表。沿用 `build` 现有退出码规则：有 `failed` 才 `typer.Exit(1)`（`cli/main.py:481-482`）；`removed` / `updated` 不算失败。日志用 structlog，只记元数据不记内容（`AGENTS.md:376`）。

`sci-rag doctor` 加一行：`documents without a recorded path: N（无法参与对账）`，否则"哪些文档对不上账"就成了沉默信息。

### 6.4 幂等与中断自愈

reconcile 的终态只由"源侧文件集 + 库中路径"决定，跑两遍结果相同。任何中断后下一轮都会收敛，因为身份是路径且源文件还在：

- 删了旧的没插新的 → 下轮判为"新增"重新摄取
- 插了一半的文档被现有"每文档一事务"挡住（`ingest/ingester.py:1-7`），不会留半篇

---

## 7. 测试、ADR 与文档

### 测试分层（`AGENTS.md:387-407`）

| 层 | 文件 | 测什么 | 依赖 |
|---|---|---|---|
| unit | `tests/unit/test_reconcile.py` | 分类纯函数的 8 种状态、指纹比较、路径解析、**根目录越界必须返回"不删"**、变更文件解析失败时**必须保留旧文档** | 无 DB |
| integration | `tests/integration/test_reconcile.py` | 删+摄配对、`extra["path"]` 落库、**无路径的旧文档走 fallback 且被如实报出**、连跑两轮计数不变、中断后下轮收敛、删除后 `kg_*` 证据被 `delete_documents` 擦干净 | 一次性 Postgres |
| 对抗 | 同上 | 范围外文档**断言不被删**（断言缺失，不只断言存在，`AGENTS.md:399-400`）；`license_class` 不被 reconcile 触碰 | 一次性 Postgres |

### 变更证据

`AGENTS.md:344-347` 要求检索类改动附前后消融。本改动**不改 chunking/retrieval/fusion/eval 任何一处**，所以正确的证据是**零差异证明**：语料未变时 `build` 跑两轮 → `sci-rag corpus snapshot` 的语料摘要完全一致、`eval retrieval` 逐层分数相同（`cli/main.py:1854` 的 `corpus snapshot` 记录每文档 hash）。有语料变动的前后对比另跑一次 `eval diff`。

### ADR

新增 `docs/adr/0012-document-level-reconcile.md`（context / decision / consequences / reversal conditions，`AGENTS.md:420-421`）。

**撞号提醒**：仓库里那份未跟踪的 ModelScope/DeepSeek 计划自己占了 `docs/adr/0012-modelscope-deepseek-providers.md`。谁先落地谁用 0012，后落地的顺延为 0013；落地前必须核对 `docs/adr/` 的实际文件名并按实际编号落位，**不能照抄本节的编号**。

### 文档同改（`AGENTS.md:411-413`）

- `build` / `ingest` 的 docstring（第 3 节那处口径落差）
- README「Use your own documents」段、`docs/bring-your-own-domain.md`（七步配方）、`docs/learn.md`、`docs/faq.md`
- `docs/cli.md` 由 `scripts/render_cli_docs.py` 生成 → 跑对应 make 目标重生成，不手改
- `AGENTS.md` 仓库地图加一行 `src/sci_rag/reconcile.py`
- `mkdocs.yml` 若新增页面，必须先在 `docs/STYLE.md` 的页型表里分类，否则构建失败（`AGENTS.md:417-418`）

---

## 8. 已确认的设计决策汇总

| # | 决策 | 结论 |
|---|---|---|
| 1 | 运行形态 | 批量 on-demand，无常驻进程 |
| 2 | 增量粒度 | 文档级 |
| 3 | 技术路线 | 自研（方案 B），排除接入与混合 |
| 4 | 文档身份 | 源文件绝对路径（`extra["path"]`），`content_hash` 仍作唯一兜底 |
| 5 | 老数据 | 首跑一次性全量解析后补指纹，输出里明说 |
| 6 | 变更文件顺序 | 先解析比对，成功才删旧文档 |
| 7 | 删除作用域 | 仅构建根目录之下，范围外计 `out_of_scope` 不删 |
| 8 | `graph gc --apply` 自动范围 | 仅本轮刚被自己删空的实体（需 `DeleteOutcome.affected_entity_ids` + `graph_gc(only_entity_ids=...)`）；历史遗留留给显式命令 |
| 9 | schema / 依赖 | 零迁移、零依赖、零新进程 |

## 9. 撤销条件

满足任一条即应重新评估（尤其是重新评估"接入 CocoIndex"）：

1. 需要准实时 / 文件监听的常驻形态，那时 CocoIndex 的 live 模式才有分量
2. 源侧扩展到 S3 / Kafka / Google Drive 等非文件系统源，且变更检测需要超出"路径 + 指纹"的能力
3. 需要 chunk 级复用（文件变了但未变 chunk 复用旧向量），且实测文档级重嵌入成本不可接受
4. `reconcile.py` 膨胀到需要通用 DAG/记忆化框架，且 CocoIndex 的表所有权模型已能覆盖 `kg_*` 的失效语义
