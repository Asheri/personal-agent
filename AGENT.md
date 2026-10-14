# AGENT.md: personal-agent 项目协作指南（PC-Mem）

> 本文件是项目的**总入口与协作契约**，面向所有人类协作者与 AI 编码代理。
> 配套文件：[AGENTS.md](AGENTS.md)（代码级工作契约）、[MIGRATION.md](MIGRATION.md)（迁移台账）、
> [docs/superpowers/specs/](docs/superpowers/specs/)（设计规格与审阅记录）。
> 台账与治理条款是活文档：任务状态变化与审阅记录请及时更新本文件。

---

## 1. 项目定位

**PC-Mem（全 PC 文件管理记忆系统）**：让 Agent 长期理解个人电脑上的异构文件（论文、PPT、
Word、代码、数据、图片、会议记录、邮件），不仅「找到相似内容」，还能回答「这份材料属于
哪个项目」「哪个是最新版本」「之前在哪个项目里做过类似的事」，并随着新文件持续更新知识。

三层职责（完整架构见规格 §1）：

```
GenericAgent 运行时（记忆面 L0-L4 + 记忆调用路由）      经验、偏好、路由知识
        |  CLI / MCP 调用                        提纯 / 主动注入
服务面（RagService 单门面: REST + MCP, scope 收口）
        |
知识库底座（Postgres 16-18 + pgvector: ingest/graph/relate/retrieve/answer）
        |
文件感知层（增量 reconcile: scheduler 定时 + hooks 事件 + OS 轮询兜底）
        |
C:\Users\<user>\ 下的异构文件
```

需求六项与研究难点到验收判据（A1-A7）的映射见规格 §0；本项目**以该规格为唯一设计基线**。

## 2. 仓库地图

| 路径 | 内容 | 来源 |
| :--- | :--- | :--- |
| `src/sci_rag/` | 知识库底座（ingest/graph/retrieve/answer/server/db/campaigns 等） | sci-rag-kit fork |
| `tests/` | unit / integration / server / docs / cloud 分层测试 | fork |
| `domain/` | 出厂 demo 域（农业语料），**测试基线，勿动** | fork |
| `domain-personal/` | **个人文件空间域**：12 实体 / 11 关系 / 中文提示词，`SCI_RAG_DOMAIN_DIR=domain-personal` 切换 | 本项目特化 |
| `plugins/` | `hooks.py`、`project_mode.py`（GenericAgent 原件）+ `pcmem_router.py`（记忆路由骨架） | GA + 本项目 |
| `memory/` | GA 记忆面种子：L0 META-SOP、L1 索引、L2 事实、L3 `pcmem_sop.md` | GA + 本项目 |
| `docs/superpowers/specs/` | **设计规格 v1.1 + 审阅记录**（受治理基线，见 §5） | 本项目 |
| `migrations/` + `alembic.ini` | Alembic 迁移 | fork |
| `MIGRATION.md` | 迁移台账：出处、排除清单、偏差记录 | 本项目 |
| `AGENTS.md` | 代码级工作契约（上游运营合同 + fork 注记） | fork + 注记 |

**外部依赖**：GenericAgent 运行时（外部实例，不 vendored；种子代码不可修改）；
PostgreSQL 16-18 + pgvector。

## 3. 环境与快速上手

```bash
# 依赖（Python 3.11 或 3.12；禁 3.14）
uv sync --extra modelscope-embedding --extra openai

# 切换个人域
export SCI_RAG_DOMAIN_DIR=domain-personal     # Windows: set SCI_RAG_DOMAIN_DIR=domain-personal

# 测试（本机无 make，用等价裸命令）
uv run ruff check src tests examples scripts
uv run ruff format --check src tests examples scripts
uv run mypy
uv run pytest tests/unit -q
```

- **数据库**：docker 容器 `sci-rag-kit-db-1`（pgvector，端口 5433），或 `SCI_RAG_DB_BACKEND=local`。
  集成/server 测试会破坏 `SCI_RAG_TEST_DATABASE_URL` 指向的库：**只准指向一次性测试库**，
  绝不准指向开发/生产库。
- **凭据**：`.env` 本机自建（参考 `.env.example`），不入库、不打印、不进日志。无生成凭据时
  图抽取/社区摘要/答案生成整体降级，向量与关键字检索仍可用。
- **生成文档三件套**（`docs/cli.md`、`docs/configuration.md`、`docs/benchmarks.md`）由脚本生成，
  禁止手改；Windows 上重渲染 `docs/cli.md` 有反斜杠陷阱（`data\campaigns` 渲染差异），必须按
  「渲染到 scratch、归一化、diff 核对」流程，详见 AGENTS.md 与历史会话记录。

## 4. 协作规范（多人）

### 4.1 分支、提交与 PR

- 分支命名 `<type>/<topic>`（`feat/`、`fix/`、`docs/`、`spec/`、`test/`）；Conventional Commits；
  一 PR 一主题，不夹带无关重构。
- PR 描述固定四段：**改动 / 验证（跑了什么、退出码）/ 残余风险 / 跳过项（为什么跳）**。
- 涉及规格语义的 PR 还须满足 §5 的二次审阅要求。

### 4.2 测试门槛

- 放行口径：聚焦测试 + 全量 `tests/unit` **不新增失败**（当前基线见 §7）；跳过的检查必须显式声明，
  跳过的集成测试不构成通过证据。
- 检索/评测/融合权重相关改动：同语料前后消融证据（`sci-rag eval diff`）。
- schema 改动：Alembic 迁移 + 一次性库上 `upgrade head` / `downgrade -1` 双向证据。
- bug 修复：先写能复现原失败的回归测试，再修。

### 4.3 文档与 ADR

- 用户可见行为、配置、运维变化在**同一 PR** 更新文档。
- 架构决策写 ADR（`docs/adr/`，0014 起），四节形状：context、decision、consequences、
  reversal conditions。历史 ADR 与设计记录**只 supersede 不改写**。
- 中英文排版：仓库源码与 docs 用英文（风格测试强制美式拼写，**全仓任何 UTF-8 文件禁 U+2014
  破折号**，`memory/` 下中文文件同样适用）。

### 4.4 证据纪律

- 结论标注 `文件:行号`；没查证的写「未核验」；数字给可复算口径；禁止编造 ID、数值、结果。
- 「未搜到」不等于「不存在」；「测试跳过」不等于「通过」。

### 4.5 并发约定

- **版本链 / 迁移 / reconcile 相关改动单人串行**（对应规格「单一写入方」精神）；认领见 §6。
- 集成测试各用各的一次性数据库；长任务用 `.worktrees/` worktree 隔离。
- 认领任务时在 §6.2 对应条目后标注 `@名字 (日期)`，避免两人撞同一改动面。

### 4.6 隐私红线

- `.env`、密钥文件仅引用不读取不打印；个人文件默认 `license_class='unknown'`（fail-closed），
  出站（外部 LLM、导出）默认全拒；人名/机构/项目/地点不进日志与轨迹。

## 5. 规格治理：二次审阅（强制条款）

**受治理基线**：

- `docs/superpowers/specs/设计方案-全PC文件记忆系统-spec.md`（spec v1.1，独立审查「修订后放行」）
- `docs/superpowers/specs/设计方案-全PC文件记忆系统-spec审查.md`（审查报告与修订记录）
- 审定原件存档于仓库外 `C:/Users/12062/OneDrive/Desktop/items/`；仓库内为工作基线副本
  （安装时 8 处 U+2014 纯标点归一，偏差见 MIGRATION.md）。

### 5.1 什么必须二次审阅

凡属以下任一情形的改进或变化，**必须经过二次审阅后才可合并**：

1. 修改或实现与规格相关的任何语义面：共享概念 C-1 至 C-13、存储契约（§3）、
   scope 与隐私（§5）、功能面行为（§4.1 至 §4.7）、验收判据 A1 至 A7（附录 A）。
2. 实现与规格出现**任何偏差**（包括认为规格本身有错而绕行的改动）。
3. 对规格文本本身的修订（含新增/删除章节、判据变更）。

**豁免**（PR 中声明即可）：纯排版与错字修复；不触及上述语义的测试修绿；上游 fork 同步。

### 5.2 流程（四步，缺一不可）

1. **指认**：PR/变更说明里指名受影响的 C/A 编号与规格章节（例：「spec §4.6 / A6-2 / C-4」）。
2. **实现 + 验证**：按 §4.2 门槛；规格 §7 的预注册对抗性测试是放行门槛（先补测试再改实现）。
3. **二次审阅**：由**非作者的独立审阅人**按 P0（阻断）/ P1（应改）/ P2（可选）分级审阅，
   重点对拍：规格条款是否被遵守、验收判据是否仍可机械断言、是否重蹈历史缺陷
   （旧评审 R-1 至 R-6 模式）。
4. **归档**：审阅记录存 `docs/superpowers/specs/reviews/YYYY-MM-DD-<topic>-review.md`，
   与代码同 PR 提交。

审阅记录模板：

```markdown
# 审阅记录：<主题>
- 日期 / 审阅人（非作者）/ 变更 PR 或提交
- 对拍范围：spec §X / C-x / A-x
- 判定：可放行 | 修订后放行 | 不通过（P0=n, P1=n, P2=n）
- 逐条发现与改法 / 已确认正确 / 未验证声明
```

### 5.3 规格自身的修订规则

- 版本号递增（v1.1 → v1.2 ...），修订内容追加到审查报告「修订记录」节，历史条目不改写。
- 修订后的规格**同样必须过一次独立审阅**才能成为新基线（作者不得自批）。
- 撤销条件（规格 §8）触发时：停下实现、回规格修订，而不是继续硬推。

### 5.4 违反处理

未附审阅记录的规格相关 PR **不得合并**；已合并的违规变更要么回滚、要么补审并在修订记录留痕。

---

## 6. 任务台账

> 维护规则：认领标注 `@名字 (日期)`；完成后整条移入 §6.1 并补「验证证据」；
> 阻塞项写明阻塞原因与解除条件。验收依据列指向规格附录 A 的判据编号。

### 6.1 已完成（Done，截至 2026-10-14）

| # | 任务 | 产出 | 验证证据 |
| :--- | :--- | :--- | :--- |
| D1 | 迁移 sci-rag-kit 整树 fork（510 文件，排除 `.env`/`data/raw`/`.venv`/`site` 等） | 本仓库 + `MIGRATION.md` | `uv sync` 通过；`test_docs_style` 15/15；`tests/unit` 1517 passed |
| D2 | 迁移 GenericAgent 记忆面（hooks/project_mode/L0-L3 种子），零改 GA 种子代码 | `plugins/`、`memory/` | 三模块导入通过 |
| D3 | 个人域特化：12 实体 / 11 关系 / 3 提示词 / query_classes | `domain-personal/` | `load_domain` + `render_prompt` 槽位渲染通过 |
| D4 | 记忆路由骨架（五场景触发表挂 hook 总线） | `plugins/pcmem_router.py` | hooks 注册可导入 |
| D5 | PC-Mem 设计规格 v1.1 撰写 | `docs/superpowers/specs/设计方案-全PC文件记忆系统-spec.md` | 独立审查「修订后放行」 |
| D6 | 独立审查（P0=1/P1=7/P2=8）并修订 | `...-spec审查.md` + spec v1.1（附录 A 56 条判据） | P0/P1 全修、P2 修 5 留 3（在案） |
| D7 | 测试基线归因：5 条 git 态测试转绿、`test_cli_help` 定位上游既有、`backups/.gitkeep` 修复 | 提交 `ec1c5d2` | 源仓库基线对照复跑 |
| D8 | spec 装入项目 + 标点归一（8 处 U+2014） | `docs/superpowers/specs/` 两份 | `test_docs_style` 通过 |
| D9 | 本文件（协作指南 + 任务台账 + 二次审阅治理制度） | `AGENT.md` | 二次审阅条款自本提交生效 |

### 6.2 待办（TODO）

**P0 清障**（阻塞 P1；来源：规格 §6）：

- [ ] 合并 `feature/incremental-reconcile` 分支（reconcile/fingerprint + 21 文件；合并时按
      规格 §4.6 落 `PendingIngest` 交接与版本链语义改造）⚠ **单人串行**，认领：____
- [ ] ADR 编号冲突收口：分支 `0012-document-level-reconcile` 重命名 0013 并修正自指；
      2026-10-08 reconcile 稿受影响节加修订说明（supersede 不改写）

**P1 底座**（依赖 P0）：

- [ ] M-0008-R 迁移：documents 新列、`projects`/`document_embeddings`/`file_events` 表、
      CHECK 约束、部分唯一索引（`content_hash WHERE is_current`、`version_of`）+ ADR 0014
      （版本链 / 哈希约束 / 基线谓词三决策）；downgrade 内链折叠。验收：A3-6、A6-2 + 迁移双向
- [ ] C-1 复合身份贯通：reconcile 分桶键 `(path, source_member)`、宿主成员聚合哈希探针、
      member_key 规则（Message-ID 优先）。验收：对抗测试 #9（A1-4）
- [ ] `is_current` 基线谓词 + scope 字段总表（§5.2）+ 非 walk 路径统一收口。
      **先补对抗测试 #1/#2 再改实现**。验收：A3-7、A4-6、A5-2
- [ ] `test_retrieval_scope.py` 两条断言改写 + `dataclasses.fields` 元测试兜底

**P2 写方并行**（依赖 P1，两线可并行）：

- [ ] F1 解析面：`parse_file_many`、Office 三件套、邮件（一文件多文档）、OCR 协议、
      占位文件 owner + 第 10 类状态 `placeholder_skipped`、失败统计持久化（汇总表 + 退出码）
      验收：A1-1 至 A1-7
- [ ] F2 抽取面：本体换代重建路径（graph gc/extract --all/resolve/communities）、
      项目三来源（manual>rule>inferred + 锁定）、标签分列、同名合并审计收据、
      ExtractionStats 丢弃计数、`project` 命令组（面板归属）。验收：A2-1 至 A2-8

**P3 关系面**（依赖 P2）：

- [ ] `relate/` 新包：相似（居中向量）、提及引用（对账键/消歧/CHECK）、版本链维护语义
      （删除重连、批量提升、双 reason）、读取面全部带 scope。验收：A3-1 至 A3-9

**P4 检索浏览**（spike 可提前，浏览依赖 P3）：

- [ ] 中文 keyword spike（预注册：24 条样本、`hit@20>=0.75`、`p95<=300ms`、决策规则 B→D→E；
      产物 `docs/spikes/zh-keyword-spike.md`；改造面 keyword.py/router.py/domain.py 三处）
- [ ] 浏览面：`/v1/corpus/facets`（分面硬约束 + 空值桶）、`browse` 命令组、
      MCP 扩展 4 工具（`browse_corpus`/`list_projects`/`get_related_documents`/`get_document_versions`）
      验收：A4、A5

**P5 记忆面**（依赖 P4）：

- [ ] `pcmem_router` 注入实现（五场景触发表 + 调用记录断言，验收 A7-3）
- [ ] 遗忘/热度：热温冷三层、`valid_from/valid_to`、stale 只标记不删除（A7-1/A7-2）
- [ ] 三触发通道接线（scheduler/hooks/轮询）+ `pg_advisory_lock` 单实例（A6-8）；
      `--reflect` 启动形态写入部署文档

**P6 研究**（依赖 P5，验收走研究豁免条款）：

- [ ] R8 工作历史叙事（timeline + 主题簇 + L4 归档 → 时序叙事，评分协议先行）
- [ ] 多模态增强、消融研究（include_citations / 重排器默认值需消融证据才动）

**杂项与运维**：

- [ ] `.env` 本机手工建立（凭据不入 git，参考 `.env.example`）
- [ ] `data/raw` 本机语料重建（331M 未随迁）
- [ ] 集成/server 测试首跑（起一次性测试库后；此前属未验证项）
- [ ] 迁移 up/down 双向验证（一次性库）
- [ ] compression 成对闸门在个人语料重跑（0.0 floor 仅在 demo 语料验证过）
- [ ] 轮询边际成本实测回填（规格 §4.6 标 `[待实测]`）
- [ ] `test_cli_help` 转绿（依赖 P3/P4 落地 `relate`/`refresh`/`project` 命令；**不得为消红删文档引用**）
- [ ] GenericAgent 侧部署：`--reflect`/scheduler 形态、`pcmem_router` 装入外部 GA 实例的安装说明

## 7. 已知问题与测试基线（2026-10-14）

- 基线：`uv run pytest tests/unit -q` → **1517 passed / 1 failed / 38 skipped**。
- 唯一失败 `test_cli_help.py::test_every_documented_command_exists`：上游既有（源仓库同失败，
  其新 spec 文档引用了未实现命令）；PC-Mem spec 引用的 `browse`/`relate` 等会追加 offender，
  P3/P4 落地后自然转绿。
- **未验证项**（勿当已验证）：集成/server 套件（需测试库）、Alembic 迁移双向、凭据路径
  （图抽取/HyDE/答案生成）、`make docs` 构建、生成页三件套、Windows 占位文件属性位
  （CI 不可验，仅本地验证不构成通过证据）。
- Windows 主机陷阱：无 `make`（用 §3 裸命令）；`docs/cli.md` 禁直接重渲染覆盖（反斜杠）；
  给原生工具传 `C:/...` 前向斜杠路径；bash `$TMPDIR` 可能指向原生 Python 解释不了的 `/tmp`。

## 8. 文档索引

| 文件 | 用途 |
| :--- | :--- |
| `docs/superpowers/specs/设计方案-全PC文件记忆系统-spec.md` | **设计基线 v1.1**（概念 C-1..C-13、存储契约、功能面、验收 A1-A7） |
| `docs/superpowers/specs/设计方案-全PC文件记忆系统-spec审查.md` | 独立审查报告 + 修订记录 |
| `docs/superpowers/specs/reviews/` | 二次审阅记录归档处（§5.2） |
| `AGENTS.md` | 代码级工作契约（改代码前必读） |
| `MIGRATION.md` | 迁移台账：来源、排除、偏差 |
| `docs/adr/` | 架构决策记录（0014 起为本项目新决策） |
| `memory/pcmem_sop.md` | Agent 侧知识库使用 SOP（L3） |
