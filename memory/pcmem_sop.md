# pcmem_sop: 文件知识库使用入口（L3）

关键前置 + 典型坑清单。知识库是「文件事实层」，GA 记忆是「经验层」，勿互相搬运内容。

## 入口命令（主仓库根目录执行）

- 检索: `uv run sci-rag retrieve "<问题>" --profile deep --explain-routing`
- 问答: `uv run sci-rag answer "<问题>"`（带编号引用，答案只依据语料）
- 概览: `uv run sci-rag stats`
- 浏览/关系命令（browse、relate）属 P4/P3 交付，尚未存在，勿凭印象调用
- 域切换: 环境变量 `SCI_RAG_DOMAIN_DIR=domain-personal`（个人文件域），不设则用出厂 demo 域
- 健康检查: `uv run sci-rag doctor`

## 典型坑

1. 中文 keyword 层 spike 未过前，关键字路可能空候选（trace.status=empty 属已知降级），
   以向量层为主并如实声明，禁把「整体可用」当关键字层可用。
2. 历史版本默认不可见是基线谓词（is_current），不是 bug；要旧版走版本读取入口。
3. 时间过滤对无日期文档是保留语义（不被排除），时间结果里注意空日期桶。
4. 无生成凭据时图抽取/社区摘要整体不可用，doctor 会报未抽取文档数；勿把降级当完成。
5. 邮件/Office 正文默认 license_class=unknown，出站（外部模型/导出）fail-closed，先声明再放行。
6. 一次性任务模式跑增量：`python agentmain.py --task <iodir>` 的文件驱动方式见 GA subagent.md。

## 记忆分工

- 知识库回答「文件世界里有什么」（项目、版本、关系、原文出处）。
- L1-L3 回答「这个用户怎么工作」（偏好、约定、SOP、路由）。
- 写入纪律：No Execution, No Memory；只 patch 不 overwrite；指针化（doc id/project_id），不抄原文。
