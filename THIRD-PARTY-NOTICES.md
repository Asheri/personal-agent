# Third-party notices

This repository contains code copied from two upstream projects. The knowledge
base carries BSD-3-Clause; the copied Agent memory face carries MIT. Both are
recorded here so a redistributor can tell which terms apply where, and so a
reader can check the copy against its origin.

## Sci RAG Kit

- Upstream: <https://github.com/sustainability-software-lab/sci-rag-kit>
- Version: tag `v0.5.0`, commit `298d2b7892d8a3db52a98b08827e0603650bad21`
- License: BSD 3-Clause, Copyright (c) 2026, the sci-rag-kit contributors
- Copied: the `src/sci_rag/` knowledge base, the `domain/` demo profile,
  Alembic revisions `0001` to `0007`, most of `docs/`, the test suite, the
  `Makefile`, `Dockerfile`, and `pyproject.toml`. Many of these files were
  edited after the copy; [README.md](README.md) and
  [MIGRATION.md](MIGRATION.md) say which parts.
- Full license text: [LICENSE](LICENSE)
- How the version was identified: `pyproject.toml` and
  `src/sci_rag/retrieve/retriever.py` differ from tag `v0.5.0` only by this
  project's own additions, so the copy predates no upstream tag and follows
  none.

## GenericAgent

- Upstream: <https://github.com/lsdefine/GenericAgent>
- License: MIT. GitHub reports MIT for the repository.
- **The pinned commit does not resolve.** `MIGRATION.md` and
  `scripts/prepare_agent_fixture.py` name
  `a9a36b4b219593369de01c3e5973e56ac02a568b`. That object is not present in
  the public repository as of 2026-11-09, and no license file appears anywhere
  in the history reachable today. Treat the MIT grant as reported by the
  upstream project and confirm it with upstream maintainers before
  redistributing this code under another name.
- Copied verbatim (the plugin bus and the memory seeds, no runtime):

  | File | git blob SHA-1 of the local copy |
  |---|---|
  | `plugins/hooks.py` | `655fa3773fe39f0d9bfceeeceebd1db863832dc1` |
  | `plugins/project_mode.py` | `19b1df100f5656d0c1a3166f0441ba65dcd67b02` |
  | `memory/memory_management_sop.md` | `c9782d70b072a00a5c4284dd62c57c1671bb3560` |
  | `memory/insight_fixed_structure.txt` | `99d908efd732364e423b82c6cf7f71ca165f5cab` |
  | `memory/insight_fixed_structure_en.txt` | `c19d8bb5c6f58114dd3632bb3a6d75c8692cff05` |
  | `memory/global_mem_insight_template.txt` | `ebb88c55201d0400df8db7ffbd7ae3d53975ef21` |
  | `memory/global_mem_insight_template_en.txt` | `04018121c572d105367388c15a89fe4dedb79a0b` |

  A blob hash is content addressable. If you obtain a copy of the upstream
  tree, compare these hashes to confirm the files match without needing the
  missing commit.
- Not copied: the Agent runtime. `agentmain.py`, `ga.py`, `agent_loop.py`,
  `llmcore.py`, and `reflect/scheduler.py` stay external, and
  `scripts/prepare_agent_fixture.py` downloads them only for an isolated
  protocol check.

### MIT license text

```text
MIT License

Copyright (c) the GenericAgent contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

The copyright line above is a placeholder: the upstream tree at the pinned
commit carries no license file to copy it from. Replace it with the exact
line upstream publishes before distributing this work publicly.

## Python dependencies

Dependencies installed from `pyproject.toml` and `uv.lock` keep their own
licenses. They are not vendored, so their notices are not reproduced here. Run
`uv run pip-licenses` or read each package's metadata for the current set.
