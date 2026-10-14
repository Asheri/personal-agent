"""Rebrand this template for your own project and domain.

This is the narrow, surgical path: it sets a name and description and resets
the seed questions, editing `domain/domain.yaml` in place so its guided
comments survive. For the full setup session (credentials, ontology, corpus,
license, stack) run the wizard instead:

    uv run sci-rag init

Shows its plan by default; nothing changes without --apply:

    uv run python scripts/init_domain.py \
        --name "Membrane Materials KB" \
        --description "Membrane chemistry and performance for water treatment" \
        --apply

The seed template and the slug rule come from ``sci_rag.scaffold`` so this
script and the wizard cannot disagree about what a reset looks like.

The Python package stays ``sci_rag`` on purpose (see ADR 0004): keeping
the import path lets you diff against, and pull improvements from, the
upstream template.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from sci_rag.scaffold.apply import SEED_TEMPLATE
from sci_rag.scaffold.naming import slugify

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="Your project's human name.")
    parser.add_argument("--description", required=True, help="One sentence about the domain.")
    parser.add_argument("--slug", help="Package/distribution slug (default: derived from name).")
    parser.add_argument("--apply", action="store_true", help="Actually write changes.")
    args = parser.parse_args()

    slug = args.slug or slugify(args.name)
    changes: list[tuple[Path, str, str]] = []

    pyproject = REPO_ROOT / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    new_text = re.sub(r'(?m)^name = ".*"$', f'name = "{slug}"', text, count=1)
    new_text = re.sub(
        r'(?m)^description = ".*"$', f'description = "{args.description}"', new_text, count=1
    )
    if new_text != text:
        changes.append((pyproject, "project name and description", new_text))

    domain_yaml = REPO_ROOT / "domain" / "domain.yaml"
    dtext = domain_yaml.read_text(encoding="utf-8")
    new_dtext = re.sub(r'(?m)^name: ".*"$', f'name: "{args.name}"', dtext, count=1)
    new_dtext = re.sub(
        r"(?ms)^description: >\n(?:  .*\n)+",
        f"description: >\n  {args.description}\n",
        new_dtext,
        count=1,
    )
    if new_dtext != dtext:
        changes.append((domain_yaml, "domain name and description", new_dtext))

    seeds = REPO_ROOT / "domain" / "eval_seed_questions.jsonl"
    if seeds.read_text(encoding="utf-8") != SEED_TEMPLATE:
        changes.append((seeds, "reset seed questions to a guided blank", SEED_TEMPLATE))

    if not changes:
        print("Nothing to change; already initialized with these values.")
        return 0

    for path, what, _ in changes:
        print(
            f"{'WILL CHANGE' if not args.apply else 'CHANGED'}: {path.relative_to(REPO_ROOT)} ({what})"
        )

    if not args.apply:
        print("\nDry run. Re-run with --apply to write these changes.")
        return 0

    for path, _, content in changes:
        path.write_text(content, encoding="utf-8")

    print(
        f"""
Done. {args.name} is set up. Next, in order:

  1. Put documents in data/raw/.
  2. uv run sci-rag draft manifest --folder data/raw
  3. uv run sci-rag draft ontology --from-corpus
  4. uv run sci-rag draft questions --count 10
  5. Rewrite README.md's opening for your project.

Steps 2 to 4 each propose a file for you to review rather than writing one,
and each also prints its prompt (--print-prompt) if you would rather paste it
into an assistant you already have, no API key needed. Guide:
docs/bring-your-own-domain.md

Prefer to type them yourself? The full schema for every file is in
docs/bring-your-own-domain.md, and nothing here requires the drafters.

For the guided version of all of that, run `uv run sci-rag init`.
"""
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
