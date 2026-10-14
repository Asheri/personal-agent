# 规格评审报告：个人文件空间改造七份设计稿

- 日期：2026-10-14
- 状态：评审完成，待修订。本报告只诊断与提改法，不改设计
- 对象：`2026-10-14-personal-file-space-program-design.md`（下称程序稿）与六份功能稿 F1 至 F6
- 方式：7 名独立审稿人各负责一份稿，全程只读；审稿人之间交叉复核，主审对承重论断做源码级复核
- 证据级别：`[实读]` 行号与内容经实际读取命中；`[报告]` 来自审稿人汇报、主审未逐条复核；`[未验证]` 本轮未验证

## 1. 结论摘要

### 1.1 总判定

| 稿 | P0 | P1 | P2 | 判定 |
|---|---|---|---|---|
| 程序稿 | 3 | 9 | 9 | 不通过，先修 Q-1、Q-3 |
| F1 多格式解析 | 2 | 9 | 5 | 不通过，先修身份多重性 |
| F2 元数据抽取 | 1 | 6 | 7 | 不通过，先定 A2-8 与 schema 的关系 |
| F3 文档关系 | 2 | 11 | 9 | 不通过，版本链两条 P0 与程序稿同批改 |
| F4 检索问答 | 1 | 6 | 7 | 不通过，中文 spike 无判据 |
| F5 空间浏览 | 0 | 7 | 7 | 可放行，但需先补 scope 收口与 MCP 签名 |
| F6 增量更新 | 3 | 10 | 6 | 不通过，与 F3 同批改 |

合计 P0 十二处、P1 五十八处、P2 五十处。P0 去重后收敛为**六个根因**，见 §2。

### 1.2 一处需要正面指出的结构性问题

本轮六份功能稿里有四份（F1、F2、F3、F6）的问题集中在**同一个机制**上：把「一篇文档对应一个源文件、一个源文件对应一行」这条既有不变式，当成了可以局部放宽的实现细节。

- F1 要一个宿主文件产出多篇文档（§3.3）。
- F6 要同一路径保留多行历史版本（§3 W2）。
- F3 要为这些行建立链与边（§3.5）。
- F2 要旧本体抽取出的同名行在新本体下继续共存（§3.2）。

四条需求分别看都合理，合起来则同时撞上三处既有硬约束：`reconcile.build_plan` 的同路径去重（`reconcile.py:234-244` `[实读]`）、`content_hash` 的全局唯一约束（`models.py:92` `[实读]`）、以及 `fingerprint.py` 模块 docstring 明写的 "One path, one document."。**这处不变式必须由程序稿统一改写一次，四份功能稿各自绕行必然互相冲突。** 这是本轮评审最重要的单条结论。

## 2. 六个阻断级根因

### R-1 `is_current` 不是 scope 的一个维度，而是所有阶段的无条件基线

- 位置：程序稿 §4.4（Q-1、Q-2）`[实读]`
- 理由：
  1. `scope_conditions()` 的 docstring 是 "SQL conditions implementing a scope, **for queries joined to documents**"，九条条件全部是 `Document.*`（`retrieve/types.py:83-107` `[实读]`）。它是文档级收口，不是唯一收口。
  2. `is_unrestricted()` 全仓只有三个调用点：`retriever.py:200`、`community.py:29`、`graph.py:202` `[实读]`。`graph.py:202-211` 在它为真时**跳过装载** `eligible_document_ids`，`_WALK_SQL` 用 `:unrestricted OR ... = ANY(:eligible_document_ids)` 短路，`scope_conditions()` 在该路径上根本不被调用。
  3. 按程序稿 §4.4 的极性（`include_superseded` 默认 `False`，只有要求包含历史版本才算非 unrestricted），默认 scope 的 `is_unrestricted()` 恒为 `True`。于是默认查询下 graph 层返回已降级的历史版本 chunk，它们只在 `retriever.py:406` 的 `_resolve()` 被丢掉，即发生在**排序与 limit 之后**。这正是 `types.py` 开头明文禁止的模式（过滤晚于排序会让界外行挤掉合格行）。程序稿 §4.4 自己要求的对抗性测试（有界候选池下历史版本不挤占当前版本）按此设计必然失败。
  4. community 更彻底：默认启用，而 `retriever.py:423-427` 解析社区条目时不带任何 scope 条件。只要社区摘要的证据来自历史版本 chunk，默认查询就会把含历史内容的摘要作为答案证据返回。`community.py` 的模块注释自述 "a scoped caller must never receive a summary partially built from documents outside their scope"。
  5. 连带击穿既有测试：`test_retrieval_scope.py:40-43` 断言 `scope_conditions(RetrievalScope()) == []`，`:47-53` 逐维度断言 `len(scope_conditions(scope)) == 1` `[实读]`。`is_current` 一旦成为默认追加条件，两条断言同时失败。另需注意 `RESTRICTIONS` 是**手工枚举**的列表，漏登记新字段不会报错，只会静默漏测 `[报告]`。
- 改法：
  1. 把 `is_current` 做成所有阶段无条件施加的基线谓词，不再挂在 `is_unrestricted()` 上。`_WALK_SQL` 四处的 `:unrestricted OR ...` 改为再与 `(:include_superseded OR ranked_document.is_current)` 相与；`include_superseded` 单独透传进 SQL，`graph.py:202` 只留给其它维度。
  2. 在 §4.4 明确二选一：社区摘要只由 `is_current=true` 的文档构建；或 `is_current` 过滤开启时社区层整体禁用。不能默认「摘要在含历史、检索在排除历史」。
  3. 改写 `is_unrestricted()` 的 docstring，并在其中注明它**不得**再被用作「可跳过文档过滤」的依据。
  4. 改写两条既有断言（`include_superseded=True` 时才无副作用；`== 1` 改为「该维度条件存在」），并把 `RESTRICTIONS` 的登记要求写进 §4.4 的验收命令。
  5. 在 `kg_communities` 构建阶段同样过滤 `is_current`，写入 §4.4。
  6. 补三条对抗性测试并写进 §4.4 的验收命令：graph 层在有界候选池下不返回 scope 外实体；community 层在任一新增字段生效时被禁用；历史版本经引用边进池时不挤占当前版本。

### R-2 版本链的写入通道不存在，且既有的同路径删除逻辑会在下一轮销毁链

- 位置：程序稿 §4.3 与 C-4（Q-3）、F3 §3.2/§3.5/§3.7（F3-01、F3-02、F3-03）、F6 §3 W2（F6-1）`[实读]`
- 理由：
  1. **写入位置标错**。程序稿把写入逻辑放在 `reconcile.py` 的 `updated` 分支，但 `reconcile.py:316` 明写 "Never ingests -- that is the caller's job." `[实读]`；新行由 `cli/main.py:415-416` 调 `ingest_entries(reconciled.pending, ...)` 创建，而 `pending` 的元素类型 `CorpusEntry`（`manifest.py:33-48`）没有任何版本字段。结果是「新行 `version_of` 回指旧行」在现有接线里无处落笔。这条同时否掉 F3 §3.2 的「只有 `reconcile.py` 与删除通路可写」：真正插行的 ingester 被该规则排除在外。
  2. **删除逻辑与链互斥**。`build_plan` 按 `extra["path"]` 分桶后 `primary, *stale = _newest_first(candidates)`，把每个 `stale` 判 `REMOVED` 并加入 `to_delete`，reason 字面是 "stale duplicate superseded by a newer document for the same path"（`reconcile.py:228-248` `[实读]`）。版本链建立后，第二轮 reconcile 的桶里同时含旧版本行与新版本行，旧行被当陈旧副本删除，**链存在一轮即毁**。
  3. `_newest_first`（`reconcile.py:185-191`）按 `ingested_at` 认链头，与 `is_current` 无关，时钟偏移下会认错。
  4. C-4 的数学形式要求入度 ≤ 1（链非树），而程序稿 §4.2 给的是普通索引 `ix_documents_version_of`，DB 层允许两行指向同一父行。F3 §3.2 自述这类不一致「没有任何测试能事后发现」，正需要 DB 约束兜住。
  5. `is_current` 翻转与后继插入分属两个事务（`reconcile` 先提交，`ingest_entries` 后提交）。ingester 的二次解析失败、嵌入失败、通用异常三处都能留下「旧行已降级、新行未落地」的状态，即该身份零个当前版本，检索看不到这篇文档的任何版本。
- 改法（本节各条经两名审稿人交叉复核后定稿）：
  1. **用包装类型交接，不动 `CorpusEntry`**。`CorpusEntry` 是用户手写 JSONL 的解析模型，版本元数据是 reconcile 运行期派生的；若给它加字段，用户可在 JSONL 手写 `version_of` 绕过单一写入方，manifest 校验也会被迫接受语义上不属于它的字段。定稿为 `Plan.pending: list[PendingIngest]`，`PendingIngest(entry: CorpusEntry, predecessor_id: str | None, version_seq: int | None, is_current: bool)`，`cli/main.py:415-416` 的 `ingest_entries` 改收该类型。
  2. **裁决点上移到 `build_plan`，不在加载处过滤**。曾有一版改法是在 `_load_known_documents` 追加 `is_current.is_(True)`，该改法会造成回归并被撤回：`build_plan` 的删除分支遍历 `by_path[path]` 逐行加入 `to_delete`，而 `delete_documents` 按显式 id 列表删除；加载处一过滤，桶里只剩链头，源文件被删时历史版本会留成永久孤儿（`is_current=false` 且无后继，正是 R-7 描述的坏态）。定稿为：`_load_known_documents` **保持加载全部行**；`KnownDocument` 补 `is_current` 与 `version_seq` 两字段；`_newest_first` 排序键改 `(is_current, ingested_at)` 降序；`:234-244` 的 stale-duplicate 循环加 `if not other.is_current: continue`（前驱保留，只删真重复行）。判据是「`is_current=false` 在本改造里只有一个来源，即被后继取代」，故「同路径 + `is_current=false`」恒等于链上前驱；legacy 真重复行的 `is_current` 都是默认 `true`，行为不变。
  3. 删除分支 `:253-266` 的报告行收敛为「整链删除、只对链头出一行 outcome」，否则加载全链后同一文件会在报告里重复出现。这一改同时解决 F3-06（`removed` 应删整链）。
  4. `updated` 分支删掉 `reconcile.py:372` 的 `to_delete.append(primary.document_id)`，改为「旧行 `is_current=false` + pending 携带 `version_of=旧行 id`、`version_seq=旧行 version_seq+1`」。
  5. 索引沿用程序稿 §4.2 已有名，只改定义为部分唯一索引，避免同一约束两个名字：
     ```sql
     CREATE UNIQUE INDEX ix_documents_version_of
       ON documents (version_of) WHERE version_of IS NOT NULL;
     ```
     并在 §4.3 性质 1 里说明「入度 ≤ 1 由该唯一索引强制，不依赖应用层检查」。
  6. `is_current=false` 与后继插入放进同一事务（在 `ingester` 的 `session_scope()` 内先 flush 新行、再降级前驱）。补测试：在 ingest 前抛异常、在 commit 前中断两条用例，重跑后断言每个身份恰有一个 `is_current`。
  7. §4.3 补一条不变量：同路径多行的唯一合法来源是版本链；F3 §3.2 的写入方规则改为「`reconcile.py` 决定、`ingester.py` 执行」。

### R-3 `content_hash` 的全局唯一约束与版本链、与多成员文件同时互斥

- 位置：F6 §3 W1/§4（F6-2、F6-3）、F1 §3.3（F1-6）`[实读]`
- 理由：
  1. `UniqueConstraint("content_hash", name="uq_documents_content_hash")` 是表级全局约束（`models.py:92` `[实读]`），`ingester` 落库前按它去重（`ingester.py:130-139`）。版本链把旧行留在库里，旧行的哈希就永远占着该值。用户把文件从 A 改到 B 再改回 A（撤销编辑、恢复旧版）时，探针算出 `digest == H_A`，预检命中那条历史版本行，直接返回 `skipped_duplicate`，于是不插新版本，`is_current` 仍停在内容为 B 的那一版，而磁盘上是 A。这是常规操作下的静默错误。
  2. 磁盘上两个不同路径、内容相同的文件（个人空间里复制粘贴极常见），第二份必然走 `skipped_duplicate`，其路径永远不会被写进任何 `extra["path"]`。后果有二：用户看不到第二份文件；下一轮 build 里 `by_path.get(B.path)` 仍为空，B 再次判 `ADDED` 并再次解析。**B 内容从未改变却每轮都被解析一次**，而 F6 的 A6-1「未变文件零解析，第二次运行后断言为 0」是无条件判据，只要语料里有一对同内容文件就必然失败。本稿未提这条限制。
- 改法（二选一或合并）：
  1. 把唯一约束改为仅对当前版本生效的部分唯一索引，并在 `ingester` 的预检上同步加条件：
     ```sql
     ALTER TABLE documents DROP CONSTRAINT uq_documents_content_hash;
     CREATE UNIQUE INDEX uq_documents_content_hash_current
       ON documents (content_hash) WHERE is_current;
     ```
     `ingester.py:130-139` 的 `select(...).where(Document.content_hash == digest)` 追加 `.where(Document.is_current.is_(True))`。
  2. 若要求同内容不同路径各自成文，去重判据须从「按 `content_hash` 查表」升级为「按 `(content_hash, path)` 查表」；若接受折叠，则 A6-1 改为「未变且未被合并的文件零解析」，A6-6 的计数把合并项单列。
  3. 补测试 `test_revert_creates_a_new_current_version`：写入 A、改 B、改回 A，断言行数为 3、`is_current` 恰一个且内容为 A 的那版是当前版本。另补一条同内容不同路径的用例，断言按所选语义给或不给第二行。

### R-4 C-1 文档身份被功能稿二次定义，且违反「同路径即同文档」

- 位置：程序稿 C-1（Q-8）、F1 §3.3（F1-01、F1-02）`[实读]`
- 理由：C-1 定义 `id(d) = canonical_abs_path`、「同路径即同文档」，且程序稿 §4.1 规定「功能稿只要求扩写本节，不得在别处另立定义」。F1 §3.3 把邮件身份改为 `path#<message-id 或序号>` 写进 `extra["source_member"]`，而 `extra["path"]` 仍记宿主路径。即同一路径对应多篇文档，与 C-1 直接矛盾，且 C-1 未登记这条例外。与 R-2 叠加后，一个 mbox 的 N 封邮件会在第二次 build 时被删到只剩最新一封。
- 另外两处连带缺陷（同一开口）：
  1. `probe_content_hash` 只调 `parse_file`（取第一个成员，`reconcile.py:293-305` `[报告]`）。F1 把 `parse_file` 语义改成「返回第一个」后，reconcile 判定宿主是否变化时只看第一封邮件，改动发生在第 2 至 N 封时恒判 `metadata_only`，系统永远不知道。
  2. F1 §5 的改动清单**没有 `reconcile.py`**，等于承认不打算改它。
- 改法（二选一，落进程序稿）：
  - 方案 A（推荐）：C-1 升级为复合身份并回填 §3，`id(d) = (canonical_abs_path(source(d)), member_key(d))`，`member_key` 对单文档文件恒为 `""`；§4.3 性质 3 改为「任一 `(身份, member_key)` 对最多产生一个新版本节点」；`build_plan` 的分桶键改为 `(path, extra.get("source_member"))`；`extra["source_member"]` 登记进 §4.2 的 extra 键清单。`probe_content_hash` 改为按宿主聚合全部成员的哈希：`hashlib.sha256("\n".join(sorted(member_hashes)).encode()).hexdigest()`。
  - 方案 B：多成员文档整体排除在 reconcile 之外，F1 §5 增列 `reconcile.py` 并在 `build_plan` 跳过带 `source_member` 的文档；F1 §8 增一条风险「多成员宿主不参与增量收敛，只能全量重建」；A1-4 的幂等判据相应降级。
  - 无论哪种，都要补一条测试：只改 mbox 里第三封邮件，断言该宿主被判 `UPDATED`。

### R-5 中文检索的 spike 没有成功与失败判据，A4-2 永远无法判定

- 位置：F4 §3.2、§6、A4-2（F4-01）`[实读]`
- 理由：F4 §3.2 只写「在新合成语料上构造一组中文查询，量三个候选的召回与 p95 延迟，再决定」，既无阈值，也没说清五个方案里哪三个要量。§6 又把阈值推给 spike 结论，形成循环：spike 无判据、阈值无来源、A4-2 恒为「未验证」。另外中文改造面被低估了三处：查询侧的 `websearch_to_tsquery("english", query)`（`keyword.py:24` `[实读]`）、`router.py` 的多跳与概览正则全为英文、`domain.py` 用 `re.findall(r"[a-z0-9]+", ...)` 切词（中文查询得到空词集，`classify_query` 恒返回 `None`）。
- 改法：把 §3.2 末尾替换为预注册的阻塞项。
  1. 样本写死 24 条中文查询（专有名词 8、编号与标识符 8、长句 8），随 `data/demo-personal/` 提交。
  2. 指标：对每个候选在同一语料上量 keyword 层的 `hit@20`（针对 8 条标识符查询）与 `p95` 延迟。
  3. 通过判据（可机械判定）：标识符类 `hit@20 >= 0.75` 且 `p95 <= 300 ms` 且不劣于同语料的 `vector_only` 命中。
  4. 决策规则：首选方案通过即选它；不通过则依次测备选；全部不通过则选定保底方案并把 A4-2 标为「已声明降级」。
  5. 产物：`docs/spikes/zh-keyword-spike.md`，含原始命中矩阵，作为 A4-2 的判定证据。
  6. 改造面补齐：`keyword.py` 的 tsquery 配置、`router.py` 的正则、`domain.py` 的切词（或改用 `jieba`），三处一并列进 F4 §5 与 §3.4。

### R-6 A2-8 在现 schema 与现抽取路径下不可能通过

- 位置：F2 §1 A2-8、§4（F2-01）`[实读]`
- 理由：`UniqueConstraint("name", name="uq_kg_entities_name")`（`models.py:207` `[实读]`）使两个同名人物不可能同时存在两行，A2-8 的「两条记录」分支不可满足。同名合并发生在抽取期且无审计（命中既有行即累积 `chunk_ids`），而 `EntityResolutionAudit` 只在 `resolve.py:288-297` 写，且 `resolve.py:87` 只对「同类型不同名或别名重叠」配对分类，同名同型进不了消解流程 `[报告]`。所以 A2-8 的第二分支对真实同名场景恒为假。若要两条记录，必须放宽该唯一约束并引入消歧键，那是一次 `DS-5` 迁移，与 F2 §4「不需要迁移」直接冲突。
- 改法（二选一）：
  - 推荐（改动最小）：A2-8 重写为「同名实体必须被合并，且每次合并留下审计行」，断言 `kg_entities` 只有一行且 `entity_resolution_audit` 存在 `method='exact'` 的收据；F2 §5 的 `extractor.py` 一行改为「在 exact-name 命中分支写一条 `EntityResolutionAudit(method='exact', confidence=1.0)`」；§8 补「不区分同名人物，同名视为同一实体」。
  - 备选：撤回「不需要迁移」，`M-0008` 增 `DROP CONSTRAINT uq_kg_entities_name` 与 `disambiguator` 列加三元唯一约束，并给审计表加 `entity_type`。代价明显更大，需在 §4 写清。

## 3. 应改级问题（P1）

### 3.1 版本链与删除语义

| 编号 | 位置 | 症状与理由 | 改法 |
|---|---|---|---|
| P1-01 | F3 §3.5.2；`corpus delete` 收 `document_ids: list` `[报告]` | 批量删除 `{v2, v3}` 时「提升前驱」会提升到同批已删节点，链既无当前版本又多悬空指向。§3.5.2 只描述单点删除 | §3.5 增第 4 条：先删集合内节点，再对每条受影响链取 `max(chain - deleting, key=version_seq)` 置 `is_current`；链空则不置。测试：一次删 `{v2,v3}` 断言链变 `v1` |
| P1-02 | F3 §3.5.1 | 重连 `version_of` 不改变任何行的 `version_seq`，`v1(1)→v3(3)` 仍有空洞。「序号无空洞」既非机制所能也非验收所需（A3-6 只要求严格递增） | 删掉「序号无空洞」；在 C-4 补「允许因删除中间节点产生的空洞」 |
| P1-03 | F3 §3.5.3；`planner.py:130-135` `[报告]` | 失效判据以「维度」为准，而既有机制以 `embedding_version` 为准。同维度的模型升级会重算 chunk 向量却漏掉 `document_embeddings`，两种向量不同源，A3-1 的排序系统性偏移，而 `plan_reindex` 还会报「已收敛」 | §3.5.3 改为「`document_embeddings` 与 `chunks`、`kg_communities` 同列于 `plan_reindex` 的陈旧条件」；§5 增 `_stale_document_embeddings_condition(version)` 与 `DocumentEmbeddingPlan.stale_documents` |
| P1-04 | 程序稿 §4.3；F3 §3.5.3 | 版本升级后 `document_embeddings.document_id`、`document_citations.citing/cited_document_id`、`kg_entities.document_ids/chunk_ids` 都指向旧行 id，旧行降级后这些派生物在检索侧不可见。本稿未说新版本行何时重建居中向量、引用边与图证据如何迁移 | §4.3 补「派生数据处置」：新版本行摄取完成后重算 `document_embeddings`；引用边与图证据在下次 `graph citations` 与抽取时对当前版本重建；相似查询默认过滤 `is_current` |
| P1-05 | F6 §3 W2；`reconcile.py:156-165` `[报告]` | `updated` 原由「删旧」触发 `graph_evidence_changed`，进而触发 `graph gc` 与社区重建。改成版本链后旧行不删，更新不再触发任何图层失效。历史 chunks 是否参与抽取与社区摘要、旧图证据是否导致摘要过时、`graph_evidence_changed` 是否重定义，三个问题都未回答 | W2 补「版本链与图层失效的对接」并落成三条可断言：历史版本 chunks 保留但在 scope 层排除；`graph_evidence_changed` 与 08 稿的触发图同步改写并写明降级是否触发 gc；补测试断言旧版 chunks 不进五路候选而当前版图证据仍在 |
| P1-06 | F6 §1 A6-5；F3 §3.5.2 | A6-5 只约束终态，未覆盖版本链特有的中断窗口（旧行已降级、新行未落地即崩溃）。F3 §3.5.2 已把该状态标为必须避免 | W2 补第四条不变量：降级与插入同事务，任何时刻同一身份至少一个 `is_current=true`；补测试 `test_interrupt_between_demote_and_insert_leaves_a_current_version` |
| P1-07 | 程序稿 §4.2 与 C-5 | `version_of` 用 `ON DELETE SET NULL`，删除中间节点 B 后 `C.version_of` 置 NULL，而 `A.is_current` 仍 false，A 成为 `is_current=false` 且无后继的孤儿，破坏 C-5 的等价式 | §4.2 该行改为「`ON DELETE SET NULL` 仅作兜底；禁止任何删除绕过 F3 §3.5 的重连逻辑」；新增 doctor 不变式：每个身份 `count(is_current)=1` 且不存在 `is_current=false` 却无后继的行 |
| P1-08 | 程序稿 §4.2.1、§9；F3 §4；F6 §4 | 「回滚后 `is_current` 等效于全 true，不需要数据修复」不成立。`downgrade()` 只删列不删行，同一路径的多行历史全部可见且无字段可再表达当前版本；回滚后一次 build 会把较早行当重复行清理，历史内容丢失。schema 可逆不等于数据可逆 | §4.2.1 改为「schema 层可逆；`downgrade()` 前必须先 `sci-rag corpus snapshot`（命令见 `cli/main.py:1853`）」，并在 `downgrade()` 内先折叠链（保留 `max(version_seq)` 一行、删其余并写审计）；`downgrade()` 的删除顺序补「先删索引、删 `documents` 上的 `project_id` 与 `version_of` 外键、删列、删 `document_embeddings`、删 `projects`」 |
| P1-09 | F3 §3.5.2；`reconcile.py:253-266` | reconcile 的 `removed`（源文件从磁盘消失）与 `corpus delete`（用户主动删一版）语义相反，却共用 `delete_documents`。对 `removed` 套用「提升前驱」会把用户已删的文件用上一版复活，下一轮 reconcile 又判 `removed`，来回震荡 | 落成两个参数：`delete_documents(..., *, reason: Literal["user", "source_removed"])`。`source_removed` 删整链；`user` 按重连与提升处理。删除报告区分两类计数。与 R-2 改法第 3 条一并落地 |

### 3.2 可见性与 scope

| 编号 | 位置 | 症状与理由 | 改法 |
|---|---|---|---|
| P1-10 | F5 §3.3、§3.4、§5 | 分面聚合未绑定 `scope_conditions()`。既有 `list_documents`（`service.py:164-195`）根本不含任何 scope，只校验认证范围。按 §3 与 §5 字面实现，分面计数会绕过权利作用域，泄漏被排除文档的存在与数量，恰是 F5 §6 想防的 | §3.3 增硬约束：`facet_counts()`、`browse_documents()`、`topic_overview()` 的每条聚合 SQL 必须以 `where(*scope_conditions(scope))` 起头，与五路检索共用 `types.py:83` 这一收口；禁止在分面模块另写 where。§6 补「受限 scope 下 facet 计数等于逐文档按同 scope 查询的行数」 |
| P1-11 | F5 §3.2、§3.6、A5-2 | 浏览与分面未声明 `is_current` 过滤。时间分面直读 `documents.doc_date` 直方图，若不走 scope 收口则每个历史版本各贡献一次计数；A5-2「直方图总和等于文档总数」中的「文档总数」是否含历史版本与空日期未定义 | §3.3 与 §3.6 明写「浏览与分面默认 `Document.is_current.is_(True)`」；A5-2 判据写死为「直方图桶之和加空日期桶等于当前版本且在该 scope 内的文档数」 |
| P1-12 | F5 §3.2、§4 | `entity_names`（命名主题允许集）无法用 `scope_conditions()` 的 Document-only 条件表达。要落到文档必须经 `kg_entities → chunk_ids → chunks → documents`，不是任何单个 Document 列；§4 却把它列为元数据过滤一族并要求登记进 `is_unrestricted()`，未给 SQL 形态 | §4 写死条件形态，例如 `EXISTS (SELECT 1 FROM kg_entities e, unnest(e.chunk_ids) c JOIN chunks ch ON ch.id = c WHERE e.name = ANY(:names) AND ch.document_id = documents.id)`，并说明同样由 `scope_conditions()` 产出；否则把它降级为「仅分面、不参与文档过滤」并同步改 §3.2 与 A5-3 |
| P1-13 | F3 §3.6；`service.py:218` `[报告]` | 关系读取面无 scope 参数。`get_citations` 只做双向查边并返回标题，对比 `retrieve` 与 `answer` 都调 `scope_from()`。以 `source=work` 检索时，一条提及边就能经 `get_related_documents` 或 `get_citations` 把公司外文档的标题与存在性泄露出去。F3 §6 的对抗性测试只覆盖检索面，未覆盖读取面 | §3.6 表增一列「scope 语义」：四个入口都接受 `RetrievalScope`，边的两端文档都必须过 `scope_conditions(scope)`；证据 chunk 也须属 in-scope 文档。§6 增「以 `source=A` 为 scope 调三个读取入口，断言 A 外文档的标题、id、数量均不出现」。程序稿 §4.4 同步：读取面与检索面共用同一收口 |
| P1-14 | 程序稿 §4.4；`export.py:148` `[实读]` | 收口清单只列四个调用点，漏了 `export.py`。该处 `scope_conditions(scope) if scope is not None else []`，`scope=None` 时导出含历史版本。F2 §3.3 与 F3 均称导出受 scope 约束 | §4.4 补 `export.py:148`，并声明「导出默认也排除历史版本，除非显式 `include_superseded`」；F3 §8 补「不导出 `document_citations` 与 `document_embeddings`；将来若要导出引用，必须先加『边两端都须过 scope』的过滤」 |
| P1-15 | F4 §4.3；程序稿 C-11；F5 A5-5 | `date_min`/`date_max` 对 `doc_date IS NULL` 的文档语义未定义。既有范围过滤写法是 `Document.publication_year >= scope.year_min`（`types.py:92-95` `[实读]`），照抄则 NULL 比较得 NULL、行被丢弃，即无日期文档在任一时间过滤下被静默排除，与 F5 A5-5 的取向相反。仓库已有 NULL 容错先例可照搬：`exclude_dois` 那条写的是 `or_(Document.doi.is_(None), Document.doi.not_in(...))` `[实读]` | §4.3 写死二选一并在 §6 补断言。推荐保留：`or_(Document.doc_date.is_(None), Document.doc_date >= date_min)`。§6 的「全空落 NULL」改述为「四来源全空时落 NULL，仅发生于迁移前旧行或取不到 `ingested_at` 的行」 |

### 3.3 契约与字段

| 编号 | 位置 | 症状与理由 | 改法 |
|---|---|---|---|
| P1-16 | 程序稿 §4.4；F4 §4.3/§5；F5 §4/§5 | 本轮新增 `RetrievalScope` 字段散在三份稿里，无单一登记处：程序稿只登记 `include_superseded`，F4 加 `date_min`/`date_max`，F5 加 `projects`、`tags`、`auto_tags`、`entity_names`（§4 表格实为 6 个字段名，正文却写「这五个字段」）。两稿都声称与对方「共用同一组字段，不重复定义」，又都把 `retrieve/types.py` 列进自己的改动清单 | 程序稿 §4.4 增「本轮新增 scope 字段总表」（`include_superseded`、`date_min`、`date_max`、`projects`、`tags`、`auto_tags`、`entity_names`），逐字段标注属权利族还是元数据族（F5 §3.1 的语义区分必须逐字段标），并规定「任何功能稿只引用本表，不得在别处另立字段」；`tests/unit/test_retrieval_scope.py` 一次性登记全部；修正 F5 §4 的计数表述 |
| P1-17 | 程序稿 §4.2；F5 §3.2/§3.7/§7 | `projects` 表只写「`id`（pk）、`name`（唯一）、`slug`（唯一）、`description`、`created_at`、`updated_at`」，未给类型与生成规则。`documents.project_id` 声明为 `text` 外键，故 `projects.id` 必须同为 `text`。F5 用 `--project <slug>` 过滤、§3.7 却写「非法的项目名返回 404」、§3.2 的过滤字段又叫 `projects`，三处各指一种标识；改名时 `slug` 是否变、URL 是否失效都未定义 | §4.2 补全类型与生成规则，明确 `projects.id` 复用 `sci_rag.db.models.new_id()`、`slug` 由 `slugify(name)` 生成并在冲突时追加序号；写死「`id` 是稳定标识（用于 URL 与过滤参数），`slug` 是人读别名，可随 `name` 改名而变」。F5 据此统一三处：§3.2 注明值域、§7 改为 `--project <id>` 或声明同时接受 id 与 slug、§3.7 改为「未知项目标识返回 `404 project_not_found`」 |
| P1-18 | F3 §3.4；`citations.py:110` `[报告]` | 既有对账把现有行索引成 `{(citing_document_id, cited_doi): row}`。mention 行的 `cited_doi` 为 NULL，于是同一 citing 文档的所有 mention 边塌缩成同一个键 `(doc, None)`，`rows_written` 与 `rows_removed` 会算错并可能删掉刚建的边。DB 侧的 `uq_document_citations_reference` 含 `cited_doi`，对 NULL 不生效，无法兜底 | §3.4 明确 mention 通路换键：对账键用 `(citing_document_id, cited_document_id)`，`existing` 查询按 `source == detector` 过滤。程序稿 §4.2 增 `CREATE UNIQUE INDEX uq_document_citations_mention ON document_citations (citing_document_id, cited_document_id) WHERE source = 'mention';`。测试：同一 citing 文档 3 条 mention 边跑两轮重建，断言 `rows_written=0` 且 `rows_removed=0`、表内仍 3 行 |
| P1-19 | `models.py:167-169`；F3 §3.4 | `uq_document_citations_pair (citing_document_id, cited_document_id)` 不含 `source`。学术文档 A 既在 Crossref 引用 B、正文又出现 B 的标题时，两条边 `(A,B)` 相同，第二条插入抛 `IntegrityError`，整轮 `graph citations --apply` 失败。F3 §3.4 未规定两个检测器的优先级 | §3.4 二选一：在候选阶段跳过已存在 crossref 边的 `(A,B)`（C-9 判据加前置条件「且不存在 crossref 边」，推荐，因为它让「既有实现不动」这句成立）；或写入用 `ON CONFLICT ... DO NOTHING` 并规定 crossref 优先。补测试：同时具备 DOI 引用与标题提及的文档，断言表内该对只有一行且 `source='crossref'` |
| P1-20 | F3 §3.4 | 提及引用同名不同文档（两个 `report_2024.pdf`）无消歧规则。C-9 的键集合是标题与文件名主干，命中可能多目标；程序稿的 CHECK 要求 mention 行 `cited_document_id IS NOT NULL`，却未定义多目标时取哪一个 | §3.4 增消歧规则二选一。保守（推荐）：命中多个候选即判歧义、不计边、计入 `unmatched`，理由是个人空间里同名文件常见、误连代价高于漏连。激进：对每个候选各建一条边并把 `confidence` 除以候选数，且要求两个不同键同时命中。配单测 |
| P1-21 | 程序稿 §4.2.1、§4.2 索引清单 | 判据「参与过滤、排序或唯一性约束的信息用列」不可机械应用且有反例：`project_source` 不参与任何 DB 过滤或排序或唯一约束（只在应用层表达 F2 A2-5），按判据应是 JSONB 却被定为列；`doc_date_source` 被 F4 明说可能用于筛选，按判据需列且需索引，而索引清单只有 `ix_documents_doc_date`，缺 `ix_documents_doc_date_source` | 判据拆两级：「过滤、排序、唯一 → 列加索引；承载应用不变式或审计但不进 SQL 谓词 → 列不索引；纯描述 → JSONB」。据此补 `ix_documents_doc_date_source`，或删掉 F4 §4.2「可能被用来筛」的措辞以保持自洽 |
| P1-22 | F2 §4.1 与 §5 | §4 说「本稿不使用迁移」，§5 却列 `migrations/versions/0008_*.py`。两处不是矛盾而是措辞含混，但按程序稿 §4.2.1 判据，`source_member` 一旦参与身份唯一性就应当考虑用列，而 F1 §4 断言这些键「不需要被索引或参与过滤」，与 R-4 的方案 A 冲突 | F1 §4 增一句决策：`extra["source_member"]` 仅由应用层在内存中作分组键，不建索引、不参与 SQL 过滤；若团队不接受，则在 `M-0008` 加 `source_member text NULL` 并建唯一索引。F2 §4 的「不使用迁移」改为「本稿不新增独立迁移，两列随 `M-0008` 落地」 |

### 3.4 判据可判定性

| 编号 | 位置 | 症状与理由 | 改法 |
|---|---|---|---|
| P1-23 | F1 §1 A1-5、§5 | A1-5 要求 `doctor` 报「每类文件的成功数与失败数」，但 `doctor` 是纯环境检查，只统计库里的行数；解析失败不落库，`IngestOutcome(status="failed")` 只活在 `IngestReport` 里，命令结束即消失。没有持久化就没有失败数可读 | 推荐第三种：A1-5 改为「`ingest` 的 stdout 汇总加退出码」：新增 `sci-rag ingest --strict-format-report` 打印 `parser=x ok=n failed=m` 表，`m>0` 时退出码 1，A1-5 断言该表与退出码。另两种备选是落盘 `data/last-ingest.json` 或新增 `documents` 之外的载体 |
| P1-24 | F1 §1 A1-3、§3.5、§9.1 | A1-3 的判据是「chunk 字符数大于阈值且 `extra["ocr"]["engine"]` 有值」，§3.5 触发扫描版判定的条件也依赖「低于每页阈值」，而两个阈值在本稿中都没有数值，选阈值又必须先知道引擎的产出量。以依赖未定量的阈值作验收判据，等于把验收标准一并推迟 | 拆成机制项与效果项：A1-3a（现在可判定）对固定样张注入假引擎，断言 `extra["ocr"]["engine"]=="fake"`、`pages==1`、该文档 `chunks` 行数大于 0；A1-3b（spike 回填）由 spike 给出引擎的准确率 p 与单页耗时 t，写成「产出不少于 ⌈p·N⌉ 字符、单页耗时不超过 t·2」。§3.5 补一句「Docling 未安装时扫描版判定退化为只依据 pypdf 的每页字符数」 |
| P1-25 | F2 §1 A2-1、A2-7 | A2-1 依赖 `doctor` 打印本体类型清单，而现状只打印计数；A2-7 要求「丢弃计入报告」，但 `ExtractionStats` 无丢弃计数，改动清单也未加 | §5 明确 `doctor` 改动为「逐条打印 `entity_type` 名称」；`extractor.py` 的统计对象增丢弃计数字段，并在 §6 断言注入未知类型后计数加一 |
| P1-26 | F3 §1 A3-2、A3-9 | A3-2 的判定写「公告邻居变化」，「公告」不是断言；A3-9 要求四类关系都能回答「谁建的边、依据是什么」，但相似不存边、项目是单值列，二者没有建边方 | A3-2 改为「摄取新文档后 `relate similar` 的返回集合含该文档，且过程中未调用 `embed reindex`（用调用记录断言）」；A3-9 拆成四条各自可断言的子项 |
| P1-27 | F6 §1 A6-2、A6-6 | A6-2 写「断言文档行数不变」，而版本链每更新一次必然多一行历史，判据在保留历史的世界里不可能成立。A6-6 写「各类计数之和等于扫描文件数」，而 `ReconcileReport.counts` 累加的是全部 outcomes，其中 `REMOVED`、`OUT_OF_SCOPE`、`NO_PATH_RECORDED` 来自库侧行，计数之和严格大于扫描文件数 | A6-2 改为「`is_current=true` 的行数不变、`version_seq` 严格递增、`version_of` 指向同身份上一版、恰一个 `is_current`、`documents` 总行数加一」；A6-6 拆成源侧计数与库侧计数两条独立断言 |
| P1-28 | F4 §1 A4-1 | 判定写「有候选或有非 success 的轨迹状态」。`StageTrace.status` 取值域含 `empty`，而关键字层在中文语料上恰是「跑赢但零候选」即 `empty`，会自动通过 A4-1，把本稿自己认定的最大缺口判成通过 | A4-1 改为机械断言：`trace.status == "success"` 且 `candidate_count > 0`，或状态属 `timeout`、`error`、`disabled`、`skipped` 且在文档中显式声明降级；`empty` 一律判失败 |
| P1-29 | F6 §7、§5 | 验收命令引用 `sci-rag relate versions`，该命令属 F3（P3），main 与分支都没有 `relate` 命令组也没有 `src/sci_rag/relate/`，F6 的改动清单也不含它。F6 完成时这条命令必不可跑，且未声明面板归属 | §7 改为本稿当下可跑的断言（版本链不变量由 §6 的测试承担），并把「A6-2 的端到端验收需要 F3 的 `relate versions`」写成 §9 的显式前置依赖 |
| P1-30 | F4 §7 | pytest 选择器选不到支撑 A4-6 的既有对抗性测试。`tests/integration/test_metadata_filters.py` 里的 `test_metadata_scope_disables_the_community_layer` 与 `test_year_range_filters_inside_each_layer` 既不含 `retrieve` 也不含 `answer` 或 `demo`；§7 也没有日期命令，A4-9 无命令可跑 | §7 改为精确目标：`pytest tests/unit/test_retrieval_scope.py -q` 与 `pytest tests/integration/test_metadata_filters.py tests/integration/test_offline_answer_boundary.py -q`；补 `retrieve ... --date-min/--date-max` 与 `make benchmark-check` |

### 3.5 本体换代的真实成本

| 编号 | 位置 | 症状与理由 | 改法 |
|---|---|---|---|
| P1-31 | F2 §4、§2、R2-4 | §4 以「schema 不改」为唯一迁移理由，只讨论新取值可写，未讨论旧取值清理。旧 `kg_entities`、`kg_relationships`、`kg_communities`、`entity_resolution_audit` 全部留库无重建路径。更严重的是 `name` 全局唯一：新本体下重抽的旧名词条命中既有行且类型不同时会直接丢弃该实体，即「不迁移」不是中性的，旧行会主动吞掉新抽取结果 | §4 增一小节「本体换代的重建路径」，写死命令与前置：`graph gc --apply`、`graph extract --all`（必须而非可选，理由引 `extractor.py:193-194` 只处理未盖章 chunk）、`graph resolve-entities --apply`、`graph communities` |
| P1-32 | F2 R2-4 | R2-4 的量化处置不完整。`Makefile:136` 把 graph replay 文件名钉死，`scripts/graph_replay.py` 校验 `domain_digest` 与 `extractor_contract_version`，不匹配即 fail closed，换本体必改 digest，`make benchmark-check` 会失败。另有多处测试夹具写死农业本体，换本体后大面积失败 | R2-4 的处置改为四条可勾选项：重录 `data/demo/graph-replay/` 并更新 Makefile 的哈希文件名与 receipt；更新写死本体的测试夹具；对已抽取语料执行 `graph extract --all`；重跑 `graph communities` |
| P1-33 | F2 §4 | 本体无版本戳。`KgEntity` 无本体版本列，换本体后无法区分新旧本体行；`EntityResolutionAudit` 只存名字与 id，换本体后收据会指向语义已变的实体。仓库已有现成的 `domain_digest` 机制可复用 | 最省（不改 `DS-5`）：§4 写死「换本体等于对 `DS-5` 三表清空重建」，并在抽取统计里打印当前 `domain_digest`。长期可查询：`M-0008` 增 `kg_meta(domain_digest, ontology_version, applied_at)`，或给审计表加 `entity_type` |

### 3.6 结构完整性与出口

| 编号 | 位置 | 症状与理由 | 改法 |
|---|---|---|---|
| P1-34 | 程序稿全稿 | §5 把「验收命令」与「不做的事」定为每份功能稿的必备节，承载 `M-0008` 的程序稿自己没有，P0 与 P1 因此没有放行门槛 | 新增两节。验收命令至少含：`alembic upgrade head` 后断言新列、两张表、HNSW 索引存在；`alembic downgrade -1` 在一次性库上断言 schema 还原与链折叠；`pytest tests/unit/test_retrieval_scope.py` 全绿；§4.4 对抗性测试的具体命令；断言 `count(is_current) == count(documents)`。不做的事至少写：本轮不引入 `document_projects`；不把 `project_source` 与 `version_seq` 提升为可过滤维度；不改 `DS-5` 三张图表结构 |
| P1-35 | F1 §5 | 改动文件清单缺六类必改文件：`reconcile.py`（见 R-2/R-4）、`ingest/fingerprint.py`（R1-1 自己要求的占位检测落点）、`cli/doctor.py`（`doctor` 实现在此，§5 却写 `cli/main.py`）、`.github/workflows/ci.yml`（决定 CI 装 `office` 却未列该 sync 行）、`draft/sampling.py` 与 `draft/manifest.py`、以及被钉死的文档串（README、`docs/cli.md`、`docs/faq.md`、`docs/index.md`、`cli/main.py` 的 help 串，改后须重跑 `make docs-reference`，否则 `make docs` 的 `--check` 失败） | §5 补齐上述各行；docs 行改为「更新四处格式枚举；重跑 `make docs-reference` 同步 `docs/cli.md`；新后缀写入 `bring-your-own-domain.md`」 |
| P1-36 | F1 §3.2/§3.6；`draft/sampling.py:107-131`、`draft/manifest.py:100-109` `[报告]` | 两处都消费 `SUPPORTED_SUFFIXES` 后直接 `parse_file`，白名单扩容会静默把图片与邮件塞进 `sci-rag draft` 的采样面；而 §3.6 把 OCR 引擎缺失定为失败（不静默跳过），于是语料里只要有一张截图，`sci-rag draft manifest --folder` 就整体抛 `DraftError` 退出 | §5 增列这两处；把解析失败从 `raise DraftError` 改为「记一条跳过并继续」，或显式限定 draft 只用原六种后缀（`DRAFT_SUFFIXES`）；在 §8 落一条「draft 采样面是否随 ingest 白名单扩张」的决策 |
| P1-37 | F5 §3.4、§5 | §3.4 定义四个服务方法，§5 只在 MCP 那行写两个工具**名字**，无参数、无返回、无 docstring，也没说明两个工具如何覆盖四个方法。REST 侧只落一个端点，`list_projects` 与 `topic_overview` 无对应端点。§8 又宣称「MCP 让本机 agent 直接当浏览界面」，无签名落不了地 | §5 补签名，例如 `browse_corpus(dimension, by=None, filters=None) -> dict` 与 `list_projects() -> {...}`，并二选一写死 `topic_overview` 的 REST 承载（`/v1/corpus/facets?include=topics` 或新增 `GET /v1/corpus/topics`） |
| P1-38 | F6 §3 W4；F1 §8 R1-1 | 两稿都声明这一项「共有」，都把实现放在同一处，却给出**相反的结论**。F1 说占位文件会让指纹「误判为未变」，处置是「显式跳过并计数，不静默当成未变」；F6 说「指纹判定正常，未变文件仍会被正确跳过」，处置是「照读、失败则记新原因」。两稿都没写谁是单一负责方，失败原因字符串也各定义一套，合并后会撞同一个 `detail` 词表 | 在 F6 §3 W4 指定所有权并统一结论：占位文件的检测与失败原因由 F1 独占定义（属性位判定加统一的原因字符串枚举）；F6 只做两件事，即在 `failed` 分支识别并透传 F1 的新原因、`doctor` 增加对应计数。两稿的 R1-1 与 R6-5 改成同一条文本 |
| P1-39 | F6 §2、§3 W4；`reconcile.py:72-81` | 被跳过的占位文件既不是 `added` 也不是 `unchanged`，九项分类里没有它的位置；`STATUSES` 是硬编码元组，输出的表与计数都按它遍历，新增一类必须同时改三处。F6 只写「列出文件数与路径」，未说是哪个状态、是否算进计数 | §2 分类表加第 10 项（如 `placeholder_skipped`），写明属 Phase A 可判定、进 `STATUSES`、参与源侧计数、`doctor` 单列；§5 与 §6 补上 `reconcile.py` 的 `STATUSES`、`cli/main.py` 的行色表、`test_report_counts_every_status` 三处必改点 |
| P1-40 | F2 §5 | 新增 `project` 命令组（`assign`、`list`、`rules check`）未声明 `rich_help_panel` 归属。程序稿 §5 与仓库规范都要求每个新命令落在六个面板之一并给一行 help | §5 该行补面板归属（建议 `Build your knowledge base`），并给三条一行 help |
| P1-41 | F6 §3 W2、§5 | W2 的 supersede 定位只点名 08 稿的 §4 与 §5，而 08 稿把「删旧插新」在至少五处重复声明：§1 的非目标「不改 schema 不加迁移」、§3 的「不改 schema 因此不需要新迁移」、§4 的「`content_hash` 唯一约束保持不变」、§6.1 的逐文件顺序、§8 的决策汇总。合并后 08 稿会自相矛盾 | §5 那一行改为逐条点名（含头部与 §8 的决策汇总），并在 W2 里给一张「08 稿受影响位置与新结论」的两列表，作为可机械核对的清单 |
| P1-42 | F6 §8 | §8 写「不改动 scope 规则」，而 C-5 的可见性只能靠程序稿 §4.4 的 scope 收口实现，程序稿白纸黑字写着「这是一次 scope 规则变更」。F3 §8 也把该过滤归给 `CP-6` | §8 改为「不改动 scope 规则的其余部分（融合权重、答案提示词、评测方法、本体）；`C-5` 的过滤属程序稿 §4.4 的既定变更，本稿只负责写入 `is_current`」；§9 补「A6-9 须等 `CP-6` 落地才可验收」 |
| P1-43 | F2 与 F5 | 概念 `C-10 主题` 的归属两稿不一致。F2 §3.1 说命名主题对应 `KgEntity`、主题簇对应 `C-10`；F5 §3.2 却把「`C-10` 的第一层」给命名主题、「`C-10` 的第二层」给主题簇。程序稿的 C-10 只定义簇 | 统一为「`C-10` 仅指主题簇；命名主题不占用 C 编号，或另立 `C-12`」，并同步修正 F2 §3.1 与 F5 §3.2 的表述 |

### 3.7 未登记的风险与遗漏

| 编号 | 位置 | 症状与理由 | 改法 |
|---|---|---|---|
| P1-44 | F1 §8 | 风险表四条无一条涉及隐私。产品定位是个人文件空间，而本稿新增的两大来源恰是最敏感的：邮件正文与 Office 正文。落库后分块存原文、送嵌入模型，后续图抽取会把分块送到 LLM 提供方 | §8 增一行：经文件夹发现的邮件与 Office 文件默认 `source="local"`、`license_class="unknown"`，并声明该许可类的文档是否进入图抽取的 LLM 调用；`doctor` 增加一行「N 篇文档的正文会送外部模型」 |
| P1-45 | 程序稿 §8 | 风险表遗漏四类：向量双写与维度漂移（`0007` 的 `_VECTOR_COLUMNS` 硬编码两张表，新增第三张向量表后未来维度变更会漏掉它）；旧语料版本字段回填（只提无路径行保持 NULL，未提有路径行的回填及其对首次 reconcile 的影响）；中文关键字硬编码（`models.py:124-127` 与 `keyword.py:24` 两处 `english`，是 F4 的阻断项，却只登记了「英文提示词不适合中文」）；迁移中断 | 新增三条：向量维度漂移（处置：`_VECTOR_COLUMNS` 扩为三表，`embed reindex` 同时失效两者，配三列 `format_type` 一致的断言）；旧语料版本字段回填（处置：`server_default` 保证，验收断言 `count(is_current) == count(documents)`）；中文语料关键字层无候选（处置：指向 F4 §3.2 的 spike，并声明该层对中文的降级必须在交付说明里显式声明） |
| P1-46 | F4 §3.5 | 把受 `is_unrestricted()` 约束的层写成了「HyDE 与 community」，实际是 community 与 graph。源码中 `graph.py:202` 同样消费该函数并把布尔绑入 `_WALK_SQL`，是比 community 更隐蔽的第二条泄漏路径；HyDE 不 gate，它只经 `vector_stage` 做行级过滤，也不该被禁用 | §3.5 改为「`community` 层与 `graph` 层都消费 `is_unrestricted()`；`HyDE` 不 gate」。§6 补一条「graph 层在有界候选池下不得返回 scope 外实体」 |
| P1-47 | F4 §3.4、§5 | 引用的本地化通路与仓库真实机制不符。`domain/prompts/prompt_localization.md` 开篇写明是「领域用词改写」，不是语言本地化；驱动 `draft/prompts.py` 的 `EDITABLE_PROMPTS` 只含 `entity_extraction` 与 `answer`，且 `snippet_compression` 在 `REFUSED_PROMPTS` 里被明文拒绝，理由是「压缩决定哪些证据能到达答案，它的措辞是实验条件」，改它会抛错 | §3.4 改为：中文路线是新建一个中文 `domain/` 目录（中文 `domain.yaml` 加手写中文提示词，用 `SCI_RAG_DOMAIN_DIR` 切换），不走 `sci-rag draft prompts`；压缩提示词与裁判提示词改为手写中文版，并说明压缩提示词的中文化必须重跑成对闸门。§5 把「`answer.md` 等」替换为逐一列名 |
| P1-48 | F2 §3.7 | 推断失败时「`project_source` 落 `inferred` 但不写 `project_id`」，会覆盖由目录规则派生的 `rule` 行（变成 `project_id='X'` 加 `project_source='inferred'`），破坏「人工 > 规则 > 推断」不变式 | 改为「推断失败或置信度缺失时不改动原有 `project_id` 与 `project_source`，只在报告里计一次失败；仅当推断确实产出项目时才写 `project_source='inferred'` 与置信度」。§6 补断言：先规则指派、再跑空推断，断言两者不变 |
| P1-49 | F2 §3.4、§5、§9 | 「规则层」没有可实现的定义：§3.4 只举一个路径通配例子，§5 新增规则文件但未给 schema，验收命令要求「无冲突」却没定义冲突，§9 还把 glob 与正则的选择留作开放问题。没有这层定义，`project_source='rule'` 的写入逻辑与 A2-4 的第二个用例无从实现 | §3.4 补规则文件的确定形态（有序列表、先匹配先赢、含 `project`、`include`、`exclude`、`priority` 四字段），写明匹配对象是 `C-1 文档身份`、路径按平台归一化、`check` 把「同一路径命中多个不同 project」报为冲突；§9 开放问题收口为「只做 glob，不支持正则」 |
| P1-50 | F3 §3.8 与程序稿 §4.1 | 程序稿 §4.1 把多对多项目的升级条件外包给「F3 §8」，而 F3 §8 只有通用边表与物化视图的触发条件，没有多项目这一条。全仓 `document_projects` 只出现一次（在程序稿 §4.1） | F3 §8 补一行「多对多项目：当确认一篇文档需同时属于多个项目时，引入 `document_projects(document_id, project_id, source)` 并把 `documents.project_id` 降级为主项目；触发条件是用户显式指派第二个项目，或目录规则命中多个项目且无法判定主项目」。或把该条写进程序稿 §4.1 自身并去掉指针 |
| P1-51 | F2 §3.3、§1 A2-3 | §3.3 与 R2-3 引「F3 的导出规则」，而 F3 通篇无导出内容；导出契约实际在仓库规范与 `sci-rag corpus export` 的 scope 条款里。A2-3 要求「各有来源记录」，但 `documents.authors` 是普通列，`extra` 只装解析器名与摄取时间，没有来源列可断言 | §3.3 改为引导出命令的 scope 条款，并补「实体仅当其来源文档全部在 scope 内才导出」「社区与主题簇不导出」；A2-3 的判定改为断言 `extra` 新增来源键，或删掉该半句 |
| P1-52 | F5 §3.2、§3.3 | 分面维度硬编码。§3.2 的八行表即维度集合的事实定义，§3.3 未说明端点是遍历一张注册表还是逐维度手写 SQL，新增第九个维度的代价未交代 | §3.3 增「分面维度由声明式清单驱动，`facet_counts()` 遍历生成查询；新增维度等于清单加一行（无索引时补同级迁移）」，并列出「按解析器浏览」的代价（需把 `extra["parser"]` 提升为列，与程序稿 §4.2.1 判据冲突，故本阶段不做） |
| P1-53 | F5 §3.6 | §3.6 把已上线端点 `/v1/documents` 的排序由 `ingested_at desc, id` 改为 `doc_date desc nulls last, ingested_at desc, id`，会改变现有调用方的翻页预期，却当作实现细节一笔带过，且现有契约测试不钉排序，改后不会报错 | §3.6 补「这是对既有响应顺序的行为变更；自有 fork 可直接改，但需在 `docs/api.md` 记明并加契约测试钉住 `doc_date desc nulls last`」 |
| P1-54 | F6 §3 W3 | §3 声称「本稿只处理尚未覆盖的三件事」，而 §0 与 §3 实际有四项（W1 至 W4）。这是可机械判定的内部不一致 | 头部改为「四件事（W1 至 W4）」。**本轮已修正** |
| P1-55 | 程序稿 §6 与 F6 头部 | CP-5 的阶段标为 P0，而 §2 的 P0 只含「合并 F6 分支」，版本链写入依赖 `M-0008`（P1），F6 头部自写「P0 加 P1 之后的一处语义改造」。CP-5 实际横跨 P0 与 P1 | §6 的 CP-5 阶段列改为「P0（合并）+ P1（版本链写入）」 |
| P1-56 | F6 §1 A6-9、§1 | 本稿只声明拥有 `CP-5`，而 A6-9（历史版本不出现在候选或答案）的实现落点是 `CP-6`，不在本稿组件范围内，判据与归属不匹配 | A6-9 的判定方式补注「实现归 `CP-6` 与程序稿 §4.4；本稿只保证写入的 `is_current` 正确」 |

## 4. 可选优化（P2）

按稿归类，每条给出定位与要点。

**程序稿**

| 位置 | 要点 |
|---|---|
| §1 | REST 端点数写错（6 应作 7）。**本轮已修正** |
| C-3 | 唯一约束行号 78 应作 92。**本轮已修正** |
| §4.4 | `is_unrestricted()` 只写 `types.py:61-80`，未指出开关在 `retriever.py:200` 与 `community.py:29` |
| §4.2 | `document_citations` 唯一约束与 `cited_doi` 改可空的交互未说明：mention 边的幂等实际靠 `uq_pair`，`uq_reference` 对 NULL 不生效；若允许同一对被两检测器各建一条边，需把 `uq_pair` 改为含 `source` 的三元组 |
| §4.2.1 | `downgrade()` 删除顺序未含外键 |
| §9 | 第三条撤销条件不可机械判定（「准确率低到成为唯一可用来源」无阈值），建议改为可判定阈值 |

**F1**

| 位置 | 要点 |
|---|---|
| §2 | 五处行号偏差（`parsers.py` 四处、pre-commit 一处）；`parsers.py:54`、`manifest.py:78-79`、`ingester.py:123`、`architecture.md:165` 均正确，600 KB 阈值正确 |
| §6 | 对抗性测试里的「超长单行 CSV」不在本稿格式集合内（悬空测试对象），换成 `.txt` 或补 `.csv` |
| §5 | `ocr.py` 写「两个适配器」而 §9.1 列三个候选，数字悬空 |
| §3.3 | 邮件序号的规则未定义（从 1 起？全局还是每次解析？删中间一封后序号是否迁移？），身份稳定性因此不可判 |
| §4 | 新 `extra` 键没有写入通路：`ingester` 只搬 `metadata["parser"]` 一个键，需明确「解析器只往 `metadata` 写、`ingester` 透传」 |
| §4 | `extra["parser"]` 的「取值扩充为」措辞丢失既有取值 `text`/`html`/`pypdf`/`docling`；`ocr` 一个值同时表示扫描版 PDF 与图片，A1-5 的分类无法区分二者 |
| §8 | 「不做的事」缺邮件附件、邮件线程、图片后缀集合三项 |

**F2**

| 位置 | 要点 |
|---|---|
| §4.1 | `auto_tags` 的分列理由是「信任级别」，不符合程序稿 §4.2.1 的过滤与排序与唯一性判据，需改理由或请程序稿扩判据 |
| §3.2 | `Document` 作为实体类型与 C-1 的文档身份同名异物（前者指正文里被提到的他人文档，后者指本库的一行），未像「主题」那样消歧 |
| §3.3、R2-3 | 隐私规则只覆盖人名，未覆盖同为本体的机构、项目、地点 |
| §6 | 单元与集成测试未列幂等重跑时 `auto_tags` 不重复的断言细节；未列单文档与全空桶用例 |

**F3**

| 位置 | 要点 |
|---|---|
| §3.4 | `CitationBuildReport` 字段列表漏 `self_citations_skipped` 与 `dry_run`，而自引用排除恰是新通路要实现的规则 |
| §5 | `relate/` 包结构缺「项目」模块，而 §3.6 要求 `relate projects` 命令 |
| §3.5 | 未声明链长 1 的删除行为；未声明同一内容换路径（重命名或移动）按 C-1 会产生新身份与新链、版本连续性不跨路径 |
| §6 | 对抗性测试缺两条具名用例：历史版本经引用边进候选池；读取面的 scope（与 P1-13 呼应） |
| §8 | 新增第三种引用检测器需要改 CHECK 约束，属 schema 变更，未声明这一代价 |
| §5、§9 | 「见 F5 §5 的统一决定」引用错位（决定在 F5 §3.5）；§9 开放问题 3 已被 F5 关闭却仍列为未决 |
| §9 | F2 声称 F3 的相似度用实体 `document_ids` 收敛候选集，而本稿 §3.3 是查询期在居中向量上做近邻检索，无实体收敛。两稿择一 |

**F4**

| 位置 | 要点 |
|---|---|
| §8 | 开放问题 3 的「另留更大语料供 `make benchmark`」不可执行：Makefile 硬编码 manifest 与 replay 产物，需加可覆盖变量。换语料后基准页数值不可比，风险表应补 R4-7「检索层改动后未重跑基准导致基准页数值污染」 |
| §6 | 「`unknown` 权利文档不得出现」在默认 scope 下不成立（该许可类的语义是 fail-closed，只在调用方限制时被排除）。应改为「在设定了许可白名单的 scope 下」并补一条默认 scope 下可见的对照用例 |
| §6 | 空查询的既有确定行为未纳入回归；超长查询无上限声明 |
| §3.5、§3.7 | scope 受限导致社区层被禁用后的答案质量下降未声明为预期降级 |
| §4.3 | `is_unrestricted()` 的逐字段登记模式不可持续，未给兜底（建议加一条遍历 `dataclasses.fields(RetrievalScope)` 的元测试） |

**F5**

| 位置 | 要点 |
|---|---|
| §2 | 「无分面聚合：所有概览都是全库计数」与既有 `stats()` 的 group-by 矛盾，且与本稿 §3.2 把来源与许可列为「已有分面来源」前后不一致 |
| §3.7 | 非法项目标识未给稳定错误码，契约测试无法钉 |
| §5 | 「`docs/api.md` 与 `docs/cli.md` 同步（后者由 `make docs-reference` 生成）」表述正确，但 §3.6 的排序变更未同步提 `docs/api.md` |
| A5-2、§6 | 「文档总数」未定义；未列单文档、`project` 全 NULL、`tags` 非空而 `auto_tags` 全空三个用例 |
| §3.8 | 引 `docs/architecture.md` 的「刻意不做的东西」用中文名，该章节英文标题为 `What is deliberately absent`，按中文名找不到 |

**F6**

| 位置 | 要点 |
|---|---|
| §3 W3 | 「一万个文件在本地磁盘上是亚秒级」是无实测断言，且 §9 又把它列为待测项；成本描述也漏了每轮 `documents` 全表读回（`reconcile.py:400-413`） |
| §3 W3、§9 | 轮询间隔只有硬编码示例，没有可配落点 |
| §2 | 分支 ADR 写 0012 与将要改成的 0013 并存，未标注「合并前」 |
| §3 W2 | `metadata_only` 与版本链的交互未写明（是否前进 `version_seq`） |
| §4 | 回滚前置 `corpus snapshot` 与程序稿定义的回滚程序不一致，未说明它换来什么 |
| §6 | 「占位文件的行为依赖 Windows 文件属性，在 CI 的 Linux 环境上无法验证」已声明跳过，方向正确，但需同时声明该条不构成通过证据 |

## 5. 跨稿一致性缺陷

### 5.1 同一概念两处定义

| 概念 | 两处 | 处置 |
|---|---|---|
| `C-1 文档身份` | 程序稿 §3 C-1 与 F1 §3.3 | 见 R-4，必须由程序稿统一改写一次 |
| `C-10 主题` | F2 §3.1（簇）与 F5 §3.2（两层） | 见 P1-43 |
| 占位文件的检测与失败原因 | F1 R1-1 与 F6 §3 W4 | 见 P1-38，结论还相反 |
| `RetrievalScope` 新字段 | 程序稿 §4.4、F4 §4.3、F5 §4 | 见 P1-16 |
| 版本链写入方 | 程序稿 §4.3 与 C-4、F3 §3.2 | 见 R-2 第 7 条 |

### 5.2 悬空引用

| 引用方 | 指向 | 问题 |
|---|---|---|
| 程序稿 §4.1 | 「F3 §8 的多项目升级条件」 | F3 §8 无此内容，`document_projects` 全仓只出现一次（见 P1-50） |
| 程序稿 §3 C-9 指代 | `document_citations.detected_by` | 该列已在 §4.2 被撤销，指代未同步。**本轮已修正** |
| F2 §3.3、R2-3 | 「F3 的导出规则」 | F3 无导出内容（见 P1-51） |
| F6 §7 | `sci-rag relate versions` | 属 F3 的 P3 交付物，未交付也未列清单（见 P1-29） |
| F1 §6 | 「超长单行 CSV」 | CSV 不在本稿格式集合内 |
| F1 §5 | 「两个适配器」 | 与 §9.1 的三个候选不一致 |
| F3 §5、§9 | 「F5 §5 的统一决定」 | 决定在 F5 §3.5 |

编号本身闭合：`C-1` 至 `C-11`、`DS-1` 至 `DS-5`、`CP-1` 至 `CP-6`、`F1` 至 `F6` 均无越界引用也无孤儿定义（七份稿交叉核对通过）。

## 6. 建议的修复批次

### 批次一：程序稿的语义地基（必须先做，其余批次全部依赖它）

1. R-1 的 `is_current` 基线谓词与 §4.4 重写（含 graph 与 community 两处同步、测试断言改写、验收命令）。
2. R-2 的版本链写入通道与 `build_plan` 裁决（含 `PendingIngest`、`_newest_first` 判据、部分唯一索引、同事务、报告收敛）。
3. R-3 的 `content_hash` 约束改写。
4. R-4 的 C-1 身份改写（四份功能稿共同依赖）。
5. P1-16 的 scope 字段总表、P1-17 的 `projects` 表定型、P1-21 的判据两级化、P1-34 的两节补齐。
6. 批次一完成后重跑 `pytest tests/unit/test_retrieval_scope.py`，它必须全绿。

### 批次二：F1 与 F6（两者共用 reconcile 与 fingerprint，必须同批）

R-4 的实现（`parse_file_many`、成员身份、`probe_content_hash` 聚合）、P1-36、P1-38、P1-39、P1-35、P1-44。

### 批次三：F2

R-6、P1-31、P1-32、P1-33、P1-48、P1-49、P1-40。本体换代先于 F3，因为 F3 的提及检测与项目实体都依赖新本体的产出。

### 批次四：F3

P1-01 至 P1-09、P1-13、P1-18 至 P1-20、P1-26、P1-50 至 P1-51。这些全部依赖批次一的 `build_plan` 与批次三的本体。

### 批次五：F4 与 F5

R-5、P1-10 至 P1-12、P1-14、P1-15、P1-23 至 P1-25、P1-28、P1-30、P1-37、P1-52、P1-53。F4 的中文 spike 可以立刻启动，它不依赖前四批。

### 并行机会

- F1 的 Office 与邮件解析器实现不依赖任何批次，可与批次一同期开工；只有它的**身份与元数据落库**部分必须等批次一。
- F4 的中文 spike 同理。
- F2 的本体提示词起草不依赖批次一。

## 7. 证据边界

1. 本报告的行号与源码论断分三级。标 `[实读]` 的经主审实际读取命中，包括 `models.py:92` 与 `:207`、`types.py:83-107` 的 docstring 与九条条件、`is_unrestricted()` 的三个调用点、`graph.py:202-211`、`community.py:29`、`test_retrieval_scope.py:40-53`、`keyword.py:24`、`draft/prompts.py:37` 与 `54-58`、`reconcile.py:228-248` 与 `:316`、`export.py:146` 与 `:148`、`cli/main.py:44-50` 与 `:1810` 与 `:1853`、`corpus.py:73`、`routers/` 的七个路由、`Makefile:87`。
2. 工作树 `.worktrees/incremental-reconcile` 内的行号（`reconcile.py`、`fingerprint.py`）标 `[报告]`，由 F1 与 F3 两名审稿人各自实读并交叉确认，主审核对了 `:316` 的 docstring 与 `:228-248` 的裁决逻辑。
3. 本轮**未验证**的项：`make benchmark` 与 `make benchmark-check` 未实际运行；`make docs` 的 `--check` 未运行；`docs/cli.md` 的生成链未运行；OCR 引擎的实测对比未做（属 R-5 与 P1-24 的 spike 范围）；Windows 占位文件属性位未做实验。
4. 本报告不判断各项改法的**优先级之外的工期**，也不替代各稿修订后的复审。§4 的 P2 项未逐条做源码复核，只按审稿人汇报收录。
5. 本轮顺带修正的 5 处零判断空间错误已记在各条 P2 与 §5.2 中，改动不涉及任何设计决策。
