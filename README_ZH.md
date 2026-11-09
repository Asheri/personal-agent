# PC-Mem

[English](README.md) | **简体中文**

PC-Mem 把个人电脑里散落的文件整理成 Agent 能长期记住的知识库：一份材料属于哪个项目、哪一份是最新版本、之前在哪个项目里做过类似的事。分块、向量、全文索引、概念图和版本链都在同一个 PostgreSQL 里；命令行、REST 接口和 MCP 工具走同一个服务门面，三处行为不会分叉。

本文件与英文 README 章节结构一致，深入到具体配置、每层检索、评测命令时请看英文 [`README.md`](README.md) 与 [`docs/`](docs/) 原文，避免两份译文长期漂移。

## 来源声明

本仓库由两个上游拼合而成，GitHub 上不显示任何 fork 关系，来源只记录在下表和 [`MIGRATION.md`](MIGRATION.md) 里。

| 部分 | 状态 | 出处 |
|---|---|---|
| `src/sci_rag/` 知识库、`domain/` 演示域、迁移 `0001` 到 `0007`、`docs/` 大部分 | **原样复制** | Sci RAG Kit `v0.5.0`，BSD-3-Clause |
| `tests/`、`scripts/`、`Makefile`、`Dockerfile`、`pyproject.toml`、`uv.lock`、文档生成管线 | **复制后修改** | Sci RAG Kit `v0.5.0`，按个人文件空间的需要扩展 |
| `plugins/hooks.py`、`plugins/project_mode.py`、`memory/memory_management_sop.md` 与 `memory/` 下的记忆模板 | **逐字复制** | GenericAgent `a9a36b4b219593369de01c3e5973e56ac02a568b`，MIT |
| `domain-personal/`、迁移 `0008` 到 `0013`、`browse.py`、`refresh.py`、`projects.py`、`reconcile.py`、`versions.py`、`relate/`、`agent_memory.py`、`memory_state.py`、`agent_backend.py`、Office/邮件/代码/OCR 解析、`plugins/pcmem_router.py`、`memory/pcmem_sop.md`、`docs/adr/0013` 到 `0020`、各阶段规格与审阅模板 | **本项目原创** | 本项目 |

比例并不均衡：`src/` 下共 30,463 行，本仓库新增或重写的约 5,300 行，占 17%；其余随 fork 一起进来。13 个 Alembic 迁移里有 6 个是新的。

两家的许可证声明见 [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md)，其中包含 GenericAgent 的 MIT 全文与文件级 blob 校验值。三位作者的署名与各自负责的部分见 [`AUTHORS.md`](AUTHORS.md)。

## 快速开始

三个平台共用同一套依赖与测试，区别只有环境准备和定时任务。

| 步骤 | macOS 与 Linux | Windows |
|---|---|---|
| 依赖 | `uv sync` | `uv sync` |
| 数据库 | `make db-up`，或 `docker compose up -d` | 用下面的 `db-up` 任务 |
| 配置文件 | `cp .env.example .env` 后 `chmod 600 .env` | 用英文 README 里那段 `icacls` 序列 |
| 演示 | `make demo` | 用 `demo` 任务 |

Windows 默认没有 `make`，所以每个日常目标都另有一个跨平台任务入口，两者执行完全相同的命令：

```bash
make db-up                            # macOS 与 Linux
uv run python scripts/tasks.py db-up  # 三个平台
uv run python scripts/tasks.py --list # 列出全部任务
```

`docs`、`benchmark`、`benchmark-check`、`benchmark-refresh-graph` 四个目标在 Makefile 里是 POSIX shell 管道，仍留在 Makefile；任务入口会明确拒绝并提示改用 `make`。数据库可以用 Docker、系统安装的 PostgreSQL、macOS 上的 Postgres.app，或 Cloud SQL，见 [`docs/run-postgres.md`](docs/run-postgres.md)。Docker 是默认后端，需要能访问容器镜像仓库；拉不到 `pgvector/pgvector` 的网络环境请把 `SCI_RAG_DB_BACKEND` 设为 `local`，让 `scripts/local_postgres.py` 使用本机已装的 PostgreSQL 16 到 18 与 pgvector。

跑通个人域而不是演示域：

```bash
cp .env.example .env
chmod 600 .env
uv sync
SCI_RAG_DB_BACKEND=docker make db-up
SCI_RAG_DOMAIN_DIR=domain-personal uv run sci-rag db upgrade
uv run sci-rag doctor
```

## 命令速查

| 想做什么 | 命令 |
|---|---|
| 建库并入库 | `uv run sci-rag build data/demo/fixture` |
| 体检 | `uv run sci-rag doctor` |
| 提问 | `uv run sci-rag answer "问题"` |
| 按项目、时间、主题浏览 | `uv run sci-rag browse documents --filters '{"sources":["local"]}'` |
| 一次性增量刷新 | `uv run sci-rag refresh run <目录> --channel manual` |
| 起服务 | `uv run sci-rag serve`（REST 在 `/docs`，MCP 在 `/mcp`） |
| 检索消融 | `uv run sci-rag eval retrieval --ablation` |

完整命令树见 [`docs/cli.md`](docs/cli.md)。

## 状态与边界

这棵树是候选实现，不是已批准的发布版本。每个阶段在 `docs/superpowers/specs/` 下有带日期的规格和审阅模板，九份模板的审阅人一栏都还是 `unassigned`。

已知并已声明的边界：

- **语料是合成的。** `data/demo/` 是 5 篇农业残留物短文，`data/demo-personal/` 是 20 条构造样例加 8 条对照。在它们上面算出的命中率和 F1 说明机制通了，不代表真实文件集的准确率。
- **证据留在本地。** `.context/` 被 git 忽略，里面是这次改动的运行回执。克隆本仓库无法复核 [`docs/engineering-requirements.md`](docs/engineering-requirements.md) 里的数字；已实测的数字与出处集中记在 [`docs/verification.md`](docs/verification.md)。
- **没有声称**独立审阅、真实语料部署、真实模型长期对话，或大目录性能指标。
- **图片 OCR 是可选能力。** 需要 `ocr` extra 和带 `chi_sim` 的 Tesseract，缺了就保留旧版本并报告失败。
- **Agent 安装器只支持 Windows。** `scripts/install_pcmem_agent.py` 生成 PowerShell 启动脚本和计划任务 XML；`scripts/prepare_agent_fixture.py` 与 `scripts/run_agent_acceptance.py` 还要求路径落在 `PCMEM_DATA_DIR` 下。知识库本体和 `sci-rag refresh run --channel poll` 三个平台都能跑，macOS 与 Linux 的定时封装还没有。

## 许可

知识库部分为 BSD-3-Clause，逐字复制的 GenericAgent 文件为 MIT。两份声明分别见 [`LICENSE`](LICENSE) 与 [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md)。
