# Deploy PC-Mem with GenericAgent

Install a small plugin, environment launcher, and one-shot refresh command into
an existing GenericAgent checkout. The installer preserves all Agent seed files.
Use explicit corpus paths and a reviewed manifest before enabling real automation.

## Prepare the local runtime

Keep this environment under the root named by `PCMEM_DATA_DIR`, which defaults to
`pcmem-data` in your home directory. Install this project's locked dependencies
and chosen embedding/generation provider. Configure credentials locally without
putting them in source, logs, or the handoff archive. For offline checks use
`SCI_RAG_EMBEDDING_PROVIDER=local-hash` and a matching database vector dimension.

Back up a retained database before `sci-rag db upgrade`. Revision 0012 adds indexed
document dates/access fields and backfills the simple token index; 0013 adds refresh
events. Large-corpus lock time has not been measured. Stop scheduled writers while
migrating. Downgrade with the matching old application code; reverting 0012 also
restores the earlier Chinese-only token cache and drops access/date columns.
Reverting 0013 removes its event history. Export/back up those records first.

```powershell
$root = $env:PCMEM_DATA_DIR
python scripts/install_pcmem_agent.py `
  --agent-root "$root/GenericAgent" `
  --corpus-root "$root/my-corpus" `
  --manifest "$root/my-corpus/corpus.jsonl" `
  --python "$root/python/.venv/Scripts/python.exe"
```

The installer requires a real existing checkout and explicit paths under the data
root. It
refuses different preexisting integration files, supports identical reinstallation,
and records before/after seed hashes. It does not copy credentials or change
`agent_loop.py`, `ga.py`, `agentmain.py`, `llmcore.py`, hooks, or scheduler seeds.

## Run the three channels

`start-pcmem.ps1` loads the integration environment and starts
`python agentmain.py --reflect`. The generated `sche_tasks/pcmem-refresh.json`
uses the upstream scheduler's `every_15m` task format. Its prompt runs
`pcmem-refresh.ps1 -Channel scheduler` and requires an `ask_user` failure report
when the command fails. The scheduler's existing run-report/cooldown mechanism
remains responsible for recording completed scheduled tasks.

The plugin's `tool_after` callback recognizes successful `file_write/file_patch`
outcomes, resolves the Agent's path, and calls the same refresh with channel hooks.
Writes outside the explicit corpus are ignored by the backend. Failed writes do
not trigger refresh. Routing failures appear in the next Agent prompt by operation
name and status, without raw error text or source contents.

For OS polling, the installer writes `pcmem-poll-task.xml`, a least-privilege
interactive task repeating every 15 minutes. Register it only for the intended
deployment user:

```powershell
schtasks /Create /TN PCMemPoll /XML $root/GenericAgent/pcmem-poll-task.xml
```

The installer and acceptance run do not register a permanent OS task. Test the
exact polling entry point directly with
`powershell -NoProfile -File $root/GenericAgent/pcmem-refresh.ps1 -Channel poll`.
Its exit code is propagated unchanged. All channels use one database lock, so
overlapping invocations return busy without creating competing writers.

## Validate and operate

`scripts/prepare_agent_fixture.py` pins six public upstream files by Git blob and
commit for a disposable protocol check. `scripts/run_agent_acceptance.py` tests
installation twice, the real hook/dispatch and scheduler protocols, all five route
scenes, three successful-task receipts, new-session SOP reuse, and private-pointer
exclusion. It uses a controlled handler and local-hash embeddings, not a live
GenericAgent model conversation. Its source/fixture directories must remain under D.

Check `sci-rag refresh history` and `sci-rag doctor` after failures. Inspect the
recorded run/channel/status/counts before assuming knowledge is current. If a
model batch fails, fix the provider or input and retry the same refresh. Unstamped
chunks remain available for retry. If sources are temporarily unreadable, avoid
changing the explicit root or manifest to force a successful-looking scan.

Choose a production corpus and database separately from the disposable handoff
environment. The packaged installation code is ready to configure; the test
database, runtime fixture, and automatic background tasks are not retained.
