# F1 实现计划：自动读取并解析不同类型的本地文件

- 日期：2026-10-14
- 状态：设计稿初稿，待评审
- 阶段：P2（与 F2 并行）
- 共享契约：迁移与存储编号见 `2026-10-14-personal-file-space-program-design.md`（下称程序稿）。本稿引用 `C-x`（概念）与 `DS-x`（存储），不重复定义。
- 组件定位：本稿拥有 `CP-1`（解析面，P2）。上游是源文件（`C-1`），下游是 `DS-1` 与 F2 的抽取面。

## 1. 功能定义与验收标准

**功能**：把指定目录下的本地文件读进语料，不需要用户为每种格式手工准备文本。

**验收标准**（逐条可机械判定，全部通过才算完成）：

| 编号 | 判据 | 判定方式 |
|---|---|---|
| A1-1 | 七类文件全部可解析：PDF、Markdown、纯文本、HTML、Office 三件套、图片与扫描件、邮件 | 集成测试对每类各放一个样本，断言 `documents` 行数等于样本数 |
| A1-2 | 表格不丢结构 | 对每个含表格的样本，断言存在 `is_table=true` 的 chunk，且其内容含表头字段 |
| A1-3 | 扫描件与图片经 OCR 产出可检索文本 | 断言 OCR 样本的 chunk 字符数大于阈值，且 `extra["ocr"]["engine"]` 有值 |
| A1-4 | 邮件按一封一文档切分 | 一个含 3 封邮件的 mbox 产出 3 行 `documents` |
| A1-5 | 解析失败可见且不静默 | `sci-rag doctor` 报告每类文件的成功数与失败数；失败项带原因字符串 |
| A1-6 | 大表不会被静默截断 | 超过行数上限的 sheet 在 `extra.truncated` 里记录被丢弃的行数 |
| A1-7 | 仓库自检不退化 | `make check` 通过，且未把二进制样本提交进仓库 |

## 2. 现状核对

已实现的部分：

- 递归扫描目录并按后缀过滤：`src/sci_rag/ingest/manifest.py:78-79`（`folder.rglob("*")`）。
- 后缀白名单：`src/sci_rag/ingest/parsers.py:54`，值为 `.pdf`、`.md`、`.markdown`、`.txt`、`.html`、`.htm`。
- 分支派发：`parsers.py:59-80` 的 `parse_file`。
- PDF 双路：Docling（可选 extra，表提取最好）优先，`pypdf` 回退，并在日志里写明实际走的哪条路（`parsers.py:59-66`）。
- HTML 用标准库解析、去页面装饰、表格转成 pipe table（`parsers.py` 模块 docstring）。
- Docling 输出先导出 Markdown 再复用 Markdown 的块切分，两条结构化路径共用一个块模型。
- 统一的中间表示：`Block(kind, text, level)` 与 `ParsedDocument(title, blocks, raw_text, page_count, metadata)`（`parsers.py:33-47`）。
- 无文本可抽时按失败处理而不是写入空文档：`src/sci_rag/ingest/ingester.py:123`，`status="failed"`、`detail="no extractable text"`。

缺失的部分：

- 无 Office 解析器，`docx`、`xlsx`、`pptx` 进不了语料。
- 无 OCR。扫描版 PDF 走 `pypdf` 后得到空文本，直接落到上面那条 `no extractable text` 失败分支；图片文件连后缀都不在白名单里，`parse_file` 抛 `ValueError`（`parsers.py:77-80`）。
- 无邮件解析。一封 `.eml` 会被当纯文本读，整段头信息与正文混在一个文档里；`.mbox` 更是把多封邮件塞进一个文档。
- 一个文件对应一个文档是硬假设。`manifest.py` 只产出 `CorpusEntry`，`ingester` 一次处理一条，没有「一个文件切出多个文档」的通路。

## 3. 设计

### 3.1 保持块模型作为唯一中间表示

仓库架构文档把「新解析器产出共享块模型」列为第一个扩展点（`docs/architecture.md:165`）。本改造沿用这条，不引入第二种文档模型。所有新解析器只做一件事：把源文件变成 `list[Block]` 或原始文本，其余交给既有切分器。

### 3.2 模块与职责

| 模块 | 职责 | 依赖 |
|---|---|---|
| `ingest/office.py` | `docx`、`xlsx`、`pptx` 转块 | 三个 Office 库，走新 extra |
| `ingest/email_parser.py` | `.eml` 与 `.mbox` 转**多个** `ParsedDocument` | 标准库 `email`、`mailbox`，零新依赖 |
| `ingest/ocr.py` | 图片与扫描页转文本，定义 `OcrEngine` 协议 | OCR 引擎走新 extra |
| `ingest/parsers.py` | 扩展后缀白名单与派发，新增 `parse_file_many` | 上述三个模块 |

每个模块只负责一种输入到块的转换，不碰数据库、不碰切分。这样它可以被单元测试单独驱动，也能在不影响调用方的情况下替换实现。

### 3.3 一个文件多个文档的通路

邮件要求「一封邮件 = 一个文档」。这突破了「一个文件 = 一个文档」的假设，因此需要在最窄的地方开口：

```python
def parse_file_many(path: Path, *, prefer_docling: bool = True) -> list[ParsedDocument]:
    """Parse one file into one or more documents. Most formats return one."""
```

`parse_file` 保留，语义改为「返回第一个」，供既有调用方与既有测试使用，行为对非邮件格式完全不变。`ingester` 的内层循环由「处理一个 `CorpusEntry`」改为「处理一个 `CorpusEntry` 产出的每个 `ParsedDocument`」，每个产出各自生成自己的 `C-3 内容哈希` 与 `DS-1 documents` 行。

`C-1 文档身份`（源文件路径）在邮件场景下不再是唯一键，因此邮件的身份改为 `path#<message-id 或序号>`，写进 `Document.extra["path"]` 之外的独立字段 `Document.extra["source_member"]`，同时 `extra["path"]` 仍记录宿主文件路径。这样 F6 的 reconcile 仍能按宿主文件判断增删改，而同一宿主内的多封邮件各自保持独立身份。

### 3.4 各格式的块映射

| 输入 | heading | text | table |
|---|---|---|---|
| `docx` | `Heading N` 样式与标题样式，级别取自样式层级 | 普通段落 | 表格转 pipe table，保留首行表头 |
| `xlsx` | 每个 sheet 名一个标题块 | 无 | 每个 sheet 一个表格块，行上限见下 |
| `pptx` | 每一页的标题占位符 | 文本框段落 | 表格形状转 pipe table |
| `.eml` / `.mbox` | 发件人、日期、邮件主题（Subject）各一行标题块 | 正文纯文本；HTML 正文走既有 HTML 路径 | 正文内表格沿用 HTML 路径 |
| 图片与扫描页 | 文件名作标题 | OCR 文本，按行合并成段 | 不尝试重建表格 |

三处需要明确写死的行为：

1. **Excel 行数上限**：默认每 sheet 前 500 行，超出部分丢弃并把丢弃行数写进 `extra["truncated"]["rows"]`。理由是一张十万行的表如果整表成块，会挤掉它自己所在请求的全部候选预算。上限可配，但必须有默认值，且截断必须可见。
2. **公式单元格**：优先取缓存值，无缓存值时写入公式字符串本身，并在 `extra` 记下该 sheet 含未求值公式的数量。绝不猜测计算结果。
3. **加密或受保护的 Office 文件**：直接按解析失败处理，原因写明是加密，不做口令尝试。

### 3.5 OCR 的接入方式

`ingest/ocr.py` 定义协议而不是直接绑定实现：

```python
class OcrEngine(Protocol):
    name: str
    def text_from_image(self, image: bytes) -> tuple[str, float | None]: ...
```

触发条件有两条：图片后缀直接进 OCR；PDF 在 Docling 与 `pypdf` 两条路都产出低于每页阈值的字符数时，判定为扫描版，逐页渲染后进 OCR。渲染与识别都要在 `extra["ocr"]` 里留下引擎名、页数与可得的平均置信度。

引擎选型是**待定的开放问题**，不在本稿拍板。硬约束是：Windows 上必须能纯 `pip` 安装，且中文识别可用。候选与取舍记录在 §9。选型前先做一次 spike，用同一份中文扫描样本量三个候选的字符准确率与单页耗时。

### 3.6 错误处理

沿用既有契约：解析异常不抛出到调用方，而是变成 `IngestOutcome(status="failed", detail=...)`（`ingester.py:115-118`）。新增三类可分辨的原因字符串：`encrypted`、`ocr_unavailable`（引擎未安装）、`image_unreadable`。OCR 引擎缺失时行为是失败而不是静默跳过，因为静默跳过会让用户以为扫描件已经进库。

## 4. 数据模型与迁移

**无 schema 变更**。所有新信息进 `DS-1 documents.extra` JSONB，沿用 F6 分支已验证的零迁移路径。

新增键：

| 键 | 内容 |
|---|---|
| `extra["parser"]` | 已有，取值扩充为 `docx`、`xlsx`、`pptx`、`eml`、`mbox`、`ocr` |
| `extra["source_member"]` | 邮件在同一宿主文件内的成员标识 |
| `extra["truncated"]` | `{"rows": n}`，Excel 截断行数 |
| `extra["ocr"]` | `{"engine": ..., "pages": n, "mean_confidence": f}` |
| `extra["formulas_unevaluated"]` | 未求值公式数量 |

不新增迁移是本稿的刻意选择：这些是文档级的描述性元数据，不需要被索引或参与过滤。如果后续 F5 要求「按解析器筛选」，再评估是否提升为列。

### 依赖新增

`pyproject.toml` 的 optional-dependencies 增加三组，遵循仓库「重依赖一律可选」的惯例：

| extra | 内容 | 理由 |
|---|---|---|
| `office` | `python-docx`、`openpyxl`、`python-pptx` | 三者都轻，但没理由强加给只用 PDF 的项目 |
| `ocr` | OCR 引擎与 PDF 光栅化库，具体清单随 §9 的 spike 结果确定 | 引擎带模型权重，必须可选 |
| `ocr-tesseract` | `pytesseract` 加 Pillow 适配器 | 给已装系统 tesseract 的用户一条备选 |

`make setup` 与 CI 的 `uv sync` 是否带上 `office` 与 `ocr`，见 §6 的测试策略：CI 至少装 `office`，OCR 若装则必须有非跳过的测试，否则宁可不装并在稿子里声明跳过。

## 5. 改动文件清单

| 文件 | 改动 |
|---|---|
| `src/sci_rag/ingest/parsers.py` | 扩展 `SUPPORTED_SUFFIXES`；`parse_file` 增加分支；新增 `parse_file_many` |
| `src/sci_rag/ingest/office.py` | 新增，三个 Office 解析器 |
| `src/sci_rag/ingest/email_parser.py` | 新增，`parse_eml`、`parse_mbox` |
| `src/sci_rag/ingest/ocr.py` | 新增，`OcrEngine` 协议与两个适配器、扫描版判定 |
| `src/sci_rag/ingest/ingester.py` | 内层循环改为遍历 `parse_file_many` 的产出；三种新失败原因 |
| `src/sci_rag/ingest/manifest.py` | 后缀校验与 `SUPPORTED_SUFFIXES` 同步；邮件宿主不因多产出而重复 lint 报警 |
| `src/sci_rag/cli/main.py` | `doctor` 增加按解析器分类的统计；`ingest` 增加 `--no-ocr` 开关 |
| `pyproject.toml` | 三组新 extra；`uv.lock` 同步 |
| `docs/` | 新增或更新一页 how-to，并把新后缀写进 `docs/bring-your-own-domain.md` |

## 6. 测试计划

**单元测试**（`tests/unit/`）：

- 每个解析器各一组，断言块序列的形状而不只是含有文本。重点覆盖：docx 标题层级、docx 空表、xlsx 多 sheet、xlsx 超上限截断、pptx 无标题页、eml 多部分正文、mbox 三封邮件产出三个文档、图片 OCR 失败路径。
- 夹具**在测试里程序化生成**（用被测的三个库自己写文件），不提交二进制样本。理由有两条：绕过 `.pre-commit-config.yaml:21-22` 的 600 KB 提交上限，且合成样本没有许可证问题。
- OCR 用假引擎注入，断言的是协议调用与 `extra` 落盘，不是识别准确率。

**集成测试**（`tests/integration/`）：

- 一个混合目录走完整 `build`，断言文档数与 `extra["parser"]` 分类计数。
- 邮件多产出与 `C-1 文档身份` 的交互：同一 mbox 重复 ingest 应幂等。
- 加密 docx 与损坏 eml 的失败可见性。

**对抗性测试**：

- 0 字节文件、只有 BOM 的文本、超长单行 CSV、文件名含中文与空格、同名不同后缀。
- 与 F6 联动：邮件宿主文件被修改时，其成员文档的增删改如何收敛。

**必须声明的跳过**：若 CI 未安装 OCR extra，则 A1-3 无法验证，交付说明里必须写明这一项未验证，不得以「单元测试用了假引擎」充当通过证据。

## 7. 验收命令

```bash
uv sync --extra office --extra ocr
make db-up && uv run sci-rag db upgrade
uv run sci-rag build /path/to/mixed_folder
uv run sci-rag doctor            # 按解析器的成功与失败计数
uv run sci-rag stats             # 文档数、chunk 数
uv run pytest tests/unit -q -k "parser or office or email or ocr"
uv run pytest tests/integration -q -k "ingest or multi_format"
make check
```

## 8. 风险与不做的事

风险：

| 编号 | 风险 | 处置 |
|---|---|---|
| R1-1 | OneDrive 占位文件。仓库本身位于 OneDrive 同步目录，占位文件 `stat()` 能返回大小但读取会触发下载或失败，会让 `C-2 变更指纹` 误判为「未变」或让解析超时。 | 在 `SourceFingerprint.of` 附近增加占位文件检测（Windows 的文件属性位），命中的文件按「需下载」显式跳过并计数，不静默当成未变。这一项与 F6 共有。 |
| R1-2 | OCR 引入模型权重，使安装体积与首次运行时间大幅上升 | 引擎一律走 extra，默认不装；缺失时按失败处理并给出安装提示 |
| R1-3 | Excel 截断丢数据 | 上限可配、截断必须写进 `extra`、`doctor` 汇总被截断的 sheet 数 |
| R1-4 | 三个 Office 库的解析质量参差 | 每个解析器都有形状断言；不接受「抽出文本但结构全丢」的实现 |

**明确不做的事**：

- 不做 PDF 版面分析与表格重建。Docling 已有的表提取是上限，不在其上再造一套。
- 不做音视频转写。
- 不做 Office 文件的写回或格式转换，只读。
- 不做光学识别之外的图像理解（不描述图片内容，只取文字）。
- 不自动安装系统级 OCR 二进制。
- 不解析 `.doc`、`.xls`、`.ppt` 三个旧二进制格式。它们要么先由用户另存为新格式，要么单列一个后续项。

## 9. 依赖关系

**前置**：P0 清障完成（F6 分支合入），P1 的 `M-0008` 上线。本稿虽不新增迁移，但它写 `extra`，需要一个稳定的 `DS-1` 落点。

**后置**：F2 的抽取面消费本稿产出的分块；F3 的 `C-9 提及引用` 依赖邮件与 Office 正文已被正确切分；F5 的时间浏览依赖本稿写入的产物没有把时间信息吃掉（邮件日期、Office 文档属性里的修改时间）。

**开放问题（需 spike 后回填）**：

1. OCR 引擎选型：候选为 `rapidocr-onnxruntime`（纯 pip、中文可用，倾向默认）、`paddleocr`（中文最强、体积最大）、`tesseract`（需系统二进制，中文偏弱）。待定项是准确率与单页耗时的实测对比，不凭印象选择。
2. PDF 光栅化的库选型，要求不引入系统级依赖。
3. `.doc` / `.xls` / `.ppt` 是否需要，取决于用户实际语料里旧格式的占比。
