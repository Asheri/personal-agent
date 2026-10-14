# Convenience targets. Everything here is just the underlying command,
# spelled out; run `make <target>` or copy the command, whichever you like.

.PHONY: setup db-up db-down db-upgrade demo demo-cloud test lint typecheck check serve mcp eval eval-ablation providers-check docs docs-geometry docs-serve docs-reference cast benchmark benchmark-check benchmark-refresh-graph clean-demo

SCI_RAG_DB_BACKEND ?= docker

## setup: install dependencies, start Postgres, create the schema
setup:
	uv sync --extra modelscope-embedding --extra openai
	$(MAKE) db-up
	uv run sci-rag db upgrade

db-up:

ifeq ($(SCI_RAG_DB_BACKEND),cloud)
	uv run python scripts/cloud_postgres.py start
else ifeq ($(SCI_RAG_DB_BACKEND),local)
	uv run python scripts/local_postgres.py start
else ifeq ($(SCI_RAG_DB_BACKEND),docker)
	docker compose up -d --wait
else
	@echo "Unknown SCI_RAG_DB_BACKEND=$(SCI_RAG_DB_BACKEND); choose docker, local, or cloud." >&2
	@exit 2
endif

db-down:
ifeq ($(SCI_RAG_DB_BACKEND),cloud)
	uv run python scripts/cloud_postgres.py stop
else ifeq ($(SCI_RAG_DB_BACKEND),local)
	uv run python scripts/local_postgres.py stop
else ifeq ($(SCI_RAG_DB_BACKEND),docker)
	docker compose down
else
	@echo "Unknown SCI_RAG_DB_BACKEND=$(SCI_RAG_DB_BACKEND); choose docker, local, or cloud." >&2
	@exit 2
endif

db-upgrade:
	uv run sci-rag db upgrade

## demo: ingest the offline demo corpus and run a scored retrieval check.
## Works with zero credentials (uses the deterministic local-hash embedder
## if you set SCI_RAG_EMBEDDING_PROVIDER=local-hash, or the configured
## semantic embedder otherwise).
demo:
	uv run sci-rag ingest --manifest data/demo/manifest.jsonl
	uv run sci-rag retrieve "How much rice straw was generated in the Colusa Basin in 2023?" --profile interactive --limit 3
	uv run sci-rag eval retrieval
	@echo ""
	@echo "Next: configure SCI_RAG_DEEPSEEK_API_KEY in .env (see .env.example), then run"
	@echo "'make demo-cloud' for graph extraction, deep retrieval, and answers."

## demo-cloud: the full pipeline on the demo corpus (needs generation credentials)
demo-cloud:
	uv run sci-rag graph extract
	uv run sci-rag graph communities
	uv run sci-rag answer "What conversion route suits rice straw given its ash content, and what yields should I expect?"
	uv run sci-rag eval retrieval --ablation

test:
	uv run pytest

lint:
	uv run ruff check src tests examples scripts
	uv run ruff format --check src tests examples scripts

typecheck:
	uv run mypy

## check: everything CI runs
check: lint typecheck test

serve:
	uv run sci-rag serve

mcp:
	uv run sci-rag mcp

eval:
	uv run sci-rag eval retrieval

eval-ablation:
	uv run sci-rag eval retrieval --ablation

## docs-reference: regenerate source-derived CLI and configuration reference.
docs-reference:
	uv run python scripts/render_cli_docs.py --output docs/cli.md
	uv run python scripts/render_config_docs.py --output docs/configuration.md

## cast: regenerate the homepage sci-rag-new session and its terminal cast.
## The session is produced by driving the real wizard with a scripted set of
## answers, not typed by hand, so re-run this whenever the questions change.
## `make docs` fails if it is stale, so you cannot forget.
cast:
	uv run python scripts/render_cast.py

## providers-check: ask the provider whether the documented partner models still answer.
## Needs SCI_RAG_GCP_PROJECT and application-default credentials. Not a CI job:
## it calls a model, and a check that always skips is a check nobody reads.
providers-check:
	uv run --extra anthropic --extra openai python scripts/check_partner_models.py

## docs: build the documentation exactly as CI and GitHub Pages do.
docs:
	uv run python scripts/render_cli_docs.py --check --output docs/cli.md
	uv run python scripts/render_config_docs.py --check --output docs/configuration.md
	uv run python scripts/render_cast.py --check
	uv run mkdocs build --strict
	test ! -d site/planning
	test ! -e site/assets/branding/README/index.html
	@if grep -RilE 'PISCES|filed software disclosure' site; then \
		echo "Internal planning language leaked into the public site." >&2; \
		exit 1; \
	fi

## docs-geometry: measure the built site in a browser. Needs `make docs` first.
## Separate from `docs` because it pulls a browser; the tests skip without one.
docs-geometry:
	uv sync --group docs --group docs-test
	uv run playwright install chromium
	uv run pytest tests/docs -q

docs-serve:
	uv run mkdocs serve

# The full, reproducible benchmark behind docs/benchmarks.md: real
# embeddings + graph + every ablation config + judged answers +
# calibration, then re-render the page from the report JSONs.
# Needs the selected PostgreSQL backend and Google credentials (see .env.example).
# Use a named, disposable PostgreSQL database dedicated to this run. The target
# ingests the tracked demo into otherwise pristine graph state.
# Do not clear an unrelated development corpus to satisfy the replay preflight;
# select a disposable database instead.
BENCH_SNAP := benchmark-$(shell date -u +%Y%m%d-%H%M%S)
BENCH_GRAPH_REPLAY := data/demo/graph-replay/a24c3fb88f163941048866b86fc494a3470337b0c24257f1d9235c8b00f19d15.json
GRAPH_REPLAY_RECEIPT := eval_results/graph-replay-receipt.json

## benchmark-refresh-graph: record a new immutable graph replay candidate.
## This target never selects the candidate for the published benchmark.
benchmark-refresh-graph: db-up
	uv run sci-rag db upgrade
	uv run sci-rag ingest --manifest data/demo/manifest.jsonl
	uv run python scripts/graph_replay.py refresh \
		--artifact-dir data/demo/graph-replay \
		--receipt "$(GRAPH_REPLAY_RECEIPT)" \
		--snapshot "$(BENCH_SNAP)"

benchmark: db-up
	uv run sci-rag db upgrade
	uv run sci-rag ingest --manifest data/demo/manifest.jsonl
	uv run python scripts/graph_replay.py require \
		--artifact "$(BENCH_GRAPH_REPLAY)" \
		--receipt "$(GRAPH_REPLAY_RECEIPT)" \
		--snapshot "$(BENCH_SNAP)"
	uv run sci-rag graph communities
	uv run sci-rag corpus snapshot $(BENCH_SNAP)
	uv run sci-rag eval retrieval --ablation --snapshot $(BENCH_SNAP)
	uv run sci-rag eval answers --snapshot $(BENCH_SNAP)
	@# The paired half of the compression gate. Both runs are needed: a token
	@# saving with no quality comparison is not evidence for a default.
	uv run sci-rag eval answers --compressed --snapshot $(BENCH_SNAP)
	@# Roles come from each report's own config.compression, not from a
	@# directory timestamp. Calibration writes into the uncompressed run, so
	@# an `ls -t` selector reverses the pair right before the page is drawn.
	@set -e; \
	roles="$$(uv run python scripts/render_benchmarks.py --select-answer-roles eval_results)"; \
	uncompressed="$$(printf '%s\n' "$$roles" | sed -n 1p)"; \
	compressed="$$(printf '%s\n' "$$roles" | sed -n 2p)"; \
	echo "uncompressed: $$uncompressed"; \
	echo "compressed:   $$compressed"; \
	uv run sci-rag eval calibrate --labels domain/eval_calibration_labels.jsonl \
		--report "$$uncompressed"; \
	uv run python scripts/render_benchmarks.py \
		--retrieval $$(ls -d eval_results/*-retrieval-ablation | sort | tail -1) \
		--answers "$$uncompressed" \
		--answers-compressed "$$compressed" \
		--graph-receipt "$(GRAPH_REPLAY_RECEIPT)" \
		--output docs/benchmarks.md \
		--update
	@echo "docs/benchmarks.md regenerated. Every number that moved is listed above;"
	@echo "a MATERIAL move is a finding to explain, not a refresh to commit."

## benchmark-check: reproduce the published numbers without republishing them.
## Same inputs as `benchmark`, and it exits nonzero when a number has moved
## beyond the declared tolerance. Needs the reports `benchmark` wrote.
benchmark-check:
	@set -e; \
	roles="$$(uv run python scripts/render_benchmarks.py --select-answer-roles eval_results)"; \
	uv run python scripts/render_benchmarks.py \
		--retrieval $$(ls -d eval_results/*-retrieval-ablation | sort | tail -1) \
		--answers "$$(printf '%s\n' "$$roles" | sed -n 1p)" \
		--answers-compressed "$$(printf '%s\n' "$$roles" | sed -n 2p)" \
		--graph-receipt "$(GRAPH_REPLAY_RECEIPT)" \
		--output docs/benchmarks.md \
		--check
