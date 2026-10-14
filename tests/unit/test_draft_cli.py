"""`sci-rag draft` and its two lanes.

Lane A calls the configured model. Lane B renders the same prompt to stdout
for a scientist with no credentials to paste anywhere, and reads the reply
back from a file. The point of the design is that they are one path, so the
load-bearing test here is that a captured Lane A reply, replayed through
`--from-file`, produces a byte-identical file.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sci_rag.cli.main import app
from sci_rag.config import reset_settings_cache
from sci_rag.llm import MockLLM

REPO_ROOT = Path(__file__).parents[2]
runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "300"})
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(output: str) -> str:
    return _ANSI.sub("", output)


_REPLY = json.dumps(
    {
        "questions": [
            {
                "id": "drafted-rice-straw-tonnage",
                "question": "How much rice straw did the Colusa Basin generate in 2023?",
                "reference_answer": "About 302,000 dry tons across roughly 141,000 acres.",
                "reference_titles": ["Colusa Basin Rice Straw Assessment"],
                "evidence_phrases": ["302,000 dry tons"],
                "tags": ["availability"],
            },
            {
                "id": "drafted-switchgrass-probe",
                "question": "What sugar yield does enzymatic hydrolysis of switchgrass reach?",
                "reference_answer": "The corpus does not cover switchgrass; say so.",
                "reference_titles": [],
                "evidence_phrases": [],
                "tags": ["unanswerable"],
            },
        ]
    }
)


#: Two short documents, small enough that sampling takes every passage. A
#: reply can then quote them and the grounding check has a known answer,
#: which the shipped demo fixture (long enough to be sampled selectively)
#: could not give without pinning the sampler's internals.
_RICE = """# Colusa Basin Rice Straw Assessment

The Colusa Basin generated 302,000 dry tons of rice straw during the 2023
season, harvested from roughly 141,000 acres of irrigated rice ground.

Of that total, about 88,000 dry tons were baled and removed from the field,
while the remainder was chopped and incorporated during the winter flood.
"""

_ALMOND = """# Almond Pruning Logistics

Mature almond blocks average 0.9 dry tons of prunings per acre per year, and
blocks between sixteen and twenty five years old run closer to 1.1 dry tons.

Chipping and roadside handling averaged 19 dollars per dry ton in 2023, with
transport adding 0.32 dollars per dry ton-mile to the delivered cost.
"""


def _project(tmp_path: Path) -> Path:
    """A scratch project: the shipped domain profile and two raw documents."""
    root = tmp_path / "project"
    shutil.copytree(REPO_ROOT / "domain", root / "domain")
    raw = root / "data" / "raw"
    raw.mkdir(parents=True)
    (raw / "colusa-rice-straw.md").write_text(_RICE, encoding="utf-8")
    (raw / "almond-prunings.md").write_text(_ALMOND, encoding="utf-8")
    return root


#: A port nothing listens on, so the corpus lane fails fast and the file
#: fallback is what actually runs. Unit tests stay database-free by design,
#: and a sibling checkout's Postgres must not decide the outcome here.
_NO_DATABASE = "postgresql+asyncpg://sci_rag:sci_rag@127.0.0.1:1/absent"


def _offline_project(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from sci_rag.db import dispose_engine

    monkeypatch.chdir(root)
    monkeypatch.setenv("SCI_RAG_DOMAIN_DIR", str(root / "domain"))
    monkeypatch.setenv("SCI_RAG_DATA_DIR", str(root / "data"))
    monkeypatch.setenv("SCI_RAG_DATABASE_URL", _NO_DATABASE)
    reset_settings_cache()
    asyncio.run(dispose_engine())


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    root = _project(tmp_path)
    _offline_project(root, monkeypatch)
    yield root
    reset_settings_cache()


def _mock_llm(monkeypatch: pytest.MonkeyPatch, responses: list[str]) -> MockLLM:
    llm = MockLLM(responses=list(responses))
    monkeypatch.setattr("sci_rag.llm.get_llm", lambda *a, **k: llm)
    return llm


def _forbid_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("this lane must not reach for a model")

    monkeypatch.setattr("sci_rag.llm.get_llm", _boom)


def test_the_group_is_registered() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "draft" in _plain(result.output)


def test_help_screens_render() -> None:
    for args in (["draft", "--help"], ["draft", "questions", "--help"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, f"{args}: {result.output}"


def test_documented_flags_exist() -> None:
    help_text = _plain(runner.invoke(app, ["draft", "questions", "--help"]).output)
    for flag in ("--count", "--folder", "--print-prompt", "--from-file", "--apply", "--dry-run"):
        assert flag in help_text


def test_print_prompt_emits_the_prompt_and_calls_no_model(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_llm(monkeypatch)

    result = runner.invoke(app, ["draft", "questions", "--count", "5", "--print-prompt"])

    assert result.exit_code == 0, result.output
    printed = _plain(result.output)
    assert "302,000 dry tons" in printed, "the prompt must carry real passage text"
    assert "Feedstock" in printed, "the prompt must carry the ontology"
    assert not (project / "domain" / "eval_seed_questions.jsonl.proposed").exists()


def test_print_prompt_puts_nothing_but_the_prompt_on_stdout(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The documented lane is `--print-prompt > prompt.txt`, so status chatter
    on stdout would be pasted into the assistant along with the prompt."""
    _forbid_llm(monkeypatch)

    result = runner.invoke(app, ["draft", "questions", "--count", "5", "--print-prompt"])

    assert result.exit_code == 0, result.output
    stdout = _plain(result.stdout)
    assert stdout.startswith("You are helping a scientist")
    assert "No usable ingested corpus" not in stdout
    # The fallback did happen; it just went where diagnostics belong.
    assert "No usable ingested corpus" in _plain(result.stderr)


def test_a_draft_proposes_a_file_rather_than_overwriting_the_seed_set(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_file = project / "domain" / "eval_seed_questions.jsonl"
    before = seed_file.read_bytes()
    _mock_llm(monkeypatch, [_REPLY])

    result = runner.invoke(app, ["draft", "questions", "--count", "2", "--no-repair"])

    assert result.exit_code == 0, result.output
    proposed = seed_file.with_suffix(".jsonl.proposed")
    assert proposed.exists()
    assert seed_file.read_bytes() == before, "the reviewed seed set is never overwritten"
    assert "drafted-rice-straw-tonnage" in proposed.read_text(encoding="utf-8")


def test_dry_run_writes_nothing(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_llm(monkeypatch, [_REPLY])

    result = runner.invoke(app, ["draft", "questions", "--count", "2", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert not (project / "domain" / "eval_seed_questions.jsonl.proposed").exists()


def test_apply_appends_to_the_seed_set_and_keeps_what_was_there(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sci_rag.evals.seeds import DRAFTED_TAG, load_seed_questions

    seed_file = project / "domain" / "eval_seed_questions.jsonl"
    existing = [q.id for q in load_seed_questions(seed_file)]
    _mock_llm(monkeypatch, [_REPLY])

    result = runner.invoke(app, ["draft", "questions", "--count", "2", "--apply", "--no-repair"])

    assert result.exit_code == 0, result.output
    after = load_seed_questions(seed_file)
    ids = [q.id for q in after]
    assert ids[: len(existing)] == existing, "hand-written ground truth is never dropped"
    drafted = {q.id for q in after if DRAFTED_TAG in q.tags}
    assert drafted == {"drafted-rice-straw-tonnage", "drafted-switchgrass-probe"}
    assert not any(DRAFTED_TAG in q.tags for q in after[: len(existing)])


def test_the_summary_says_where_the_passages_came_from(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_llm(monkeypatch, [_REPLY])

    result = runner.invoke(app, ["draft", "questions", "--count", "2", "--dry-run"])

    assert "data/raw" in _plain(result.output)


def test_from_file_reproduces_lane_a_byte_for_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of Lane B: same prompt, same validator, same bytes."""
    lane_a = _project(tmp_path / "a")
    lane_b = _project(tmp_path / "b")

    _offline_project(lane_a, monkeypatch)
    _mock_llm(monkeypatch, [_REPLY])
    a = runner.invoke(app, ["draft", "questions", "--count", "2", "--no-repair"])
    assert a.exit_code == 0, a.output

    reply_file = tmp_path / "reply.json"
    reply_file.write_text(_REPLY, encoding="utf-8")

    _offline_project(lane_b, monkeypatch)
    _forbid_llm(monkeypatch)
    b = runner.invoke(app, ["draft", "questions", "--count", "2", "--from-file", str(reply_file)])
    assert b.exit_code == 0, b.output

    produced_a = (lane_a / "domain" / "eval_seed_questions.jsonl.proposed").read_bytes()
    produced_b = (lane_b / "domain" / "eval_seed_questions.jsonl.proposed").read_bytes()
    assert produced_a == produced_b
    reset_settings_cache()


def test_an_ungrounded_row_is_reported_not_silently_dropped(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reply = json.dumps(
        {
            "questions": [
                {
                    "id": "invented",
                    "question": "How much switchgrass?",
                    "reference_answer": "Nine hundred tons.",
                    "reference_titles": ["Colusa Basin Rice Straw Assessment"],
                    "evidence_phrases": ["900 dry tons of switchgrass"],
                    "tags": ["availability"],
                }
            ]
        }
    )
    _mock_llm(monkeypatch, [reply, reply])

    result = runner.invoke(app, ["draft", "questions", "--count", "1", "--no-repair"])

    output = _plain(result.output)
    assert "invented" in output
    assert "900 dry tons of switchgrass" in output


def test_a_reply_that_is_not_json_fails_loudly(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_llm(monkeypatch, ["I cannot help with that."])

    result = runner.invoke(app, ["draft", "questions", "--count", "2", "--no-repair"])

    assert result.exit_code != 0
    assert "JSON" in _plain(result.output)


def test_apply_skips_a_drafted_row_whose_id_is_already_taken(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The seed file is the expert's; a drafted row never overwrites one."""
    from sci_rag.evals.seeds import load_seed_questions

    seed_file = project / "domain" / "eval_seed_questions.jsonl"
    collision = json.dumps(
        {
            "questions": [
                {
                    "id": "rice-straw-generated",
                    "question": "How much rice straw did the Colusa Basin generate in 2023?",
                    "reference_answer": "About 302,000 dry tons.",
                    "reference_titles": ["Colusa Basin Rice Straw Assessment"],
                    "evidence_phrases": ["302,000 dry tons"],
                    "tags": ["availability"],
                }
            ]
        }
    )
    before = load_seed_questions(seed_file)
    _mock_llm(monkeypatch, [collision])

    result = runner.invoke(app, ["draft", "questions", "--count", "1", "--apply", "--no-repair"])

    assert result.exit_code == 0, result.output
    after = load_seed_questions(seed_file)
    assert [q.id for q in after] == [q.id for q in before]
    assert "rice-straw-generated" in _plain(result.output)


# --- draft manifest and draft ontology, through the same two lanes ----------

_MANIFEST_REPLY = json.dumps(
    {
        "source_buckets": ["field_notes"],
        "documents": [
            {
                "filename": "colusa-rice-straw.md",
                "title": "Colusa Basin Rice Straw Assessment",
                "authors": ["Demo Region Biomass Office"],
                "year": 2023,
                "source": "field_notes",
                "license_class": "public",
            },
            {
                "filename": "almond-prunings.md",
                "title": "Almond Pruning Logistics",
                "year": 2023,
                "source": "field_notes",
            },
        ],
    }
)

_ONTOLOGY_REPLY = json.dumps(
    {
        "entity_types": [
            {"name": "Feedstock", "description": "A residue stream"},
            {"name": "Region", "description": "A geographic area"},
            {"name": "Property", "description": "A measured characteristic"},
        ],
        "relation_types": [{"name": "LOCATED_IN", "description": "Grown or collected in"}],
        "query_classes": [
            {
                "name": "availability",
                "keywords": ["tons"],
                "hyde_instruction": "Write a resource assessment passage.",
            }
        ],
    }
)


def test_the_new_commands_are_registered() -> None:
    for args in (["draft", "manifest", "--help"], ["draft", "ontology", "--help"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, f"{args}: {result.output}"


def test_manifest_flags_exist() -> None:
    help_text = _plain(runner.invoke(app, ["draft", "manifest", "--help"]).output)
    for flag in ("--folder", "--print-prompt", "--from-file", "--apply", "--dry-run", "--output"):
        assert flag in help_text


def test_ontology_flags_exist() -> None:
    help_text = _plain(runner.invoke(app, ["draft", "ontology", "--help"]).output)
    for flag in ("--from-corpus", "--refine", "--cold", "--print-prompt", "--from-file", "--apply"):
        assert flag in help_text


def test_manifest_never_writes_a_license_class_the_model_asserted(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sci_rag.ingest.manifest import load_manifest

    _mock_llm(monkeypatch, [_MANIFEST_REPLY])

    result = runner.invoke(app, ["draft", "manifest", "--folder", str(project / "data" / "raw")])

    assert result.exit_code == 0, result.output
    proposed = project / "data" / "corpus.jsonl.proposed"
    assert proposed.exists()
    entries = load_manifest(proposed)
    assert {e.path.name for e in entries} == {"colusa-rice-straw.md", "almond-prunings.md"}
    assert all(e.license_class == "unknown" for e in entries)
    assert "rights decision" in _plain(result.output)


def test_manifest_print_prompt_puts_nothing_but_the_prompt_on_stdout(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_llm(monkeypatch)

    result = runner.invoke(
        app,
        ["draft", "manifest", "--folder", str(project / "data" / "raw"), "--print-prompt"],
    )

    assert result.exit_code == 0, result.output
    stdout = _plain(result.stdout)
    assert "colusa-rice-straw.md" in stdout
    assert "302,000 dry tons" in stdout


def test_manifest_from_file_reproduces_lane_a_byte_for_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lane_a = _project(tmp_path / "ma")
    lane_b = _project(tmp_path / "mb")

    _offline_project(lane_a, monkeypatch)
    _mock_llm(monkeypatch, [_MANIFEST_REPLY])
    a = runner.invoke(app, ["draft", "manifest", "--folder", str(lane_a / "data" / "raw")])
    assert a.exit_code == 0, a.output

    reply_file = tmp_path / "manifest-reply.json"
    reply_file.write_text(_MANIFEST_REPLY, encoding="utf-8")

    _offline_project(lane_b, monkeypatch)
    _forbid_llm(monkeypatch)
    b = runner.invoke(
        app,
        [
            "draft",
            "manifest",
            "--folder",
            str(lane_b / "data" / "raw"),
            "--from-file",
            str(reply_file),
        ],
    )
    assert b.exit_code == 0, b.output

    produced_a = (lane_a / "data" / "corpus.jsonl.proposed").read_text(encoding="utf-8")
    produced_b = (lane_b / "data" / "corpus.jsonl.proposed").read_text(encoding="utf-8")
    # Paths are absolute per scratch project, so compare everything else.
    assert produced_a.replace(str(lane_a), "") == produced_b.replace(str(lane_b), "")
    reset_settings_cache()


def test_ontology_proposes_a_file_and_keeps_the_tuned_blocks(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import yaml

    from sci_rag.domain import load_domain

    domain_yaml = project / "domain" / "domain.yaml"
    untouched = domain_yaml.read_bytes()
    before = load_domain(project / "domain").config
    _mock_llm(monkeypatch, [_ONTOLOGY_REPLY])

    result = runner.invoke(
        app,
        ["draft", "ontology", "--from-corpus", "--folder", str(project / "data" / "raw")],
    )

    assert result.exit_code == 0, result.output
    proposed = domain_yaml.with_name("domain.yaml.proposed")
    assert proposed.exists()
    assert domain_yaml.read_bytes() == untouched, "a proposal never edits domain.yaml"
    raw = yaml.safe_load(proposed.read_text(encoding="utf-8"))
    assert [e["name"] for e in raw["entity_types"]] == ["Feedstock", "Region", "Property"]
    assert raw["retrieval"]["weights"] == before.retrieval.weights
    assert raw["retrieval"]["rrf_k"] == before.retrieval.rrf_k


def test_ontology_apply_writes_in_place(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sci_rag.domain import load_domain

    _mock_llm(monkeypatch, [_ONTOLOGY_REPLY])

    result = runner.invoke(
        app,
        [
            "draft",
            "ontology",
            "--from-corpus",
            "--folder",
            str(project / "data" / "raw"),
            "--apply",
        ],
    )

    assert result.exit_code == 0, result.output
    after = load_domain(project / "domain").config
    assert [e.name for e in after.entity_types] == ["Feedstock", "Region", "Property"]


def test_ontology_cold_needs_no_corpus(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--cold is the wizard's behaviour: description only, no documents."""
    llm = _mock_llm(monkeypatch, [_ONTOLOGY_REPLY])

    result = runner.invoke(app, ["draft", "ontology", "--cold", "--dry-run"])

    assert result.exit_code == 0, result.output
    output = _plain(result.output)
    assert "Grounded in" not in output, "the cold lane reads no documents at all"
    assert "Resulting ontology: Feedstock, Region, Property" in output
    assert "302,000" not in llm.calls[0]["prompt"], "no passage reached the cold prompt"


# --- draft prompts: narrow by construction ---------------------------------


def test_the_prompts_command_is_registered() -> None:
    result = runner.invoke(app, ["draft", "prompts", "--help"])
    assert result.exit_code == 0, result.output
    help_text = _plain(result.output)
    for flag in ("--print-prompt", "--from-file", "--apply", "--dry-run"):
        assert flag in help_text


@pytest.mark.parametrize(
    "name", ["judge_grounding", "judge_correctness", "snippet_compression", "ontology_draft"]
)
def test_the_refused_prompts_are_refused_by_name(
    project: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    _forbid_llm(monkeypatch)

    result = runner.invoke(app, ["draft", "prompts", name])

    assert result.exit_code != 0
    output = _plain(result.output)
    assert name in output
    assert not (project / "domain" / "prompts" / f"{name}.md.proposed").exists()


def test_a_rewrite_that_drops_a_slot_is_refused(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_llm(monkeypatch, [json.dumps({"prompt": "Extract entities from $PASSAGES."})])

    result = runner.invoke(app, ["draft", "prompts", "entity_extraction"])

    assert result.exit_code != 0
    assert "ENTITY_TYPES" in _plain(result.output)
    assert not (project / "domain" / "prompts" / "entity_extraction.md.proposed").exists()


def test_a_valid_rewrite_is_proposed_not_applied(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = (project / "domain" / "prompts" / "entity_extraction.md").read_text(encoding="utf-8")
    reworded = original.replace("knowledge graph", "knowledge network")
    _mock_llm(monkeypatch, [json.dumps({"prompt": reworded})])

    result = runner.invoke(app, ["draft", "prompts", "entity_extraction"])

    assert result.exit_code == 0, result.output
    proposed = project / "domain" / "prompts" / "entity_extraction.md.proposed"
    assert proposed.read_text(encoding="utf-8") == reworded
    assert (project / "domain" / "prompts" / "entity_extraction.md").read_text(
        encoding="utf-8"
    ) == original


def test_prompts_print_prompt_carries_the_current_text_and_calls_no_model(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_llm(monkeypatch)

    result = runner.invoke(app, ["draft", "prompts", "answer", "--print-prompt"])

    assert result.exit_code == 0, result.output
    stdout = _plain(result.stdout)
    assert "$QUESTION" in stdout or "$SOURCES" in stdout, "the slots to keep are named"
    assert "answer" in stdout
