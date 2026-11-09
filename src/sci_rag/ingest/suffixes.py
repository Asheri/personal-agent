"""One discovery whitelist; drafting intentionally keeps its narrower subset."""

CODE_SUFFIXES = frozenset(
    {
        ".py",
        ".pyi",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".sh",
        ".bash",
        ".ps1",
        ".sql",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".java",
        ".go",
        ".rs",
    }
)
DATA_SUFFIXES = frozenset({".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml"})
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"})
SUPPORTED_SUFFIXES = (
    {
        ".pdf",
        ".md",
        ".markdown",
        ".txt",
        ".html",
        ".htm",
        ".docx",
        ".pptx",
        ".xlsx",
        ".eml",
        ".mbox",
    }
    | CODE_SUFFIXES
    | DATA_SUFFIXES
    | IMAGE_SUFFIXES
)


def parser_for_suffix(suffix: str) -> str:
    suffix = suffix.lower()
    if suffix in CODE_SUFFIXES:
        return "code"
    if suffix in IMAGE_SUFFIXES:
        return "ocr_image"
    return {
        ".pdf": "pdf",
        ".md": "markdown",
        ".markdown": "markdown",
        ".htm": "html",
        ".txt": "text",
        ".yml": "yaml",
    }.get(suffix, suffix.lstrip(".") or "unknown")
