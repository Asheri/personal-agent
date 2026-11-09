# Plug PC-Mem into GenericAgent

PC-Mem is the memory layer. It does not ship an agent runtime, a chat client, or
a user interface: the runtime stays [GenericAgent](https://github.com/lsdefine/GenericAgent),
and this project adds a plugin, a launcher, a refresh command, and a scheduler
task to an existing checkout.

GenericAgent is **not vendored**. This page says exactly what the two projects
share, so a reader can decide how much of it to install.

## What GenericAgent provides

| Surface | Detail | Why it is enough |
|---|---|---|
| Plugin bus | `plugins/hooks.py`, 1,587 bytes: `register`, `trigger`, `unregister`, `clear`, `has`, `discover_and_load`, `load` | `plugins/pcmem_router.py` calls `register` and reads the context that `trigger` passes |
| Plugin discovery | `agentmain.py` calls `discover_and_load()`, which imports every `plugins/*.py` whose name does not start with an underscore | dropping one file into `plugins/` is the whole installation step |
| Scheduler | `reflect/scheduler.py` reads task files with `enabled`, `repeat`, `schedule`, `max_delay_hours`, `prompt` | we write one task file in that shape |
| Dispatch | `agent_loop.BaseHandler.dispatch` and `agent_loop.exhaust` | the acceptance run subclasses `BaseHandler` to exercise the real dispatch loop |

That is the entire dependency. No ImportError from GenericAgent reaches this
project at runtime: the router imports `sci_rag` lazily, so GenericAgent's own
interpreter needs no PC-Mem package installed.

## What the installer writes

`scripts/install_pcmem_agent.py` adds seven files to an existing checkout and
refuses to replace any file whose content differs.

| File | Purpose |
|---|---|
| `plugins/pcmem_router.py` | the five scene routes, found by `discover_and_load` |
| `pcmem-env.ps1` | the `PCMEM_*` environment for the launcher and the refresh |
| `pcmem-refresh.ps1` | one-shot `refresh run --channel <channel>` wrapper |
| `start-pcmem.ps1` | `python agentmain.py --reflect` with that environment |
| `sche_tasks/pcmem-refresh.json` | the scheduled task, including the failure prompt |
| `pcmem-poll-task.xml` | Windows Task Scheduler definition for the poll channel |
| `pcmem-install-receipt.json` | before and after hashes of the six seed files |

Six upstream files are hashed before and after and **never written**:
`agent_loop.py`, `ga.py`, `agentmain.py`, `llmcore.py`, `plugins/hooks.py`,
`reflect/scheduler.py`.

## Do you need GenericAgent to run the evaluation?

It depends on which evaluation. The knowledge base never touches GenericAgent.

| Command | Needs GenericAgent | How |
|---|---|---|
| `sci-rag eval retrieval`, `eval answers`, `eval calibrate`, `eval html` | No | none |
| `pytest tests/unit`, `tests/integration`, `tests/server` | No | the hook bus used by the unit tests is the stored copy in `plugins/` |
| `scripts/run_personal_quality.py` | No | database and model endpoints only |
| `scripts/run_agent_acceptance.py` | **Yes**, six files | no install, no package, no assets |

`run_agent_acceptance.py` needs those six files because it imports the real
hook bus, subclasses the real `BaseHandler`, and loads the real
`reflect/scheduler.py`. It does not need a pip install, the repository's
23 MB of assets, or its frontends.

## Three ways to get the six files

```bash
# 1. Download, verified by blob (default; the only strict pin is the hook bus)
uv run python scripts/prepare_agent_fixture.py --directory "$PCMEM_DATA_DIR/GenericAgent"

# 2. Copy from an existing checkout, no network
uv run python scripts/prepare_agent_fixture.py --directory "$PCMEM_DATA_DIR/GenericAgent" \
  --source-dir /path/to/GenericAgent

# 3. A different branch or tag
uv run python scripts/prepare_agent_fixture.py --directory "$PCMEM_DATA_DIR/GenericAgent" \
  --ref main
```

The recorded commit `a9a36b4b` no longer resolves on GitHub, so a download
addressed to it is a 404. The fixture pins `plugins/hooks.py` by **git blob**
instead, because a blob survives the history rewrites that a commit does not.
The other five come from the same ref and are reported as `drifted` when their
blob differs from the archived one.

## When the hook bus changes

A changed `plugins/hooks.py` fails the download with the expected and actual
blob. Treat it as a real signal rather than noise:

1. Read the diff at that path.
2. Adjust `plugins/pcmem_router.py` if a function moved or a context key changed.
3. Update `PINNED` in `scripts/prepare_agent_fixture.py`, `HOOK_API` and the
   stored copy in `plugins/hooks.py` together.
4. Run `uv run pytest tests/unit/test_agent_integration_contract.py -q`.

The pin exists so that this step cannot be skipped silently.

## Verification without GenericAgent

`tests/unit/test_agent_integration_contract.py` checks the contract with no
network and no checkout:

- the stored `plugins/hooks.py` matches its pinned blob, and it is the only
  strict pin;
- an AST scan proves the router calls nothing beyond the seven documented
  functions;
- the installer adds exactly its seven files and leaves all six seeds byte
  identical;
- the generated task file has the five keys the upstream scheduler reads;
- the installer refuses to overwrite an edited integration file;
- the router imports and passes the context through when `PCMEM_KB_ROOT` is
  unset, so a missing corpus cannot break agent startup.

## Platform support today

| Piece | Windows | macOS | Linux |
|---|---|---|---|
| Plugin, refresh CLI, scheduler task | yes | yes | yes |
| `pcmem-refresh.ps1` launcher | yes | not shipped | not shipped |
| `pcmem-poll-task.xml` OS task | yes | not shipped | not shipped |
| `run_agent_acceptance.py` | yes | yes | yes |

The acceptance run uses the PowerShell wrapper on Windows and the same refresh
command directly on macOS and Linux. A scheduled poll on those platforms needs
your own timer (`launchd` or a systemd timer) until a template ships.
