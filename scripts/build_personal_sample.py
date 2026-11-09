"""Build a small synthetic personal-file corpus with provisional target labels."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from docx import Document
from pptx import Presentation


def build(directory: Path) -> None:
    rows = [
        {
            "path": "atlas/plan.md",
            "title": "Atlas Plan",
            "project": "Atlas",
            "body": "陈林负责 Atlas 项目。Atlas 项目使用知识图谱。Atlas 项目产出 Atlas实验计划。",
            "entities": [
                ["陈林", "Person"],
                ["Atlas", "Project"],
                ["知识图谱", "Technology"],
                ["Atlas实验计划", "Document"],
            ],
        },
        {
            "path": "inbox/review.docx",
            "title": "Atlas Review",
            "project": "Atlas",
            "body": "Atlas实验计划由陈林撰写。Atlas实验计划属于 Atlas 项目。陈林评审 Atlas实验计划。",
            "entities": [["陈林", "Person"], ["Atlas", "Project"], ["Atlas实验计划", "Document"]],
        },
        {
            "path": "atlas/course-note.txt",
            "title": "Horizon Notes",
            "project": "Horizon",
            "manual": True,
            "body": "Horizon 项目由王宁负责。Horizon 项目使用自然语言处理。王宁制作检索原型。",
            "entities": [
                ["Horizon", "Project"],
                ["王宁", "Person"],
                ["自然语言处理", "Technology"],
                ["检索原型", "Artifact"],
            ],
        },
        {
            "path": "horizon/slides.pptx",
            "title": "Horizon Slides",
            "project": "Horizon",
            "body": "检索原型由王宁制作。检索原型属于 Horizon 项目。Horizon 项目使用自然语言处理。",
            "entities": [
                ["Horizon", "Project"],
                ["王宁", "Person"],
                ["自然语言处理", "Technology"],
                ["检索原型", "Artifact"],
            ],
        },
        {
            "path": "inbox/reminder.txt",
            "title": "General Reminder",
            "project": None,
            "body": "例行备忘: 定期检查本地备份, 并整理已经完成的日常事项。本页没有声明任何项目归属。",
            "entities": [],
        },
        {
            "path": "inbox/unknown-rights.txt",
            "title": "Unclassified Rights",
            "project": None,
            "license_class": "unknown",
            "body": "这是一份生成的未知授权样例。其内容不应被发送给模型。",
            "entities": [],
        },
    ]
    directory.mkdir(parents=True, exist_ok=True)
    for row in rows:
        path = directory / row["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".docx":
            document = Document()
            document.add_heading(row["title"], 0)
            document.add_paragraph(row["body"])
            document.save(str(path))
        elif path.suffix == ".pptx":
            presentation = Presentation()
            slide = presentation.slides.add_slide(presentation.slide_layouts[1])
            slide.shapes.title.text = row["title"]
            slide.placeholders[1].text = row["body"]
            presentation.save(str(path))
        else:
            path.write_text(
                ("# " + row["title"] + "\n\n" if path.suffix == ".md" else "") + row["body"] + "\n",
                encoding="utf-8",
            )
    targets = {
        "status": "AI-authored provisional labels; independent human review pending",
        "license": "Synthetic text released as CC0; names are fictional",
        "scope": "Target-entity recall, ownership, and source-grounded cross-file paths; not a representative quality benchmark",
        "documents": rows,
    }
    (directory / "targets.json").write_text(
        json.dumps(targets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (directory / "project_rules.yaml").write_text(
        '- project: Atlas\n  include: ["*/atlas/*"]\n  priority: 10\n- project: Horizon\n  include: ["*/horizon/*"]\n  priority: 10\n',
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("examples/personal-files"))
    build(parser.parse_args().output)
