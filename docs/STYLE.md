---
title: Documentation style
description: "How to write a page for this site: which type it is, what shape it takes, and the words this project does and does not use."
---

# Documentation style

This is the standard every page on this site is held to. Read it before you write a page, and run the checklist at the end before you open the pull request. Most of it is judgment a reviewer applies; the mechanical half is enforced by `tests/unit/test_docs_style.py`, and each test names the rule it came from.

The short version: say what the reader will have, tell them what they need, give them one action at a time, show them what success looks like, and hand them somewhere real to go next. Then delete every sentence that survived only because it sounded finished.

## Every page has one type

Documentation fails in a predictable way. A tutorial grows explanations until nobody can follow it, and a reference grows tutorial prose until nobody can scan it. The fix is to decide, once, what each page is for.

Four types, from the [Diataxis](https://diataxis.fr/) framework. A page that cannot pick one is doing two jobs and should be split.

| Page | Type |
|---|---|
| `get-started.md` | explanation |
| `quickstart.md` | tutorial |
| `choosing-sci-rag-kit.md` | explanation |
| `troubleshooting.md` | how-to |
| `learn.md` | explanation |
| `faq.md` | explanation |
| `architecture.md` | explanation |
| `methodology.md` | explanation |
| `guides.md` | explanation |
| `bring-your-own-domain.md` | tutorial |
| `campaigns.md` | how-to |
| `evaluation.md` | how-to |
| `extend.md` | how-to |
| `operations.md` | how-to |
| `deploy-gcp.md` | how-to |
| `run-postgres.md` | how-to |
| `reference.md` | explanation |
| `cli.md` | reference |
| `configuration.md` | reference |
| `api.md` | reference |
| `benchmarks.md` | reference |
| `glossary.md` | reference |
| `project.md` | explanation |

Two assignments are worth defending, because a reasonable person would put them elsewhere.

**Section hubs are explanations.** A hub exists so a reader can tell which page in the section is theirs. That is understanding, so a hub gets an explanation's job: describe the shape of the section and recommend a starting point.

**Contributing is reference.** It sets the bar a change has to clear. You look up the rule that applies to you; you do not read it start to finish.

## What each type looks like

### Tutorials and how-to guides

Both teach a task, so both owe the reader the same contract. The tests enforce the two headings; the rest is review.

1. An **outcome-first title** and a one-sentence lede saying what the reader will have when they finish.
2. A **meta strip** with what they will build, what they need, how long it takes, and what version it was tested against. Use the `srag-meta-strip` component.
3. **`## Before you start`**, with the prerequisites as a list or a table. Anything a reader could be missing goes here, above the first command.
4. **Step headings that begin with a verb.** Use "Ingest the corpus". Avoid noun labels such as "Ingestion". One primary action per step.
5. **A checkpoint after every stage that produces something observable**, using the `srag-checkpoint` component. Say what the reader should see, and what it means if they do not. No significant procedure ends on a command.
6. **`## Next steps`**, with two to four real continuations. Link to the page a reader genuinely wants next and omit a recap of the page they just read.

The difference between the two types is the reader's state, and it changes the tone more than the shape. A tutorial reader is learning and has no context yet, so you make every decision for them and explain the ones that will matter later. A how-to reader has a job and some context, so you can assume the quickstart and get to the point.

### Explanations

An explanation earns its place by being the page a reader reaches for when a decision has stopped being obvious. Give it:

- a plain-language definition, before any jargon;
- why it matters, in terms of something that goes wrong without it;
- one small concrete example, with real values from this project;
- how it relates to the ideas next to it;
- a link to the task where the reader will actually use it.

Decision records are explanations with a fixed shape: **Context**, **Decision**, **Consequences**, **Reversal conditions**. All four headings, every time. The [FAQ](faq.md) promises a reader that every record states what would make us change our mind, and a record without that heading breaks the promise.

### Reference

Readers scan reference pages for specific facts. Keep tutorial prose out of them. Authentication, parameters, and errors stay in separate sections so a reader can jump to one. Consistency of structure matters more than elegance of sentence: if every entry has the same fields in the same order, a reader learns the shape once and scans forever.

Three reference pages are generated from source, and hand edits to them are reverted by `make docs`:

| Page | Written in |
|---|---|
| `docs/cli.md` | the Typer `help=` strings under `src/sci_rag/cli/` |
| `docs/configuration.md` | the Pydantic field descriptions in `src/sci_rag/config.py` and `src/sci_rag/domain.py` |
| `docs/benchmarks.md` | the evaluation report JSONs, through `scripts/render_benchmarks.py` |

A help string is a documentation page. Write it that way: one action, present tense, no trailing essay.

## The rules

These apply to every type.

1. **Open with the outcome.** The first sentence says what the reader will have, or what the page lets them decide. A title that names a noun ("Ingestion") tells a reader less than one that names a result.
2. **Center the kit when describing what it does; address the reader as "you" only when they act.** "The kit stores passages in Postgres" describes a capability. "Run `make setup`" is an action. A page that says "you" in every sentence reads as a script; a page that never says it reads as a brochure. Nobody is "the user" on a page the user is reading, and the project is "we" only where a human made a judgment call.
3. **Active voice.** Name who acts. Write "The parser records the route." Avoid passive constructions such as "The route is recorded."
4. **Put an action in every step.** A numbered step with no verb is a paragraph wearing a number.
5. **Put prerequisites before the procedure.** Keep them out of the numbered steps.
6. **Conditions come before instructions.** "If you use pixi, run `make setup`" gives a reader permission to skip. "Run `make setup` if you use pixi" makes them read a command that might not be theirs.
7. **Name exact files and commands.** Use `domain/domain.yaml`; generic labels such as "the domain configuration file" slow readers down.
8. **Put code under the sentence that calls for it**, with the shortest fence that works.
9. **State the expected result** after any action that produces one. A reader with no way to check has no way to continue.
10. **Explain a concept where the next decision needs it.** Readers skip background that arrives too early.
11. **Recommend a default.** Three equally weighted options is a decision handed back to someone with less information than you. Name the one most readers should take, say who should take a different one, and put the alternatives after it.
12. **Mark optional steps optional**, in the heading, so a reader skimming headings can skip them.
13. **Warn only for security, destruction, likely failure, or genuine surprise.** A page of warnings is a page with none.
14. **End on concrete next tasks.** Delete closing summaries such as "You have now learned about ingestion."
15. **Contractions are fine.** They are how a knowledgeable colleague talks.
16. **Keep personality in transitions and instructions plain.** The sentence before a step can carry the voice.

The register to aim for: precise, direct, and willing to tell you what to do. This is a scientific tool from a national laboratory, so recommendations and contractions, yes; jokes, no.

## Words we do not use

### Filler

Each of these is a phrase that survives review because any single instance looks harmless. In bulk they are what makes prose read as generated. The site is clean of all of them, and the test keeps it that way.

`it is important to note`, `it should be noted`, `it is worth noting`, `needless to say`, `as you can see`, `at the end of the day`, `in order to`, `the fact that`, `a wide range of`, `a variety of`, `in today's`, `in the world of`, `when it comes to`, `first and foremost`, `last but not least`, `that being said`, `delve into`, `deep dive`, `leverage`, `seamless`, `streamline`, `unlock`, `tailored`, `utilize`, `cutting-edge`, `best-in-class`, `game-changing`, `effortless`, `plethora`, `myriad`.

Also no em dashes anywhere in repository source, including code, comments,
docstrings, and documentation. That rule predates this guide and lives in
[CONTRIBUTING.md](contributing.md).

### Avoid reflexive contrasts

This site once leaned on a contrast in nearly every paragraph. Most of those asides answered a distinction the reader had never raised and made the prose sound generated.

State the positive claim directly. When a distinction affects safety or correctness, give each side its own clause or sentence and name the practical consequence.

### Terminology

One spelling per thing, so a reader searching for a term finds every instance of it.

| Use | Not |
|---|---|
| Sci RAG Kit in prose, `sci-rag-kit` as an identifier, "the kit" informally | a hyphen in the display name, or mixing the three forms |
| configure, adapt, customize, "point it at your field" | `specialize`, `specialization` |
| American spelling: behavior, labeled, judgment | `behaviour`, `labelled`, `judgement` |
| domain profile, for `domain/domain.yaml` | domain config, domain file, profile YAML |
| corpus campaign, matching the `campaign` command | crawl, harvest, collection run |
| one name per page: nav label, front matter `title`, and `# Heading` all agree | three names for one page |

The retired verb is worth a note, because it was everywhere. `specialize` meant four different things across twenty-eight uses: configure the project, adapt the prompts, narrow the ontology, or point the kit at a field. It even reached the generated CLI page, where `sci-rag init` told a reader to `specialize this checkout`. Say which one you mean.

## Two passes before you open the pull request

Run these in order, on the diff you are about to push. They are separate passes because they ask opposite questions, and doing both at once produces neither.

### 1. The editor pass

Delete. Do not rephrase, do not soften, do not move. Deleting is the only move available in this pass.

- [ ] Every sentence that restates the sentence above it.
- [ ] Every paragraph that introduces what the next paragraph says.
- [ ] Every adjective doing no work. "A simple command" is a command.
- [ ] Every hedge around a fact you can state. "Generally", "typically", "in most cases", when the thing is just true.
- [ ] Every sentence whose only job is to contrast, per the budget above.
- [ ] Every closing paragraph that summarizes the page a reader just read.

### 2. The humanity pass

Now read it as the person it is for, and ask what a knowledgeable colleague would have said.

- [ ] Where the page lists options, does it recommend one? If not, pick.
- [ ] Where it is abstract, can a real value from this project replace it? Use `data/demo/`.
- [ ] Where it says a thing is hard, does it say what actually goes wrong?
- [ ] Does any instruction contain a joke, an aside, or a flourish? Move it to the sentence before, or cut it.
- [ ] Does the page end somewhere a reader wants to go, or does it just stop?
- [ ] Read the first sentence and the last sentence together. Do they promise and deliver the same thing?

## What the tests check

`tests/unit/test_docs_style.py` runs in `make check` and holds the decidable rules: the banned phrases, em dashes across repository source, American spelling, the retired verb, the contrast budget, one name per page across the nav and the front matter, front matter on every page, that every page in the nav appears in the type table above, and that every tutorial and how-to carries `## Before you start` and `## Next steps`.

The table on this page is the source of truth the test reads. Adding a page to the nav without classifying it here fails the build, which is the intended order: decide what the page is, then write it.

Everything else in this guide is a reviewer's job. A test can tell you a page has a next-steps section. It cannot tell you the next step is one a reader wants.
