---
title: 基准测试目录
description: 选哪个公开基准、每个基准测什么、需要多少 A100 卡时，以及在一张卡上跑更大规模的方法。
---

# 基准测试目录

英文版：[Benchmark catalogue](benchmark-catalogue.md)

要回答"图检索值不值"，先要选一个**能回答这个问题**的基准，而不是选一个最大的。本页列出九个候选、各自的成本，以及在租来的一张 A100 上把它们跑起来的完整步骤。

## 公开基准能测什么，不能测什么

**能测**：跨文档检索、多跳证据拼接、答案是否有出处，以及加上图这一层之后这些指标有没有变化。

**不能测**：版本链、项目归属、按时间浏览、增量刷新、文件类型解析。这四件事都需要个人语料，所以公开基准的结果与自有语料的实验回答的是报告的两半，缺一不可。

## 候选

规模取官方发布值。卡时是在一张 A100-80GB 上用 vLLM 服务 7B AWQ 模型、跑完整一轮的估算；假设与 32B 的换算见后面的成本公式。

| 基准 | 规模 | 题型 | 许可 | 测什么 | 卡时 |
|---|---|---|---:|---|---:|
| **MultiHop-RAG** | 609 篇文章 / 2,556 题 | inference、comparison、temporal、null | ODC-BY | 每题要 2 到 4 篇文档，带出版方与日期元数据 | **约 1.2 h** |
| **HotpotQA**（distractor dev） | 7,405 题 / 约 7.4 万段 | bridge、comparison | CC BY-SA 4.0 | 经典多跳问答，可对照的公开数字最多 | 约 5.5 h |
| **MuSiQue**（dev） | 2,417 题 / 约 5 万段 | 2 到 4 跳，六种组合 | CC BY 4.0 | 比 HotpotQA 更难走捷径，中间实体通常不在问题里 | 约 2.7 h |
| **2WikiMultiHopQA**（dev） | 12,576 题 / 约 3 万段 | bridge、comparison、compositional、inference | Apache-2.0 | 支撑事实本身来自 Wikidata 三元组，图这一层最有机会赢 | 约 5.8 h |
| **DocRED**（dev，抽取） | 1,000 篇 / 96 种关系 | 关系抽取 | MIT | 文档级抽取，有公开 F1 可对照；需要做本体的关系映射 | 约 0.1 h |
| **CMeIE**（抽取） | 约 2.2 万句 / 44 种关系 | 关系抽取 | 研究用途 | 中文抽取，与 `domain-personal` 更接近 | 约 0.4 h |
| **LongMemEval-S** | 500 题 / 历史最长 115k token | 单会话、多会话、时序、偏好 | MIT | 长期记忆；语料是对话，版本与项目归属逻辑用不上 | 约 14 h |
| **LoCoMo** | 50 段长对话 | 多跳、时序、对抗 | 研究用途 | 对话记忆，同上 | 约 0.8 h |
| **BEIR / SciFact** | 18 个子集 / 1,409 条 claim | 纯检索 | 各异 | 检索泛化；不生成答案，几乎不占 GPU | 约 0 |

## 三句读表结论

- **MultiHop-RAG 是"最便宜且仍有说服力"的那个**：小到能把图建起来，题目需要 2 到 4 篇文档，`null` 题顺带给出拒答探针。从它开始。
- **如果图这一层没显出效果，就换 2WikiMultiHopQA**：它的证据本身是三元组，在那里得到"无差异"比在新闻散文上得到"无差异"更有信息量。
- **DocRED / CMeIE 是给抽取章节用的**，不是给检索章节用的。代价是要把 96 或 44 种关系映射到你的本体上（挑 8 到 10 种就够，不要全映射）。

## 成本公式

```
输入 token = 语料 token + 题数 × 条件数 × 上下文 token
输出 token = 语料 token × 2（建图） + 题数 × 条件数 × 600
卡时 = 输入 / 12000 / 3600 + 输出 / 2500 / 3600
```

常数尽量用实测值：

| 常数 | 取值 | 来源 |
|---|---|---|
| 每次运行的输入 | 约 1,545 token | 1/4 样本探针实测，硅基 API，`--sources 5` |
| 每次运行的输出 | 约 600 token | 一次答案加两次判官 |
| A100 prefill | 约 12,000 tok/s | vLLM，7B AWQ，batch 32 |
| A100 decode | 约 2,500 tok/s | 同上 |
| 换成 32B | ×3 | 算力与权重大约各涨 4 倍，吞吐降到约三分之一 |
| 走 API 时每次运行的墙钟 | 约 20 秒（并发 8） | 实测，每次运行含四次串行调用 |

除 GPU 之外还要留时间：解析、嵌入、检索。这台笔记本上是几分钟；租来的机器单核更慢但核更多，新环境加模型下载请额外预留一小时。

## 我们这一版跑到哪

计划中的正式结果是 MultiHop-RAG 的 1/4 分层抽样：639 题 × 3 个条件 = 1,917 次运行，配对 n=639。三个条件是 `plain`（不给检索）、`rag`（向量加关键字）、`kg`（全层）。

**但这次没有跑完，原因在建图**：本页末尾的实测显示，新闻语料上的图抽取受输出长度限制（一次调用输出约 6,200 token，撞上 8,192 的上限后被截断、拆批重试），按这个速率整份语料要十几小时。所以仓库里留下的是可运行的脚本与成本模型，不是一份基准成绩。要跑的人按下一节操作即可。

## 在 A100 上跑更大的规模

运行器不关心模型在哪：它走任意 OpenAI 兼容端点。换 GPU 只改常数，不改命令。

### 新机器上的四件事

这四条是这个项目上真实踩过的坑：

1. **两个 extra 要在一条命令里装。** `uv sync` 只装你点名的集合，先 `--extra openai` 再 `--extra modelscope-embedding` 会把 OpenAI 客户端卸掉，下一次运行直接报 `needs the 'openai' extra`。用 `uv sync --extra openai --extra modelscope-embedding`。
2. **数据库要带 pgvector。** 用 `docker compose up -d --wait`，或对已装的 PostgreSQL 16 到 18 用 `scripts/local_postgres.py`。拉不到容器镜像的网络环境设 `SCI_RAG_DB_BACKEND=local`。
3. **给一个可写的数据根。** `export PCMEM_DATA_DIR=/data/pcmem`（或机器上空间够的目录）。语料、模型缓存、报告都在它下面，安装脚本与 fixture 脚本会拒绝写到外面。
4. **网络需要镜像时先配好。** 嵌入模型来自 ModelScope，中国大陆可直连；走 Hugging Face 需要 `HF_ENDPOINT=https://hf-mirror.com`。首次嵌入调用要下载约 1.2 GB，本项目实测 153 秒，装一次留着缓存。

再花零成本确认环境：

```bash
uv run sci-rag doctor          # schema 版本、本体、模型可达性
uv run python scripts/run_benchmark_eval.py --dataset ... --corpus-dir ... --dry-run
```

dry run 只写 Markdown 与 manifest 就停，数据集目录不对会在这里暴露，而不是一小时之后。

### 起模型并跑全量

```bash
# 1. 起模型。AWQ 的 7B 在 24 GB 内；32B 约需 20 GB。
vllm serve Qwen/Qwen2.5-7B-Instruct-AWQ \
  --max-model-len 8192 --gpu-memory-utilization 0.9 --max-num-seqs 64

# 2. 指到这个端点
export SCI_RAG_LLM_PROVIDER=openai-compatible
export SCI_RAG_OPENAI_BASE_URL=http://127.0.0.1:8000/v1
export SCI_RAG_OPENAI_API_KEY=dummy        # vLLM 不校验这个值
export SCI_RAG_LLM_MODEL=Qwen/Qwen2.5-7B-Instruct-AWQ
export SCI_RAG_EMBEDDING_PROVIDER=modelscope
export SCI_RAG_EMBEDDING_DIM=1024

# 3. 语料、图、三档对照
uv run python scripts/run_benchmark_eval.py \
  --dataset ~/data/MultiHopRAG --corpus-dir "$PCMEM_DATA_DIR/multihop" --dry-run
uv run sci-rag ingest --manifest "$PCMEM_DATA_DIR/multihop/manifest.jsonl"
uv run sci-rag graph extract && uv run sci-rag graph communities
uv run python scripts/run_benchmark_eval.py \
  --dataset ~/data/MultiHopRAG --corpus-dir "$PCMEM_DATA_DIR/multihop" \
  --limit 0 --sources 5 --concurrency 32 --output .context/benchmark-full
```

`--limit 0` 表示全部题目，`--concurrency 32` 能把一张 A100 喂饱。用托管 API 时反过来，把并发压到 8 到 12：那边的天花板是每分钟 token，不是 GPU。

| 规模 | 运行次数 | API（23 次/分） | 一张 A100 | 硅基费用 |
|---|---:|---:|---:|---:|
| 1/4 样本（计划值） | 1,917 | 约 1.4 h | 约 3 min | 约 ¥8 |
| 1/2 样本 | 3,834 | 约 2.8 h | 约 6 min | 约 ¥12 |
| 全量 | 7,668 | 约 5.5 h | 约 12 min | 约 ¥21 |

GPU 那一列不含建图，而小语料上建图是更大的一半：MultiHop-RAG 建图约 0.39 卡时，全部答案加判官约 0.79 卡时。

## 建图才是贵的那一半（实测）

用出厂 `domain-personal` 本体、Qwen3-30B-A3B-Instruct，在 MultiHop-RAG 的 20 篇文章（71 个 chunk）上做冒烟：

| 指标 | 结果 |
|---|---|
| 30 分钟超时前完成的抽取调用 | 9 次 |
| 输入 token | 29,364 |
| 输出 token | 55,959 |
| 输出/输入比 | 1.9 |
| 超时前写入 | 86 个实体、64 条关系 |

失败原因不是服务方，而是**输出长度**：一批 10 个新闻 chunk 会要求模型枚举几百个实体与关系，于是它输出约 6,200 token，撞上 8,192 的上限，返回被截断的 JSON；抽取器识别后拆批重试，这是正确行为，也正是墙钟变成几十秒一次的原因。

两条给要跑大规模的人：

- **decode 时间才是主导项。** 单流约 40 token/s、输出/输入 1.9 的情况下，无论 token 上限多少，串行建图都是几个小时的事。`sci-rag graph extract --concurrency N` 现在让 N 批同时在飞，把这部分 decode 变成 N 路并行；每批仍要拿文档写锁再落库，所以存下来的图与并发数无关。MultiHop-RAG 全量约 240 次调用，并发 8 时约是一小时的 decode 而不是十三小时。这是按上面那次冒烟做的算术，不是一次跑完的实测。另一条杠杆仍是把批量压到永不截断。
- **本体必须和语料匹配。** 同样 20 篇文章走出厂 `domain/` 农业本体时几乎抽不出东西：模型遵守了"只用这些实体类型"，而新闻里的人名、机构、事件一个都套不进去。在得出"抽取很弱"的结论前，先把 `SCI_RAG_DOMAIN_DIR` 指到匹配的本体。

实践结论：并发把**基准级别的全量建图**从研究任务变成了半个下午的服务方时间。没变的是语料规模这道墙：段落级语料（HotpotQA 约 7.4 万段、MuSiQue 约 5 万段）一段就是一个 chunk，任何并发数都救不回 7.4 万次调用。MultiHop-RAG 的 609 篇是负担得起的，所以就在它上面跑 `plain`、`rag`、`kg` 三条件。本体那条论证也没变：`SCI_RAG_DOMAIN_DIR` 必须指向实体类型能覆盖语料的 Profile，否则图这一层无论吞吐多高都抽不出东西。

## 本地嵌入实测

Qwen3-Embedding-0.6B 在 M5 Pro 上走 MPS，1,024 维：

| 批量 | 吞吐 |
|---|---:|
| 128 个 chunk（25,600 token） | 6,439 tok/s |
| 200 个 chunk（40,000 token） | 6,159 tok/s |

MultiHop-RAG 语料约 1.58M token，所以过一遍约 4 到 5 分钟；首次调用含下载与加载是一次性的 153 秒。单次查询嵌入是几十毫秒，相对一次 20 秒的问答运行可以忽略。

由此得到两个值得记住的结论：嵌入从不与服务方争 token 配额（那个配额是给对话接口的），而本地嵌入器正是私有语料能跑起来的前提。
