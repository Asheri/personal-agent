# F6 实现计划：随新文件出现持续更新已有知识

- 日期：2026-10-14
- 状态：设计稿初稿，待评审
- 阶段：P0（清障）加 P1 之后的一处语义改造
- 共享契约：见 `2026-10-14-personal-file-space-program-design.md`（下称程序稿）。
- **不要重复既有设计**：本功能的算法设计已在另一份稿子里定稿并实现，本稿只处理它尚未覆盖的四件事（W1 至 W4），见 §3。
- 组件定位：本稿拥有 `CP-5`（增量面，P0）。上游是源文件与 `DS-1` 的既有行，下游是 `DS-1`，包括 `C-4 版本链` 三列的唯一写入通路。

## 0. 与既有设计的关系

`docs/superpowers/specs/2026-10-08-incremental-reconcile-design.md`（下称 08 稿）已经完整定稿并评审通过，覆盖目标与非目标、方案调研与 PoC 实测、身份与变更判定、图层失效、安全顺序与幂等、测试与 ADR、撤销条件。实现落在 `feature/incremental-reconcile` 分支上，相对 `main` 的差异是 21 个文件、+2319 行。

本稿**不重述**上述内容。08 稿仍然是身份判定与分类算法的唯一权威定义。本稿只处理它没有覆盖、或因本次改造而失效的部分：

| 工作项 | 为何 08 稿没有覆盖 |
|---|---|
| W1 合并清障 | 08 稿写于分支落地前，当时无法预见编号占用与 `AGENTS.md` 冲突 |
| W2 版本链语义改造 | 08 稿把「修改即删旧插新」当作已确认决策写入 §4 与 §5；本改造推翻它 |
| W3 触发方式 | 08 稿把「常驻进程与文件监听」列入非目标，本稿回答「那怎么做到持续更新」 |
| W4 OneDrive 占位文件 | 08 稿假设 `stat` 可靠；仓库本身位于 OneDrive 同步目录 |

## 1. 功能定义与验收标准

**功能**：语料变化后，已有知识随之更新，且重复运行不产生重复文档、不留下已删除文件、不为未变文件付解析与嵌入成本。

| 编号 | 判据 | 判定方式 |
|---|---|---|
| A6-1 | 未变文件零解析 | 记录解析调用次数，第二次运行后断言为 0 |
| A6-2 | 修改文件不产生重复文档，旧内容进入版本链 | 断言文档行数不变、`version_seq` 递增、恰一个 `is_current` |
| A6-3 | 删除文件连同其图证据被清理，构建根之外的文档不受影响 | 复用 08 稿 §6.2 的 fail-closed 删除范围测试 |
| A6-4 | 解析失败时保留旧文档且不推进版本链 | 注入一个损坏文件，断言旧文档仍在、版本号不变 |
| A6-5 | 中断后续跑收敛到与一次性运行相同的状态 | 复用 08 稿 §6.4 的中断自愈测试，并在版本链下重跑 |
| A6-6 | 报告与退出码反映真实分类计数 | 断言各类计数之和等于扫描文件数 |
| A6-7 | 不可追踪的文档被报告而不是被猜测 | 复用 `doctor` 的「reconcile 无法追踪的文档」检查 |
| A6-8 | 无人值守轮询一轮可用 | 按 §3.3 的触发方式跑通一次计划任务 |
| A6-9 | 历史版本不出现在候选或答案中 | 与 F3、F4 共用的对抗性测试 |

## 2. 现状核对

已实现但未合并的部分（以下均在 `feature/incremental-reconcile`，`main` 上没有）：

| 组件 | 落点 | 规模 |
|---|---|---|
| 增量调和 | `src/sci_rag/reconcile.py` | 442 行，两阶段分类：`added`、`unchanged`、`verify`、`removed`、`out_of_scope`、`no_path_recorded`，以及第二阶段解析后裁决的 `metadata_only`、`updated`、`failed` |
| 文件身份与指纹 | `src/sci_rag/ingest/fingerprint.py` | 93 行，`path` 与 `source_fingerprint` 都存 `Document.extra`，因此**零 schema 变更** |
| 接线 | `src/sci_rag/cli/main.py`、`corpus.py`、`ingester.py`、`cli/doctor.py` | `build` 先调和再摄取；`doctor` 报无法追踪的文档 |
| ADR 与文档 | `docs/adr/0012-document-level-reconcile.md` 等 | 含 README、FAQ、CLI 页、spec 修订 |
| 测试 | `tests/integration/test_reconcile_flow.py` 444 行、`tests/unit/test_reconcile.py` 345 行 | 另含 `test_corpus_delete.py` 与 `test_cli_build.py` 的扩充 |

`main` 上的现状是 08 稿 §1 描述的那三条：修改过的文件会留下一条重复文档、删除的文件永远留在库里、未变文件每次全量重解析。

## 3. 工作项

### W1 合并清障

**编号冲突**。两个不同的决策各占用了 `docs/adr/0012`：`main` 上是 `0012-modelscope-deepseek-providers.md`，分支上是 `0012-document-level-reconcile.md`。

按 08 稿自己写下的规则（该稿 218 至 219 行）：谁先落地谁用 0012，后落地顺延为 0013。`main` 的 0012 已落地，且被 `docs/choosing-sci-rag-kit.md:65`、`docs/extend.md:179`、`docs/faq.md:114,147,163` 五处引用，并被 `tests/unit/test_docs_style.py:451-471` 与 `tests/unit/test_docs_shipped_defaults.py:292` 按编号钉死。因此：

1. `0012-modelscope-deepseek-providers.md` 保持不动。
2. 分支的调和 ADR 重命名为 `0013-document-level-reconcile.md`，同时修正它的 `title`、一级标题与正文里的自指编号。
3. 08 稿第 216 行的「新增 `docs/adr/0012-document-level-reconcile.md`」一并改为 0013。不改的话，合并后该稿会与仓库实际文件名互相矛盾。

**`AGENTS.md` 冲突**。`main` 的工作区有一份未提交的 `AGENTS.md` 重写，分支对同一文件有 3 行改动。合并前先提交重写，再以重写后的文本为语义基准去对齐那 3 行，否则冲突解决会以旧版为准，把重写的内容悄悄退回。

### W2 版本链语义改造

按程序稿 §4.3，`updated` 的动作从「删除旧行再摄取新行」改为「旧行降级为历史版本，新行回指旧行」。这是本次改造对既有实现唯一的语义变更。

**必须诚实记录的一笔代价**：分支的一个核心卖点是零 schema 变更（身份与指纹都放在 `extra` JSONB 里）。版本链需要 `version_of`、`version_seq`、`is_current` 三列，这一点就不成立了，`M-0008` 成为必需。程序稿 §4.1 已经解释为什么这三列不能继续用 JSONB：`is_current` 要在五路检索的 SQL 里做条件，`version_of` 需要引用完整性。取舍成立，但代价要写清楚，不能把「零迁移」继续当成这个功能的属性来宣称。

**必须显式 supersede，不得改写历史**。08 稿的 §4 与 §5 把「删旧插新」写作已确认决策，仓库规范不允许改写既有 ADR 与设计稿来让新决策显得本来就存在。因此：

1. 新增一份 ADR 记录版本链决策（建议编号 0014），含 context、decision、consequences、reversal conditions 四节，与仓库既有 ADR 的形状一致。
2. 在 08 稿的 §4 与 §5 各加一条指向新 ADR 的修订说明，写明该节结论已被取代以及取代者是谁。这是修订而不是重写：08 稿的调研、PoC 实测与安全顺序部分继续有效。

三处必须守住的性质（同时写进程序稿 §4.3，此处只列要点）：`version_seq` 单调且不跨文档连链；`failed` 不推进版本链；一次运行里同一文档身份至多产生一个新版本节点。

### W3 触发方式：如何做到「持续更新」

08 稿把常驻进程与文件监听列为非目标，理由是当时用户选择了批量 on-demand。本改造要回答的是：在不引入常驻进程的前提下，「随新文件出现持续更新」是否成立。

**结论是成立，依据是被本次调和设计本身**。调和的第一步是文件指纹比对，命中 `unchanged` 的文件不解析、不嵌入、不算图。因此轮询的边际成本只有一次目录遍历加每文件一次 `stat`。一万个文件在本地磁盘上是亚秒级。既然如此，高频轮询与常驻监听的差别只剩延迟，而代价相差一个数量级的复杂度。

推荐做法：用操作系统的计划任务按固定间隔调用一次构建，不需要任何常驻进程。Windows 上形如：

```
schtasks /create /tn "sci-rag refresh" /sc minute /mo 5 ^
  /tr "cmd /c cd /d <repo> && uv run sci-rag build <corpus_root> >> logs\refresh.log 2>&1"
```

Linux 与 macOS 用等价的 cron 或 launchd。要写进文档的三件事：日志追加而不覆盖；失败退出码要被任务计划记录，否则失败会静默；同一时刻只允许一个实例运行，需要锁文件，否则两次运行撞在一起会同时尝试删除与摄取。

**不做常驻监听**，并记录触发条件：如果实测发现五分钟延迟不可接受，或被索引的目录位于频繁变动的网络位置导致轮询成本失控，再引入监听进程。届时需要新的 ADR 显式推翻这一条，并处理「监听进程崩溃后如何补齐遗漏变更」这个批量方案天然没有的问题。

### W4 OneDrive 与占位文件

仓库本身位于 OneDrive 同步目录，被索引的语料很可能也在其中。Windows 的按需文件在 `stat` 上能返回大小与时间，但读取会触发下载或失败。对本功能的影响有两处：

1. 指纹判定正常，因为 `stat` 可用，所以未变文件仍会被正确跳过。
2. 首次摄取或文件变更时，读取会触发下载。离线状态下这会失败，而失败会被当作解析失败处理，于是旧文档被保留（A6-4 成立），但用户需要知道失败原因是「文件未同步到本地」而不是「文件损坏」。

因此新增一个可分辨的失败原因字符串，并在 `doctor` 的报告里单独计数。同时提供 `--include-placeholders` 与默认跳过两种行为，默认跳过并把跳过的文件数与路径列出。这一项与 F1 的风险项 R1-1 共有，实现放在同一处。

## 4. 数据模型与迁移

沿用程序稿 §4.2 的 `M-0008`，本稿不再新增。

版本链涉及的三列：`version_of`、`version_seq`、`is_current`。回滚时 `is_current` 等效于全真，检索行为与今天一致，因此回滚不需要数据修复，但**已建立的历史版本链会失去表达方式**，因为它们此前只是普通的 `documents` 行。回滚前必须用 `sci-rag corpus snapshot` 记录一次状态，这是回滚可审计的前提。

## 5. 改动文件清单

| 文件 | 改动 |
|---|---|
| `docs/adr/0013-document-level-reconcile.md` | 由分支的 0012 重命名并修正自指编号 |
| `docs/adr/0014-version-chain-*.md` | 新增，记录版本链决策 |
| `docs/superpowers/specs/2026-10-08-incremental-reconcile-design.md` | §4、§5 各加一条指向新 ADR 的修订说明 |
| `src/sci_rag/reconcile.py` | `updated` 分支改为版本链写入 |
| `src/sci_rag/ingest/fingerprint.py` | 占位文件检测；新增失败原因 |
| `src/sci_rag/cli/main.py` | `build` 增加 `--include-placeholders` 与并发锁 |
| `src/sci_rag/cli/doctor.py` | 占位文件跳过数与未同步数 |
| `AGENTS.md` | 与已提交的重写对齐 |
| `docs/` | 一页说明定时刷新的配置与失败可见性 |

## 6. 测试计划

**沿用分支已有测试**：`tests/integration/test_reconcile_flow.py` 与 `tests/unit/test_reconcile.py` 覆盖 08 稿 §7 的测试矩阵，包括中断自愈。这些测试在语义改造后需要按版本链重新断言 `updated` 分支的结果。

**新增单元测试**：

- 版本链写入：连续三次修改，断言链长、单调序号、唯一当前版本。
- `failed` 不推进：解析失败后版本号与 `version_of` 均不变。
- 占位文件：模拟属性位，断言默认跳过并计数、`--include-placeholders` 时报未同步失败。
- 并发锁：第二个实例启动即退出，且不修改数据库。

**新增集成测试**：

- 历史版本隔离：与 F3 的对抗性测试共用，逐路验证向量、关键字、图、社区、HyDE。
- 定时路径的等效性：无人值守跑一轮的结果与手动跑一轮一致。
- 与 F1 联动：邮件宿主文件变更时，其成员文档的增删改收敛。

**必须声明的跳过**：占位文件的行为依赖 Windows 文件属性，在 CI 的 Linux 环境上无法验证，必须显式标注该条只在本地验证过，不得以「测试通过」涵盖。

## 7. 验收命令

```bash
make db-up && uv run sci-rag db upgrade
uv run sci-rag build /path/to/corpus             # 第一次
uv run sci-rag build /path/to/corpus             # 第二次：全部 unchanged
touch /path/to/corpus/a.pdf && uv run sci-rag build /path/to/corpus
uv run sci-rag relate versions <doc_id>          # 版本链
uv run sci-rag doctor                            # 无法追踪、占位文件、未同步计数
uv run pytest tests/unit -q -k "reconcile or version or placeholder"
uv run pytest tests/integration -q -k "reconcile or corpus_delete"
make check
```

## 8. 风险与不做的事

| 编号 | 风险 | 处置 |
|---|---|---|
| R6-1 | 合并冲突以旧版 `AGENTS.md` 为准，重写被悄悄退回 | W1 明确顺序：先提交重写再合并 |
| R6-2 | 改写 08 稿与其 ADR 来掩盖决策变化 | W2 要求新增 ADR 加修订说明，历史文本保留 |
| R6-3 | 「零迁移」被继续当作本功能的卖点 | W2 明确代价；文档与 README 的相关表述同步修改 |
| R6-4 | 轮询实例重叠，两个进程同时删除与摄取 | 锁文件；集成测试覆盖 |
| R6-5 | 占位文件在离线下被当成损坏文件 | 可分辨的失败原因加 `doctor` 分类计数 |
| R6-6 | 定时任务失败无人知晓 | 日志追加加退出码；文档写明如何检查 |

**明确不做的事**：

- 不做常驻文件监听进程。触发条件与代价写在 W3。
- 不做 chunk 级复用。08 稿已把粒度定为文档级。
- 不做 watch 模式下的变更补齐（批量方案天然不需要，引入监听时再解决）。
- 不做跨机器的语料同步，那是同步工具的职责。
- 不改动 scope 规则、融合权重、答案提示词、评测方法与本体。

## 9. 依赖关系

**前置**：无。W1 是全部阶段的前置。

**后置**：F3 的 `C-4 版本链` 与 `C-5 当前版本` 由本稿的 W2 写入；F3 与 F4 的对抗性测试需要版本链先存在；F1 的占位文件处理与本稿 W4 共用实现。

**开放问题**：

1. 轮询间隔的默认值。五分钟是起点，实际取值取决于语料规模与可接受的延迟，需要在真实语料上量一次全量 `stat` 的耗时。
2. 锁文件的实现方式：数据库咨询锁（`pg_advisory_lock`）还是文件锁。前者随数据库连接自动释放，对崩溃更稳健，倾向前者。
3. 版本是否只保留最近 n 版。链无限增长会累积存储与索引成本。倾向先不限制，等真实语料上出现第一个体积问题再定，避免过早丢弃用户的历史。
