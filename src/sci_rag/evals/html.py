"""One HTML file per eval run, for the collaborator who will never open a terminal.

The JSON payload is for machines and the Markdown report is for whoever
already has the repository checked out. Neither travels well. A domain
expert asked to sanity-check ten judged answers should not have to be
talked through cloning anything, and a table pasted into email loses the
confidence intervals that were the reason to trust it.

Two constraints follow from that audience and shape everything here.

**Self-contained.** Inline styles, no fonts, no scripts, no images. A
page that fetches anything renders differently for the recipient than for
the sender, and eventually renders as nothing behind a firewall. The
tests assert the absence rather than trusting the intent.

**The caveats travel with the numbers.** The Markdown reports put the
small-sample and drafted-ground-truth warnings next to the metric on
purpose. A prettier view that drops them is worse than no view, because
it makes an unreliable number look considered. The same reasoning puts
the provenance receipt at the top: a reader who cannot run the command
has no other way to find out which model produced what they are reading.

The one piece of interpretation this file adds is marking which
comparisons the sample size can actually support. Overlapping confidence
intervals are the most common way an ablation table gets misread, and
colour is a cheaper way to say so than a paragraph nobody reads.
"""

from __future__ import annotations

import html
from typing import Any

from sci_rag.evals.stats import SMALL_N

# Deliberately boring. The palette carries three meanings (hit, miss, and
# "not distinguishable from baseline") and nothing else, and it has to stay
# legible printed in grayscale, since that is what happens to a page sent
# to someone who prints things.
STYLESHEET = """
:root { color-scheme: light; }
body { font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto,
       Helvetica, Arial, sans-serif; line-height: 1.5; margin: 0 auto; max-width: 60rem;
       padding: 2rem 1.25rem 4rem; color: #16191d; background: #fff; }
h1 { font-size: 1.6rem; margin-bottom: 0.25rem; }
h2 { font-size: 1.15rem; margin-top: 2.25rem; border-bottom: 1px solid #d7dbe0;
     padding-bottom: 0.3rem; }
h3 { font-size: 1rem; margin-top: 1.5rem; }
code, .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
              font-size: 0.86em; }
table { border-collapse: collapse; width: 100%; margin: 0.75rem 0 1.25rem; font-size: 0.9rem; }
th, td { border: 1px solid #d7dbe0; padding: 0.35rem 0.55rem; text-align: left;
         vertical-align: top; }
th { background: #f2f4f6; font-weight: 600; }
td.num, th.num { text-align: right; white-space: nowrap; }
.receipt { background: #f7f8fa; border: 1px solid #d7dbe0; border-radius: 6px;
           padding: 0.75rem 1rem; margin: 1rem 0 1.5rem; font-size: 0.88rem; }
.receipt dl { display: grid; grid-template-columns: max-content 1fr; gap: 0.2rem 0.9rem;
              margin: 0; }
.receipt dt { font-weight: 600; }
.receipt dd { margin: 0; }
.warning { border-left: 4px solid #a8730a; background: #fdf6e7; padding: 0.6rem 0.9rem;
           margin: 1rem 0; font-size: 0.9rem; }
.row--hit td:first-child { border-left: 4px solid #1c7c4a; }
.row--miss td:first-child { border-left: 4px solid #a32b2b; }
.row--miss { background: #fdf1f1; }
.cell--overlaps { background: #f2f4f6; color: #4a5158; }
.cell--distinct { font-weight: 600; }
.legend { font-size: 0.84rem; color: #4a5158; margin: 0.4rem 0 1rem; }
.answer { white-space: pre-wrap; font-size: 0.88rem; }
.rationale { color: #4a5158; font-size: 0.85rem; }
footer { margin-top: 3rem; font-size: 0.82rem; color: #4a5158;
         border-top: 1px solid #d7dbe0; padding-top: 0.75rem; }
"""


def _e(value: Any) -> str:
    """Escape anything on its way into markup.

    Answer text and judge rationales are model output, so they are data.
    A model that emits a tag gets it shown, not applied.
    """
    return html.escape("" if value is None else str(value), quote=True)


def _fmt(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return "-" if value is None else ("yes" if value else "no")
    if isinstance(value, float):
        return f"{value:.2f}" if abs(value) < 1000 else f"{value:.0f}"
    return str(value)


def _ci_text(ci: dict[str, float] | None) -> str:
    if not ci:
        return "-"
    return f"{ci['mean']:.2f} [{ci['lo']:.2f}, {ci['hi']:.2f}]"


def _overlaps(left: dict[str, float] | None, right: dict[str, float] | None) -> bool:
    """Do two intervals share any ground?

    If they do, the sample cannot tell the two configurations apart on that
    metric, whatever the means look like.
    """
    if not left or not right:
        return False
    return left["lo"] <= right["hi"] and right["lo"] <= left["hi"]


def _receipt(payload: dict[str, Any]) -> str:
    provenance = payload.get("provenance") or {}
    models = provenance.get("models") or payload.get("models") or {}
    decoding = provenance.get("decoding") or {}
    corpus = payload.get("corpus") or {}
    digest = str(provenance.get("domain_digest") or "")

    rows: list[tuple[str, str]] = [
        ("Run", f"{payload.get('kind', 'unknown')}, generated {payload.get('generated_at', '')}"),
        ("Code", f"commit {payload.get('git_commit') or 'unknown'}"),
        ("Corpus snapshot", str(payload.get("snapshot") or "not recorded")),
        (
            "Corpus",
            ", ".join(
                f"{corpus.get(key)} {key}"
                for key in ("documents", "chunks", "entities", "relationships", "communities")
                if corpus.get(key) is not None
            )
            or "not recorded",
        ),
        ("Embedding", str(provenance.get("embedding") or "not recorded")),
        (
            "Models",
            ", ".join(f"{role} {spec}" for role, spec in sorted(models.items())) or "not recorded",
        ),
        ("Domain and prompts", digest[:12] or "not recorded"),
    ]
    if decoding:
        rows.append(
            ("Decoding", ", ".join(f"{key} {value}" for key, value in sorted(decoding.items())))
        )
    items = "".join(
        f"<dt>{_e(label)}</dt><dd class='mono'>{_e(value)}</dd>" for label, value in rows
    )
    return f"<div class='receipt'><dl>{items}</dl></div>"


def _warnings(payload: dict[str, Any], n: int) -> str:
    blocks = []
    if 0 < n < SMALL_N:
        blocks.append(
            f"<div class='warning'><strong>n={n} is a small sample.</strong> The 95% "
            "intervals are wide by construction. Differences whose intervals overlap "
            "are noise, not findings.</div>"
        )
    ground_truth = payload.get("ground_truth") or {}
    drafted = int(ground_truth.get("drafted") or 0)
    total = drafted + int(ground_truth.get("reviewed") or 0)
    if drafted > 0:
        blocks.append(
            f"<div class='warning'><strong>{drafted} of {total} seed questions are "
            "model-drafted</strong> and have not been reviewed by a domain expert, so "
            "every metric here is provisional. Check each question against the document "
            "it cites, then remove its <code>drafted</code> tag.</div>"
        )
    return "".join(blocks)


def _retrieval_sections(payload: dict[str, Any]) -> tuple[str, int]:
    configs = payload.get("configs") or []
    if not configs:
        return "<p>No ablation configurations in this report.</p>", 0

    metrics = [key for key in (configs[0].get("metrics_ci") or {}) if key != "n"]
    baseline = configs[0]
    baseline_ci = baseline.get("metrics_ci") or {}
    n = int(baseline_ci.get("n") or baseline.get("metrics", {}).get("n") or 0)

    header = "".join(f"<th class='num'>{_e(metric)}</th>" for metric in metrics)
    rows = []
    for index, config in enumerate(configs):
        ci_map = config.get("metrics_ci") or {}
        cells = []
        for metric in metrics:
            ci = ci_map.get(metric)
            if index == 0:
                css = "num"
            elif _overlaps(ci, baseline_ci.get(metric)):
                css = "num cell--overlaps"
            else:
                css = "num cell--distinct"
            cells.append(f"<td class='{css}'>{_e(_ci_text(ci))}</td>")
        rows.append(
            f"<tr><td><code>{_e(config.get('name'))}</code><br>"
            f"<span class='rationale'>{_e(config.get('description'))}</span></td>"
            f"{''.join(cells)}"
            f"<td class='num'>{_e(int(ci_map.get('n') or 0))}</td></tr>"
        )

    # The comparison legend only makes sense when there is something to
    # compare against. A single-config report has a baseline and nothing else,
    # so explaining the shading there would describe marks the page never uses.
    if len(configs) > 1:
        legend = (
            "<p class='legend'>Cells are mean [95% bootstrap CI]. A "
            "<span class='cell--overlaps'>shaded cell</span> has an interval overlapping "
            f"<code>{_e(baseline.get('name'))}</code>, so this sample cannot tell the two "
            "apart on that metric. A <span class='cell--distinct'>bold cell</span> is a "
            "move the interval supports.</p>"
        )
    else:
        legend = "<p class='legend'>Cells are mean [95% bootstrap CI].</p>"
    table = (
        f"<h2>Retrieval ablations</h2>{legend}<table><thead><tr><th>Config</th>{header}"
        f"<th class='num'>n</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )

    detail = ["<h2>Per question</h2>"]
    for config in configs:
        detail.append(f"<h3><code>{_e(config.get('name'))}</code></h3>")
        body = []
        for record in config.get("records") or []:
            hit = bool(record.get("hit_at_5"))
            rank = record.get("first_relevant_rank")
            degraded = ", ".join(record.get("degraded_stages") or []) or "-"
            body.append(
                f"<tr class='{'row--hit' if hit else 'row--miss'}'>"
                f"<td><code>{_e(record.get('question_id'))}</code></td>"
                f"<td class='num'>{_e('miss' if rank is None else rank)}</td>"
                f"<td class='num'>{_e(_fmt(record.get('hit_at_5')))}</td>"
                f"<td class='num'>{_e(_fmt(record.get('hit_at_10')))}</td>"
                f"<td class='num'>{_e(record.get('retrieved'))}</td>"
                f"<td>{_e(degraded)}</td></tr>"
            )
        detail.append(
            "<table><thead><tr><th>Question</th><th class='num'>First relevant rank</th>"
            "<th class='num'>hit@5</th><th class='num'>hit@10</th>"
            "<th class='num'>Retrieved</th><th>Degraded stages</th></tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table>"
        )
    return table + "".join(detail), n


def _answers_sections(payload: dict[str, Any]) -> tuple[str, int]:
    summary = payload.get("summary") or {}
    summary_ci = payload.get("summary_ci") or {}
    n = int(summary.get("n") or 0)

    rows = "".join(
        f"<tr><td>{_e(dimension)}</td><td class='num'>{_e(_ci_text(ci))}</td>"
        f"<td class='num'>{_e(int(ci.get('n') or 0))}</td></tr>"
        for dimension, ci in sorted(summary_ci.items())
    )
    counters = "".join(
        f"<tr><td>{_e(key)}</td><td class='num'>{_e(_fmt(value))}</td></tr>"
        for key, value in sorted(summary.items())
        if key.endswith(("_median", "graded", "failed"))
    )
    section = (
        "<h2>Judged answers</h2>"
        "<table><thead><tr><th>Dimension</th><th class='num'>Mean [95% CI]</th>"
        f"<th class='num'>n</th></tr></thead><tbody>{rows}</tbody></table>"
        "<table><thead><tr><th>Counter</th><th class='num'>Value</th></tr></thead>"
        f"<tbody>{counters}</tbody></table>"
    )

    detail = ["<h2>Per question</h2>"]
    for record in payload.get("records") or []:
        grounding = record.get("grounding") or {}
        correctness = record.get("correctness") or {}
        failed = record.get("error") or not grounding
        scores = ", ".join(
            f"{key} {grounding[key]}"
            for key in ("groundedness", "citation_accuracy", "completeness")
            if key in grounding
        )
        if "correctness" in correctness:
            scores = f"{scores}, correctness {correctness['correctness']}" if scores else ""
        detail.append(
            f"<table class='{'row--miss' if failed else 'row--hit'}'>"
            f"<tbody><tr class='{'row--miss' if failed else 'row--hit'}'>"
            f"<th>Question</th><td><code>{_e(record.get('question_id'))}</code> "
            f"<span class='rationale'>{_e(', '.join(record.get('tags') or []))}</span></td></tr>"
            f"<tr><th>Scores</th><td>{_e(scores or 'not graded')}</td></tr>"
            f"<tr><th>Citations</th><td>{_e(record.get('cited_count'))} cited of "
            f"{_e(record.get('source_count'))} sources</td></tr>"
            f"<tr><th>Answer</th><td class='answer'>{_e(record.get('answer_text'))}</td></tr>"
            f"<tr><th>Grounding rationale</th>"
            f"<td class='rationale'>{_e(grounding.get('rationale'))}</td></tr>"
            f"<tr><th>Correctness rationale</th>"
            f"<td class='rationale'>{_e(correctness.get('rationale'))}</td></tr>"
            "</tbody></table>"
        )
    return section + "".join(detail), n


def _calibration_section(calibration: dict[str, Any]) -> str:
    dimensions = calibration.get("dimensions") or {}
    rows = "".join(
        f"<tr><td>{_e(name)}</td>"
        f"<td class='num'>{_e(_fmt(values.get('kappa')))}</td>"
        f"<td class='num'>{_e(_fmt(values.get('exact_agreement')))}</td>"
        f"<td>{_e(values.get('band'))}</td>"
        f"<td class='num'>{_e(values.get('n'))}</td></tr>"
        for name, values in sorted(dimensions.items())
    )
    unmatched = calibration.get("unmatched_label_ids") or []
    note = ""
    if unmatched:
        note = (
            "<p class='legend'>Labels with no matching graded answer, so they scored "
            f"nothing: {_e(', '.join(str(item) for item in unmatched))}.</p>"
        )
    return (
        "<h2>Judge calibration</h2>"
        "<p class='legend'>Agreement between the human labels and the judge on the "
        f"{_e(calibration.get('matched_n'))} answers present in both. Kappa corrects for "
        "agreement that chance alone would produce, which is why it can sit at zero while "
        "exact agreement looks high.</p>"
        "<table><thead><tr><th>Dimension</th><th class='num'>Kappa</th>"
        "<th class='num'>Exact agreement</th><th>Band</th><th class='num'>n</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>{note}"
    )


def render_html(payload: dict[str, Any], calibration: dict[str, Any] | None = None) -> str:
    """Render one eval report as a single self-contained HTML page.

    ``calibration`` is the optional ``calibration.json`` written beside an
    answers report. It is a separate argument rather than something read
    from disk here so the renderer stays a pure function of its inputs.
    """
    kind = payload.get("kind")
    if kind == "answers":
        body, n = _answers_sections(payload)
        title = "Answer evaluation"
    else:
        body, n = _retrieval_sections(payload)
        title = "Retrieval evaluation"

    sections = [_receipt(payload), _warnings(payload, n), body]
    if calibration:
        sections.append(_calibration_section(calibration))

    return (
        "<!DOCTYPE html>\n"
        "<html lang='en'>\n<head>\n<meta charset='utf-8'>\n"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>\n"
        f"<title>{_e(title)}</title>\n<style>{STYLESHEET}</style>\n</head>\n<body>\n"
        f"<h1>{_e(title)}</h1>\n"
        f"{''.join(sections)}\n"
        "<footer>Generated by <code>sci-rag eval html</code> from the run's "
        "<code>report.json</code>. Every number here is reproducible from that file.</footer>\n"
        "</body>\n</html>\n"
    )
