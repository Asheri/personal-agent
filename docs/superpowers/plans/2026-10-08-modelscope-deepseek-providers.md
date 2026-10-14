# ModelScope Embedding and DeepSeek LLM 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 `aegis:subagent-driven-development`（推荐）或
> `aegis:executing-plans` 逐任务实现此计划。步骤使用复选框（`- [ ]`）跟踪进度。

**目标：** 将默认嵌入切换为 ModelScope 下载的 Qwen3-Embedding-0.6B，将默认生成切换为 DeepSeek，
同时保留现有供应商、离线测试和数据库迁移安全边界。

**架构：** 在现有 `EmbeddingProvider` 与 `LLMClient` 接口内新增两个供应商。DeepSeek 复用
OpenAI-compatible 协议和既有重试/流式实现；ModelScope 在本地加载 Sentence Transformer，并把
1024 维向量迁移、全量重嵌入作为独立数据库任务。

**技术栈：** Python 3.11/3.12、uv、Pydantic Settings、SQLAlchemy async、Alembic、pgvector、
Sentence Transformers、ModelScope、OpenAI-compatible client、pytest、Ruff、mypy。

---

## 文件清单

- 创建：`src/sci_rag/embed/modelscope.py`
- 创建：`src/sci_rag/llm/deepseek.py`
- 创建：`migrations/versions/0007_embedding_dimension.py`
- 修改：`src/sci_rag/config.py`
- 修改：`src/sci_rag/embed/__init__.py`
- 修改：`src/sci_rag/llm/spec.py`
- 修改：`src/sci_rag/llm/__init__.py`
- 修改：`src/sci_rag/cli/doctor.py`
- 修改：`src/sci_rag/scaffold/answers.py`
- 修改：`src/sci_rag/scaffold/questions.py`
- 修改：`src/sci_rag/scaffold/apply.py`
- 修改：`src/sci_rag/scaffold/preflight.py`
- 修改：`pyproject.toml`
- 修改：`.env.example`
- 修改：`README.md`、`docs/configuration.md`、`docs/extend.md`、`docs/faq.md`
- 创建：`docs/adr/0012-modelscope-deepseek-providers.md`
- 修改：`tests/conftest.py`、`tests/unit/test_model_spec.py`、
  `tests/unit/test_llm_factory.py`、`tests/unit/test_doctor_offline.py`
- 创建：`tests/unit/test_deepseek_provider.py`、`tests/unit/test_embed_modelscope.py`
- 修改：`tests/integration/test_reindex.py`、`tests/integration/test_doctor.py`

## 任务 1：配置与 model-spec 契约

**文件：**
- 修改：`src/sci_rag/config.py`
- 修改：`src/sci_rag/llm/spec.py`
- 测试：`tests/unit/test_model_spec.py`、`tests/unit/test_default_model_is_single_sourced.py`

- [x] **步骤 1：编写失败的配置测试**

在 `tests/unit/test_model_spec.py` 增加：

```python
def test_deepseek_is_a_known_provider_with_shipped_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.embedding_provider == "modelscope"
    assert settings.embedding_model == "Qwen/Qwen3-Embedding-0.6B"
    assert settings.embedding_dim == 1024
    assert settings.llm_provider == "deepseek"
    assert settings.llm_model == "deepseek-flash"
    assert settings.deepseek_api_key is None
    assert settings.deepseek_base_url == "https://api.deepseek.com"
    assert parse_model_spec("deepseek:deepseek-flash", default_provider="google") == ModelSpec(
        "deepseek", "deepseek-flash"
    )
```

- [x] **步骤 2：运行测试验证失败**

运行：

```bash
uv run pytest tests/unit/test_model_spec.py::test_deepseek_is_a_known_provider_with_shipped_defaults -q
```

预期：失败，原因是 `Settings` 尚无 DeepSeek 字段且默认仍为 Google。

- [x] **步骤 3：实现配置与 spec 解析**

在 `config.py` 中：

```python
LLMProviderName = Literal["google", "anthropic", "openai-compatible", "deepseek"]
DEFAULT_LLM_MODEL = "deepseek-flash"

deepseek_api_key: str | None = None
deepseek_base_url: str = "https://api.deepseek.com"
embedding_provider: Literal["modelscope", "google", "local-hash"] = "modelscope"
embedding_model: str = "Qwen/Qwen3-Embedding-0.6B"
embedding_dim: int = 1024
llm_provider: LLMProviderName = "deepseek"
```

`LLMProviderName` 变化会自动进入 `KNOWN_PROVIDERS`；增加字段验证 `deepseek_base_url`
不能为空，且 `embedding_dim` 在 `modelscope` 模式下必须位于 32 到 1024 之间。

- [x] **步骤 4：运行测试验证通过**

```bash
uv run pytest tests/unit/test_model_spec.py tests/unit/test_default_model_is_single_sourced.py -q
```

预期：PASS。

- [x] **步骤 5：检查向后兼容**

```bash
uv run pytest tests/unit/test_model_spec.py -q
```

预期：裸 model id、`google:model`、`anthropic:model`、`openai-compatible:model`
仍按原规则解析。

## 任务 2：DeepSeek OpenAI-compatible 适配器

**文件：**
- 创建：`src/sci_rag/llm/deepseek.py`
- 修改：`src/sci_rag/llm/__init__.py`
- 测试：`tests/unit/test_deepseek_provider.py`、`tests/unit/test_llm_factory.py`

- [x] **步骤 1：编写失败的 DeepSeek 单元测试**

创建 `tests/unit/test_deepseek_provider.py`，复用 `test_openai_compat_provider.py` 的
`StubCompletions` 和 `StubOpenAI`，覆盖：

```python
from sci_rag.config import Settings
from sci_rag.llm.deepseek import DeepSeekLLM
from tests.unit.test_openai_compat_provider import StubCompletions, StubOpenAI

def _deepseek_with(monkeypatch, completions, settings=None):
    import openai

    monkeypatch.setattr(
        openai,
        "AsyncOpenAI",
        lambda **kwargs: StubOpenAI(_completions=completions, **kwargs),
    )
    return DeepSeekLLM(
        settings
        or Settings(_env_file=None, deepseek_api_key="sk-deepseek")
    )

def test_deepseek_uses_dedicated_key_and_endpoint(monkeypatch):
    settings = Settings(_env_file=None, deepseek_api_key="sk-deepseek")
    llm = _deepseek_with(monkeypatch, StubCompletions(), settings)
    assert llm._client.api_key == "sk-deepseek"
    assert llm._client.base_url == "https://api.deepseek.com"
    assert llm.model == "deepseek-flash"

def test_deepseek_missing_key_fails_closed():
    with pytest.raises(RuntimeError, match="SCI_RAG_DEEPSEEK_API_KEY"):
        DeepSeekLLM(Settings(_env_file=None))

async def test_deepseek_stream_yields_deltas_and_closes(monkeypatch):
    completions = StubCompletions(text="streamed answer")
    llm = _deepseek_with(monkeypatch, completions)
    chunks = [chunk async for chunk in llm.stream("q")]
    assert "".join(chunks) == "streamed answer"
    assert completions.stream_obj.closed

async def test_deepseek_retries_one_transient_error(monkeypatch):
    completions = StubCompletions(failures=1, text="recovered")
    llm = _deepseek_with(monkeypatch, completions)
    assert await llm.generate("q") == "recovered"
    assert len(completions.requests) == 2

async def test_deepseek_json_mode_sets_response_format(monkeypatch):
    completions = StubCompletions(text='{"ok": true}')
    llm = _deepseek_with(monkeypatch, completions)
    assert await llm.generate_json("q") == {"ok": True}
    assert completions.requests[0]["response_format"] == {"type": "json_object"}
```

- [x] **步骤 2：运行测试验证失败**

```bash
uv run pytest tests/unit/test_deepseek_provider.py -q
```

预期：失败，`DeepSeekLLM` 不存在。

- [x] **步骤 3：实现 DeepSeek 适配器**

`DeepSeekLLM` 复用 `OpenAICompatLLM` 的消息、流式和重试逻辑，只替换凭据解析：

```python
class DeepSeekLLM(OpenAICompatLLM):
    def __init__(self, settings, *, model=None, api_key_override=None):
        key = api_key_override or settings.deepseek_api_key
        if not key:
            raise RuntimeError(
                "DeepSeek generation requires SCI_RAG_DEEPSEEK_API_KEY."
            )
        endpoint = settings.model_copy(
            update={
                "openai_api_key": key,
                "openai_base_url": settings.deepseek_base_url,
                "gcp_project": None,
            }
        )
        super().__init__(endpoint, model=model, api_key_override=key)
```

在 `get_llm()` 增加：

```python
elif spec.provider == "deepseek":
    from sci_rag.llm.deepseek import DeepSeekLLM
    client = DeepSeekLLM(settings, model=spec.model, api_key_override=api_key_override)
```

`DeepSeekLLM.describe()` 必须返回 `deepseek:deepseek-flash`，不暴露 key。

- [x] **步骤 4：运行测试验证通过**

```bash
uv run pytest tests/unit/test_deepseek_provider.py tests/unit/test_llm_factory.py tests/unit/test_model_spec.py -q
```

预期：PASS。

- [x] **步骤 5：验证离线边界**

```bash
uv run pytest tests/unit/test_offline_generation_boundary.py -q
```

预期：PASS；缺少 key 时不能静默切换到 Google。

## 任务 3：ModelScope Qwen3 嵌入器

**文件：**
- 创建：`src/sci_rag/embed/modelscope.py`
- 修改：`src/sci_rag/embed/__init__.py`
- 修改：`pyproject.toml`
- 测试：`tests/unit/test_embed_modelscope.py`

- [x] **步骤 1：编写失败的嵌入器测试**

创建 `tests/unit/test_embed_modelscope.py`：

```python
from sci_rag.embed import get_embedder
from sci_rag.embed.modelscope import ModelScopeEmbedder
from sci_rag.embed.provider import EmbeddingDimensionError

class StubSentenceTransformer:
    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim
        self.calls: list[dict[str, object]] = []

    def encode(self, texts, *, prompt_name=None, **kwargs):
        self.calls.append({"texts": texts, "prompt_name": prompt_name, **kwargs})
        return [[1.0] + [0.0] * (self.dim - 1) for _ in texts]

def test_modelscope_dispatch_and_version():
    embedder = get_embedder(Settings(_env_file=None, embedding_provider="modelscope"))
    assert embedder.version.startswith("Qwen/Qwen3-Embedding-0.6B@")
    assert embedder.dim == 1024

async def test_query_uses_prompt_and_document_does_not(monkeypatch):
    model = StubSentenceTransformer()
    embedder = ModelScopeEmbedder(Settings(_env_file=None), model=model)
    await embedder.embed(["question"], task="query")
    await embedder.embed(["passage"], task="document")
    assert model.calls[0]["prompt_name"] == "query"
    assert model.calls[1]["prompt_name"] is None

def test_modelscope_dimension_mismatch_is_rejected():
    embedder = ModelScopeEmbedder(Settings(_env_file=None), model=StubSentenceTransformer(dim=64))
    with pytest.raises(EmbeddingDimensionError):
        embedder.assert_dimension([0.0] * 64)
```

- [x] **步骤 2：运行测试验证失败**

```bash
uv run pytest tests/unit/test_embed_modelscope.py -q
```

预期：失败，`modelscope` 未被 `get_embedder()` 接受。

- [x] **步骤 3：实现本地 ModelScope 嵌入器**

`ModelScopeEmbedder`：

1. 构造时调用 `modelscope.snapshot_download(model_id, cache_dir=settings.modelscope_cache_dir)`，
   下载结果只缓存一次。
2. 使用 `SentenceTransformer(local_path, device=settings.modelscope_device)` 加载模型。
3. `embed()` 用 `asyncio.to_thread()` 调用 `model.encode()`，避免阻塞事件循环。
4. query 传 `prompt_name="query"`，document 不传 prompt。
5. 调用 `l2_normalize()`，再调用 `assert_dimension()`。
6. `version = f"{model_id}@{dim}"`，model id 中的 `/` 保留用于版本追踪。
7. 依赖导入失败时抛出带 `uv sync --extra modelscope-embedding` 的错误。

- [x] **步骤 4：配置可选依赖**

在 `pyproject.toml` 增加：

```toml
modelscope-embedding = [
  "modelscope>=1.18",
  "sentence-transformers>=3.0",
]
```

不在默认依赖中安装 torch/modelscope；文档明确新项目执行
`uv sync --extra modelscope-embedding`。

- [x] **步骤 5：运行测试验证通过**

```bash
uv run pytest tests/unit/test_embed_modelscope.py tests/unit/test_embed_local.py -q
```

预期：PASS。

## 任务 4：1024 维数据库迁移与重嵌入

**文件：**
- 创建：`migrations/versions/0007_embedding_dimension.py`
- 修改：`src/sci_rag/cli/doctor.py`
- 测试：`tests/integration/test_reindex.py`、`tests/integration/test_doctor.py`

- [x] **步骤 1：编写失败的迁移/维度测试**

在 disposable PostgreSQL 测试中增加：

```python
async def test_vector_columns_are_1024_after_migration(clean_tables):
    assert await live_vector_dimension(session, "chunks", "embedding") == 1024
    assert await live_vector_dimension(session, "kg_communities", "summary_embedding") == 1024

async def test_old_vectors_are_invalidated_not_mixed(clean_tables):
    # After command.upgrade(cfg, "head"):
    async with get_session_factory() as session:
        populated = await session.scalar(
            select(func.count(Chunk.id)).where(Chunk.embedding.is_not(None))
        )
        versions = set(
            (await session.execute(select(Chunk.embedding_version).distinct())).scalars()
        )
    embedder = LocalHashEmbedder(1024)
    plan = await plan_reindex(get_session_factory(), embedder)
    assert populated == 0
    assert versions == {None}
    assert plan.stale_chunks == plan.total_chunks
```

- [x] **步骤 2：运行测试验证失败**

```bash
uv run pytest tests/integration/test_reindex.py -q -k "1024 or dimension"
```

预期：当前 schema 仍为 1536，测试失败。

- [x] **步骤 3：实现 Alembic 迁移**

`0007_embedding_dimension.py`：

- 读取 `SCI_RAG_EMBEDDING_DIM`，只允许 `32 <= dim <= 1024`。
- 删除两个 HNSW index。
- 将 `chunks.embedding` 和 `kg_communities.summary_embedding` 设为 NULL。
- `ALTER TYPE`/重建为 `vector(dim)`。
- 重建 `ix_chunks_embedding_hnsw`，保留 cosine operator。
- downgrade 恢复到 1536 前先清空向量并重建旧 index。
- migration 文本中明确要求先备份数据库。

- [x] **步骤 4：运行迁移测试**

```bash
uv run pytest tests/integration/test_reindex.py tests/integration/test_doctor.py -q
```

预期：PASS；若 PostgreSQL 不可用则明确记录为 skipped，不声称通过。

- [x] **步骤 5：验证全量重嵌入流程**

```bash
uv run sci-rag db upgrade
uv run sci-rag embed reindex --dry-run
uv run sci-rag embed reindex --apply
uv run sci-rag doctor
```

预期：dry-run 报告 stale，apply 完成后 doctor 的 `embedding versions` 为 ok。

## 任务 5：项目向导与默认配置

**文件：**
- 修改：`src/sci_rag/scaffold/answers.py`
- 修改：`src/sci_rag/scaffold/questions.py`
- 修改：`src/sci_rag/scaffold/apply.py`
- 修改：`src/sci_rag/scaffold/preflight.py`
- 修改：`.env.example`
- 测试：`tests/unit/test_scaffold_answers.py`、`tests/unit/test_scaffold_apply.py`、
  `tests/unit/test_scaffold_wizard.py`

- [x] **步骤 1：编写失败的向导测试**

```python
from pathlib import Path

from sci_rag.scaffold.answers import ProjectAnswers
from sci_rag.scaffold.apply import apply_env_file

def test_project_defaults_to_modelscope_and_deepseek():
    answers = ProjectAnswers(project_name="Demo", repo_name="demo")
    assert answers.embedding_provider == "modelscope"
    assert answers.embedding_model == "Qwen/Qwen3-Embedding-0.6B"
    assert answers.embedding_dim == 1024
    assert answers.llm_provider == "deepseek"
    assert answers.llm_model == "deepseek-flash"

def test_generated_env_contains_deepseek_and_modelscope(tmp_path: Path):
    root = tmp_path
    (root / ".env.example").write_text(
        "SCI_RAG_LLM_PROVIDER=google\n"
        "SCI_RAG_LLM_MODEL=gemini-3.6-flash\n"
        "SCI_RAG_EMBEDDING_PROVIDER=google\n"
        "SCI_RAG_EMBEDDING_MODEL=gemini-embedding-001\n"
        "SCI_RAG_EMBEDDING_DIM=1536\n"
        "# SCI_RAG_DEEPSEEK_API_KEY=\n",
        encoding="utf-8",
    )
    answers = ProjectAnswers(
        project_name="Demo",
        repo_name="demo",
        credentials="deepseek",
        deepseek_api_key="secret",
    )
    apply_env_file(answers, root)
    env = (root / ".env").read_text(encoding="utf-8")
    assert "SCI_RAG_LLM_PROVIDER=deepseek" in env
    assert "SCI_RAG_LLM_MODEL=deepseek-flash" in env
    assert "SCI_RAG_EMBEDDING_PROVIDER=modelscope" in env
    assert "SCI_RAG_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B" in env
    assert "SCI_RAG_EMBEDDING_DIM=1024" in env
    assert "SCI_RAG_DEEPSEEK_API_KEY=secret" in env
```

- [x] **步骤 2：运行测试验证失败**

```bash
uv run pytest tests/unit/test_scaffold_answers.py tests/unit/test_scaffold_apply.py -q
```

预期：失败，向导仍生成 Google/1536。

- [x] **步骤 3：实现向导默认值**

- `ProjectAnswers.credentials` 增加 `deepseek` 选项，默认 `deepseek`。
- 增加 `deepseek_api_key` secret 字段和 `llm_provider` 字段。
- `embedding_provider` 选项增加 `modelscope`，默认 `modelscope`。
- 默认 `embedding_model=Qwen/Qwen3-Embedding-0.6B`、`embedding_dim=1024`。
- 离线模式仍强制 `local-hash`，且不生成 DeepSeek key。
- `apply_env_file()` 写入 `SCI_RAG_LLM_PROVIDER`、`SCI_RAG_DEEPSEEK_API_KEY`
  和 `SCI_RAG_MODELSCOPE_*`。
- preflight 对 DeepSeek 使用 dedicated key，对 ModelScope 使用本地依赖检查，
  不打印 key。

- [x] **步骤 4：运行向导测试**

```bash
uv run pytest tests/unit/test_scaffold_answers.py tests/unit/test_scaffold_apply.py tests/unit/test_scaffold_wizard.py -q
```

预期：PASS。

- [x] **步骤 5：验证新项目生成**

```bash
uv run sci-rag new --defaults
```

预期：生成的 `.env` 使用 ModelScope/DeepSeek 默认值，且没有泄露任何 key。

## 任务 6：doctor 与离线诊断

**文件：**
- 修改：`src/sci_rag/cli/doctor.py`
- 测试：`tests/unit/test_doctor_offline.py`、`tests/integration/test_doctor.py`

- [x] **步骤 1：编写失败诊断测试**

```python
def test_modelscope_without_extra_is_actionable():
    row = _embedding_provider_check(Settings(_env_file=None, embedding_provider="modelscope"))
    assert row.status == "fail"
    assert "uv sync --extra modelscope-embedding" in row.fix

def test_deepseek_without_key_fails_closed():
    checks = _by_name(_llm_credential_checks(Settings(_env_file=None, llm_provider="deepseek")))
    assert checks["llm credentials (deepseek)"].status == "fail"
    assert "SCI_RAG_DEEPSEEK_API_KEY" in checks["llm credentials (deepseek)"].fix
```

- [x] **步骤 2：运行测试验证失败**

```bash
uv run pytest tests/unit/test_doctor_offline.py -q
```

- [x] **步骤 3：实现诊断分支**

- Google credential check 仅在 `embedding_provider == "google"` 时要求 Google key。
- 新增 ModelScope check：依赖缺失或模型 id 为空为 fail；非法维度在
  `Settings` 配置加载阶段 fail-fast，doctor 不宣称能够报告该错误。
- LLM credential check 增加 `deepseek` 分支：缺 key 为 fail，key 存在为 ok。
- schema revision 更新为 `0007`；双列检查读取 live `format_type`，缺列、
  非 vector 类型或维度不符均 fail。
- `--probe` 的异常 detail 复用共享脱敏；静态 doctor 构造 embedder 不下载，
  首次 embed 才加载模型。

- [x] **步骤 4：运行测试验证通过**

```bash
uv run pytest tests/unit/test_doctor_offline.py tests/integration/test_doctor.py -q
```

## 任务 7：文档、ADR 与配置引用

**文件：**
- 修改：`.env.example`、`README.md`、`docs/configuration.md`、`docs/extend.md`、`docs/faq.md`
- 创建：`docs/adr/0012-modelscope-deepseek-providers.md`
- 测试：`tests/unit/test_docs_style.py`、`tests/unit/test_docs_shipped_defaults.py`

- [x] **步骤 1：编写失败文档契约测试**

```python
def test_docs_document_new_default_providers():
    env = Path(".env.example").read_text(encoding="utf-8")
    assert "SCI_RAG_EMBEDDING_PROVIDER=modelscope" in env
    assert "SCI_RAG_LLM_PROVIDER=deepseek" in env
    assert "SCI_RAG_DEEPSEEK_API_KEY" in env
    assert "modelscope-embedding" in Path("README.md").read_text(encoding="utf-8")
```

- [x] **步骤 2：运行测试验证失败**

```bash
uv run pytest tests/unit/test_docs_shipped_defaults.py -q
```

- [x] **步骤 3：更新文档与 ADR**

ADR 记录：

- 为什么选择本地 ModelScope 下载而不是 ModelScope hosted inference；
- 为什么 Qwen3 原生 1024 维触发 schema migration；
- 为什么 DeepSeek 复用 OpenAI-compatible 协议；
- 为什么旧 Google/Anthropic/OpenAI-compatible 仍保留；
- 何时需要撤销该决策。

- [x] **步骤 4：运行文档检查**

```bash
uv run pytest tests/unit/test_docs_style.py tests/unit/test_docs_shipped_defaults.py -q
uv run mkdocs build --strict
```

预期：PASS。

## 任务 8：全量验证与交付

- [x] **步骤 1：运行格式、lint 和类型检查**

```bash
uv run ruff format --check src tests examples scripts
uv run ruff check src tests examples scripts
uv run mypy
```

- [x] **步骤 2：运行离线单测**

```bash
uv run pytest tests/unit -q
```

- [x] **步骤 3：运行数据库集成测试**

```bash
SCI_RAG_DB_BACKEND=docker make db-up
SCI_RAG_TEST_DATABASE_URL=postgresql+asyncpg://sci_rag:sci_rag@localhost:5433/sci_rag_test \
  uv run pytest tests/integration -q
```

若数据库不可用，明确报告 skipped，不把 skipped 说成通过。

- [x] **步骤 4：可选真实供应商 smoke test**

```bash
SCI_RAG_EMBEDDING_PROVIDER=modelscope \
SCI_RAG_DEEPSEEK_API_KEY=<key> \
uv run sci-rag doctor --probe
```

只在用户明确提供凭据且允许网络调用时运行；输出中不得出现 key。

- [x] **步骤 5：审查最终 diff**

```bash
git diff --check
git status --short
```

确认没有 `.env`、模型缓存、下载文件、API key 或无关格式化改动。

## 计划自检

1. **规格覆盖度**：配置、DeepSeek、ModelScope、1024 迁移、向导、诊断、文档、测试均已对应任务。
2. **占位符扫描**：计划中不存在 `TODO`、`TBD`、省略号或空测试；测试助手
   `StubCompletions`、`StubOpenAI`、`_deepseek_with` 和
   `StubSentenceTransformer` 均给出了实际定义。
3. **类型一致性**：统一使用 `Settings`、`ModelSpec`、`EmbeddingProvider`、`LLMClient`、
   `ModelScopeEmbedder`、`DeepSeekLLM`、`SCI_RAG_DEEPSEEK_API_KEY` 和
   `SCI_RAG_EMBEDDING_DIM=1024`。
4. **执行边界**：不修改 scope、fusion、answer prompt 或评估方法；不提交凭据或模型缓存。
