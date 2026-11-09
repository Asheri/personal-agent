"""Unit checks for geometry and explicit references without models or services."""

import math
from array import array

import pytest
from typer.testing import CliRunner

from sci_rag.cli.main import app
from sci_rag.db.models import Document
from sci_rag.relate.mentions import mention_keys, resolve_key
from sci_rag.relate.vectors import centered_cosine, mean_vector


@pytest.mark.parametrize("vectors", [[], [[]], [[1], [1, 2]], [[math.nan]], [[math.inf]]])
def test_invalid_document_vectors_are_refused(vectors):  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError):
        mean_vector(vectors)


def test_vector_sequences_and_translation_invariance():
    assert mean_vector([array("d", [1.0, 2.0]), array("d", [3.0, 4.0])]) == [2, 3]
    a, b, center = [1.0, 0.0], [0.9, 0.1], [0.0, 0.5]
    score = centered_cosine(a, b, center)

    def shifted(v):  # type: ignore[no-untyped-def]
        return [v[0] + 10, v[1] - 20]

    assert centered_cosine(shifted(a), shifted(b), shifted(center)) == pytest.approx(score)
    assert centered_cosine(center, b, center) is None


def test_only_explicit_links_and_dois_become_mention_candidates():
    content = "An incidental title is not a citation. [[Atlas Plan]] [notes](notes.md) `file.docx` DOI 10.1234/example."
    assert mention_keys(content) == ["Atlas Plan", "notes.md", "file.docx", "10.1234/example"]
    assert mention_keys("Just ordinary prose and a proper name.") == []


def test_relative_links_resolve_before_ambiguous_basenames():
    source = Document(id="source", title="Source", extra={"path": r"d:\records\one\source.md"})
    one = Document(id="one", title="Repeated", extra={"path": r"d:\records\one\target.md"})
    two = Document(id="two", title="Repeated", extra={"path": r"d:\records\two\target.md"})
    assert resolve_key("target.md", source, [one, two]) == ("one", False)
    assert resolve_key("Repeated", source, [one, two]) == (None, True)


@pytest.mark.parametrize(
    "command", ["similar", "citations", "projects", "versions", "mentions", "embeddings"]
)
def test_relation_commands_are_discoverable(command):  # type: ignore[no-untyped-def]
    assert CliRunner().invoke(app, ["relate", command, "--help"]).exit_code == 0
