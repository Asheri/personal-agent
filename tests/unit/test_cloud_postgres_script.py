"""The Cloud SQL development helper, exercised as a real subprocess.

The fake binaries below model the Cloud SQL control plane and a listening
proxy without contacting Google. They let the unit suite prove idempotency,
workspace isolation, secret handling, and lifecycle behavior deterministically.
The credentialed counterpart lives in ``tests/cloud``.
"""

from __future__ import annotations

import json
import os
import runpy
import socket
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from platform_checks import windows_acl_snapshot

REPO_ROOT = Path(__file__).parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cloud_postgres.py"

# The helper ships no project or instance, so every test names its own. These
# are deliberately not any real instance: `pause` and `resume` act on whatever
# they are given, and a test fixture that named live infrastructure would be
# the same defect the script no longer has.
FIXTURE_PROJECT = "example-project"
FIXTURE_INSTANCE = "example-instance"
FIXTURE_REGION = "us-west1"
FIXTURE_CONNECTION = f"{FIXTURE_PROJECT}:{FIXTURE_REGION}:{FIXTURE_INSTANCE}"

FIXTURE_CONFIG = {
    "SCI_RAG_CLOUD_PG_PROJECT": FIXTURE_PROJECT,
    "SCI_RAG_CLOUD_PG_INSTANCE": FIXTURE_INSTANCE,
    "SCI_RAG_CLOUD_PG_REGION": FIXTURE_REGION,
}

# Settings the developer's own shell may carry. Clearing them keeps a test
# from passing or failing because of the machine it ran on.
_HELPER_VARS = (
    "SCI_RAG_CLOUD_PG_PROJECT",
    "SCI_RAG_CLOUD_PG_INSTANCE",
    "SCI_RAG_CLOUD_PG_REGION",
    "SCI_RAG_CLOUD_PG_DIR",
    "SCI_RAG_CLOUD_PG_PORT",
    "SCI_RAG_CLOUD_PG_WORKSPACE",
    "SCI_RAG_CLOUD_PG_USER",
    "SCI_RAG_CLOUD_PG_CONFIG",
)


# One flat 30 second budget covered every operation, and `start` spends its
# share on four sequential helper invocations. On a loaded machine the last
# one ran out and the test failed on wall clock alone, with no assertion
# reached, on a diff that never went near `scripts/cloud_postgres.py`.
#
# Per operation instead, so the bound still means something. A `status` that
# takes a minute is a real defect and should still fail; a `start` that takes
# a minute on a busy laptop is Tuesday.
_FAST_OPERATIONS = frozenset({"config", "status", "stop"})
_FAST_TIMEOUT_S = 30
_PROVISIONING_TIMEOUT_S = 120


def timeout_for(operation: str) -> int:
    """How long an operation may take before it counts as hung.

    Named and exported so the budget is a stated policy rather than a
    magic number buried in a call.
    """
    return _FAST_TIMEOUT_S if operation in _FAST_OPERATIONS else _PROVISIONING_TIMEOUT_S


def _run(
    *args: str, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    environment = {key: value for key, value in os.environ.items() if key not in _HELPER_VARS}
    environment.update(FIXTURE_CONFIG)
    environment.update(env or {})
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=environment,
        timeout=timeout_for(args[0] if args else ""),
    )


def test_a_read_only_operation_keeps_a_tighter_budget_than_a_provisioning_one() -> None:
    """The point of splitting the budget is that one of them stays strict.

    Raising every timeout would have stopped the flake and also stopped the
    test noticing a genuinely hung `status`, which is the failure worth
    catching.
    """
    assert timeout_for("status") < timeout_for("start")
    assert timeout_for("config") == _FAST_TIMEOUT_S
    assert timeout_for("resume") == _PROVISIONING_TIMEOUT_S
    # An operation nobody listed is assumed to provision, because guessing
    # "fast" for something unknown is how the original flake happened.
    assert timeout_for("some-future-subcommand") == _PROVISIONING_TIMEOUT_S


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _make_executable(path: Path, source: str) -> None:
    if os.name == "nt":
        script = path.with_suffix(".py")
        script.write_text(source, encoding="utf-8")
        wrapper = path.with_suffix(".cmd")
        wrapper.write_text(
            f'@"{sys.executable}" "%~dp0{script.name}" %*\r\n',
            encoding="utf-8",
        )
        return
    path.write_text(f"#!{sys.executable}\n{source}", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _assert_owner_only(path: Path) -> None:
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        return
    acl = windows_acl_snapshot(path)
    assert acl["Protected"] is True, f"inherited access remains on {path}: {acl}"
    assert acl["Count"] == 1, f"expected one access rule, got {acl}"
    assert acl["Sid"] == acl["CurrentSid"], f"access belongs to the wrong account: {acl}"
    assert "FullControl" in str(acl["Rights"]), f"owner lacks FullControl: {acl}"
    assert acl["AccessType"] == "Allow", f"owner rule is not Allow: {acl}"
    assert acl["Inherited"] is False, f"owner rule is inherited: {acl}"


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL semantics are not available here")
def test_owner_only_removes_a_preexisting_explicit_ace(tmp_path: Path) -> None:
    path = tmp_path / "private-file"
    path.write_text("fixture\n", encoding="utf-8")
    subprocess.run(
        ["icacls", str(path), "/grant:r", "*S-1-1-0:(M)"],
        capture_output=True,
        text=True,
        check=True,
    )

    module = runpy.run_path(str(SCRIPT), run_name="cloud_postgres_owner_test")
    module["_set_owner_only"](path)

    _assert_owner_only(path)


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL semantics are not available here")
def test_owner_only_assertion_reads_get_acl_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "private-file"
    path.write_text("fixture\n", encoding="utf-8")
    module = runpy.run_path(str(SCRIPT), run_name="cloud_postgres_acl_contract_test")
    module["_set_owner_only"](path)

    original_run = subprocess.run

    def reject_icacls(command: list[str], *args: object, **kwargs: object):
        assert command[0].lower() != "icacls", "owner-only assertions must use Get-Acl"
        return original_run(command, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(subprocess, "run", reject_icacls)

    _assert_owner_only(path)


@pytest.fixture
def fake_cloud_tools(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state_file = tmp_path / "instance-state"
    databases_file = tmp_path / "databases"
    command_log = tmp_path / "gcloud.jsonl"
    psql_log = tmp_path / "psql.jsonl"

    _make_executable(
        bin_dir / "gcloud",
        """import json
import os
import pathlib
import sys

args = sys.argv[1:]
with pathlib.Path(os.environ["FAKE_GCLOUD_LOG"]).open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(args) + "\\n")
state_path = pathlib.Path(os.environ["FAKE_INSTANCE_STATE"])
db_path = pathlib.Path(os.environ["FAKE_DATABASES"])
state = state_path.read_text(encoding="utf-8").strip() if state_path.exists() else "STOPPED"

if args[:3] == ["sql", "instances", "describe"]:
    activation = "ALWAYS" if state == "RUNNABLE" else "NEVER"
    print(json.dumps({
        "connectionName": os.environ["FAKE_CONNECTION_NAME"],
        "state": state,
        "settings": {"activationPolicy": activation},
    }))
elif args[:3] == ["sql", "instances", "patch"]:
    policy = next(value.split("=", 1)[1] for value in args if value.startswith("--activation-policy="))
    state_path.write_text("RUNNABLE" if policy == "ALWAYS" else "STOPPED", encoding="utf-8")
elif args[:3] == ["sql", "databases", "list"]:
    if db_path.exists():
        print(db_path.read_text(encoding="utf-8"), end="")
elif args[:3] == ["sql", "databases", "create"]:
    with db_path.open("a", encoding="utf-8") as handle:
        handle.write(args[3] + "\\n")
elif args[:4] == ["secrets", "versions", "access", "latest"]:
    print("unit-test-secret")
else:
    print(f"unexpected gcloud arguments: {args}", file=sys.stderr)
    raise SystemExit(2)
""",
    )
    _make_executable(
        bin_dir / "cloud-sql-proxy",
        """import signal
import socket
import sys

args = sys.argv[1:]
port = int(args[args.index("--port") + 1])
listener = socket.socket()
listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listener.bind(("127.0.0.1", port))
listener.listen()
running = True

def stop(_signum, _frame):
    global running
    running = False
    listener.close()

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
print("Ready for new connections", flush=True)
while running:
    try:
        listener.settimeout(0.1)
        connection, _address = listener.accept()
        connection.close()
    except (TimeoutError, OSError):
        pass
""",
    )
    _make_executable(
        bin_dir / "psql",
        """import json
import os
import pathlib
import sys

with pathlib.Path(os.environ["FAKE_PSQL_LOG"]).open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({"args": sys.argv[1:], "pgpass": os.environ.get("PGPASSFILE")}) + "\\n")
""",
    )
    return {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "FAKE_GCLOUD_LOG": str(command_log),
        "FAKE_INSTANCE_STATE": str(state_file),
        "FAKE_DATABASES": str(databases_file),
        "FAKE_PSQL_LOG": str(psql_log),
        "FAKE_CONNECTION_NAME": FIXTURE_CONNECTION,
    }


@pytest.mark.parametrize("verb", ["config", "start", "status", "pause", "resume"])
def test_an_unconfigured_helper_names_what_to_set_instead_of_guessing(
    tmp_path: Path, verb: str
) -> None:
    """F-019's sibling: a shipped instance name is a target for `pause`.

    Every verb goes through the same resolver, so none of them can reach an
    instance the operator has not named. `pause` and `resume` matter most:
    ADR 0009 says plainly that they affect every workspace using the instance.
    """
    result = _run(
        verb,
        cwd=tmp_path,
        env={key: "" for key in ("SCI_RAG_CLOUD_PG_PROJECT", "SCI_RAG_CLOUD_PG_INSTANCE")},
    )

    assert result.returncode != 0
    assert "SCI_RAG_CLOUD_PG_PROJECT" in result.stderr
    assert "SCI_RAG_CLOUD_PG_INSTANCE" in result.stderr
    assert "sci_rag_cloud_pg_config" in result.stderr, "say where the values come from"
    assert result.stdout.strip() == "", "an unconfigured helper resolves to no instance at all"


def test_settings_come_from_a_file_when_the_environment_is_silent(tmp_path: Path) -> None:
    """The workspace setup script asks for configuration before `.env` exists.

    A file is what closes that loop, and its format is exactly what
    `terraform output -raw sci_rag_cloud_pg_config` already prints, so saving
    that output is the whole setup step.
    """
    workspace = tmp_path / "from-file"
    (workspace / ".cloudsql").mkdir(parents=True)
    (workspace / ".cloudsql" / "config.env").write_text(
        "# from terraform\n"
        "SCI_RAG_CLOUD_PG_PROJECT=file-project\n"
        "SCI_RAG_CLOUD_PG_INSTANCE=file-instance\n"
        "SCI_RAG_CLOUD_PG_REGION=europe-west1\n"
        "SCI_RAG_CLOUD_PG_USER=file-user\n",
        encoding="utf-8",
    )

    result = _run("config", cwd=workspace, env=dict.fromkeys(FIXTURE_CONFIG, ""))

    assert result.returncode == 0, result.stderr
    values = dict(line.split("=", 1) for line in result.stdout.strip().splitlines())
    assert values["connection_name"] == "file-project:europe-west1:file-instance"
    assert values["user"] == "file-user"


def test_an_explicit_export_overrides_the_stored_file(tmp_path: Path) -> None:
    """A file holds a default; an export is a deliberate choice."""
    workspace = tmp_path / "override"
    (workspace / ".cloudsql").mkdir(parents=True)
    (workspace / ".cloudsql" / "config.env").write_text(
        "SCI_RAG_CLOUD_PG_PROJECT=file-project\nSCI_RAG_CLOUD_PG_INSTANCE=file-instance\n",
        encoding="utf-8",
    )

    result = _run("config", cwd=workspace, env={"SCI_RAG_CLOUD_PG_INSTANCE": "exported-instance"})

    assert result.returncode == 0, result.stderr
    values = dict(line.split("=", 1) for line in result.stdout.strip().splitlines())
    assert values["instance"] == "exported-instance"


def test_config_reports_workspace_scoped_passwordless_urls(tmp_path: Path) -> None:
    workspace = tmp_path / "Davis V3"
    workspace.mkdir()
    result = _run("config", cwd=workspace)

    assert result.returncode == 0, result.stderr
    values = dict(line.split("=", 1) for line in result.stdout.strip().splitlines())
    assert values["project"] == FIXTURE_PROJECT
    assert values["instance"] == FIXTURE_INSTANCE
    assert values["region"] == FIXTURE_REGION
    assert values["workspace"] == "davis_v3"
    assert values["database"] == "sci_rag_davis_v3"
    assert values["test_database"] == "sci_rag_test_davis_v3"
    assert Path(values["state_dir"]) == workspace / ".cloudsql"
    assert "password" not in values["url"]
    assert "passfile=" in values["url"]
    assert values["SCI_RAG_DATABASE_URL"] == values["url"]
    assert values["SCI_RAG_TEST_DATABASE_URL"] == values["test_url"]
    assert "unit-test-secret" not in result.stdout + result.stderr


def test_config_honours_environment_overrides(tmp_path: Path) -> None:
    result = _run(
        "config",
        cwd=tmp_path,
        env={
            "SCI_RAG_CLOUD_PG_PROJECT": "other-project",
            "SCI_RAG_CLOUD_PG_INSTANCE": "other-instance",
            "SCI_RAG_CLOUD_PG_REGION": "us-east1",
            "SCI_RAG_CLOUD_PG_DIR": "state",
            "SCI_RAG_CLOUD_PG_PORT": "5999",
            "SCI_RAG_CLOUD_PG_WORKSPACE": "Experiment 42",
            "SCI_RAG_CLOUD_PG_USER": "researcher",
        },
    )

    assert result.returncode == 0, result.stderr
    values = dict(line.split("=", 1) for line in result.stdout.strip().splitlines())
    assert values["connection_name"] == "other-project:us-east1:other-instance"
    assert values["workspace"] == "experiment_42"
    assert values["database"] == "sci_rag_experiment_42"
    assert values["user"] == "researcher"
    assert values["port"] == "5999"
    assert Path(values["state_dir"]) == tmp_path / "state"


def test_config_walks_up_from_a_bound_port(tmp_path: Path) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        occupied = int(listener.getsockname()[1])
        result = _run(
            "config",
            cwd=tmp_path,
            env={"SCI_RAG_CLOUD_PG_PORT": str(occupied)},
        )

    assert result.returncode == 0, result.stderr
    values = dict(line.split("=", 1) for line in result.stdout.strip().splitlines())
    assert int(values["port"]) > occupied


def test_proxy_readiness_retries_before_ps_exposes_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = runpy.run_path(str(SCRIPT), run_name="cloud_postgres_test")
    config = module["Config"](
        project=FIXTURE_PROJECT,
        instance=FIXTURE_INSTANCE,
        region="us-west1",
        state_dir=tmp_path,
        port=_free_port(),
        workspace="race",
        user="sci_rag",
    )
    config.pid_file.write_text("123\n", encoding="utf-8")
    commands = iter(["", f"cloud-sql-proxy {config.connection_name}"])

    class Connection:
        def __enter__(self) -> Connection:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    helper_globals = module["_wait_for_proxy"].__globals__
    monkeypatch.setitem(helper_globals, "_process_command", lambda _pid: next(commands))
    monkeypatch.setattr(helper_globals["time"], "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        helper_globals["socket"], "create_connection", lambda *_args, **_kwargs: Connection()
    )

    module["_wait_for_proxy"](config)


def test_pause_waits_through_transitional_instance_states(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = runpy.run_path(str(SCRIPT), run_name="cloud_postgres_test")
    config = module["Config"](
        project=FIXTURE_PROJECT,
        instance=FIXTURE_INSTANCE,
        region="us-west1",
        state_dir=tmp_path,
        port=_free_port(),
        workspace="transition",
        user="sci_rag",
    )
    states = iter([{"state": "MAINTENANCE"}, {"state": "STOPPED"}])
    helper_globals = module["_wait_for_instance"].__globals__
    monkeypatch.setitem(helper_globals, "_instance_details", lambda _config: next(states))
    monkeypatch.setattr(helper_globals["time"], "sleep", lambda _seconds: None)

    assert module["_wait_for_instance"](config, running=False)["state"] == "STOPPED"


@pytest.mark.parametrize("failure_mode", ["returncode", "timeout"])
def test_windows_stop_checks_taskkill_and_keeps_a_live_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure_mode: str,
) -> None:
    module = runpy.run_path(str(SCRIPT), run_name="cloud_postgres_stop_test")
    config = module["Config"](
        project=FIXTURE_PROJECT,
        instance=FIXTURE_INSTANCE,
        region="us-west1",
        state_dir=tmp_path,
        port=_free_port(),
        workspace="stop-failure",
        user="sci_rag",
    )
    pid = 4242
    config.pid_file.write_text(f"{pid}\n", encoding="utf-8")

    helper_globals = module["_stop_proxy"].__globals__
    monkeypatch.setattr(helper_globals["os"], "name", "nt")
    monkeypatch.setitem(helper_globals, "_proxy_is_running", lambda _config: True)
    monkeypatch.setitem(
        helper_globals,
        "_process_command",
        lambda _pid: f"cloud-sql-proxy {config.connection_name}",
    )
    clock = iter((0.0, 20.0))
    monkeypatch.setattr(helper_globals["time"], "monotonic", lambda: next(clock))

    taskkill_calls: list[dict[str, object]] = []

    if failure_mode == "timeout":

        def timed_out_run(command: list[str], **_kwargs: object):
            raise subprocess.TimeoutExpired(command, 10)

        monkeypatch.setattr(helper_globals["subprocess"], "run", timed_out_run)
    else:

        def failed_taskkill(
            command: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            taskkill_calls.append({"command": command, **kwargs})
            return subprocess.CompletedProcess(command, 1, "", "access denied")

        monkeypatch.setattr(helper_globals["subprocess"], "run", failed_taskkill)

    stopped = module["_stop_proxy"](config)

    output = capsys.readouterr()
    assert stopped is False
    assert config.pid_file.exists()
    assert "could not stop proxy" in output.err
    if failure_mode == "returncode":
        assert taskkill_calls, "the Windows path must invoke taskkill"
        assert all(call["timeout"] for call in taskkill_calls)
    else:
        assert "timed out" in output.err


def test_windows_taskkill_accepts_a_wrapper_that_is_already_gone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = runpy.run_path(str(SCRIPT), run_name="cloud_postgres_taskkill_missing_test")
    config = module["Config"](
        project=FIXTURE_PROJECT,
        instance=FIXTURE_INSTANCE,
        region="us-west1",
        state_dir=tmp_path,
        port=_free_port(),
        workspace="missing-wrapper",
        user="sci_rag",
    )
    pid = 4444
    config.pid_file.write_text(f"{pid}\n", encoding="utf-8")
    helper_globals = module["_windows_taskkill"].__globals__
    monkeypatch.setattr(helper_globals["os"], "name", "nt")
    monkeypatch.setitem(helper_globals, "_process_command", lambda _pid: "")
    monkeypatch.setattr(
        helper_globals["subprocess"],
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 255, "", "child process has no running instance"
        ),
    )

    assert module["_windows_taskkill"](pid) is None
    assert module["_stop_proxy"](config) is True
    assert not config.pid_file.exists()


def test_windows_taskkill_retries_wrapper_when_process_remains(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = runpy.run_path(str(SCRIPT), run_name="cloud_postgres_taskkill_retry_test")
    config = module["Config"](
        project=FIXTURE_PROJECT,
        instance=FIXTURE_INSTANCE,
        region="us-west1",
        state_dir=tmp_path,
        port=_free_port(),
        workspace="wrapper-retry",
        user="sci_rag",
    )
    pid = 4545
    config.pid_file.write_text(f"{pid}\n", encoding="utf-8")
    helper_globals = module["_windows_taskkill"].__globals__
    monkeypatch.setattr(helper_globals["os"], "name", "nt")
    monkeypatch.setitem(
        helper_globals,
        "_process_command",
        lambda _pid: f"cloud-sql-proxy {config.connection_name}",
    )
    calls: list[list[str]] = []

    def failed_taskkill(command: list[str], **_kwargs: object):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, "", "access denied")

    monkeypatch.setattr(helper_globals["subprocess"], "run", failed_taskkill)
    clock = iter((0.0, 20.0))
    monkeypatch.setattr(helper_globals["time"], "monotonic", lambda: next(clock))

    failure = module["_windows_taskkill"](pid)
    assert failure is not None
    assert any("/T" in call for call in calls)
    assert any("/T" not in call and "/F" in call for call in calls)
    assert module["_stop_proxy"](config) is False
    assert config.pid_file.exists()


def test_posix_stop_escalates_to_sigkill_and_only_then_clears_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = runpy.run_path(str(SCRIPT), run_name="cloud_postgres_posix_stop_test")
    config = module["Config"](
        project=FIXTURE_PROJECT,
        instance=FIXTURE_INSTANCE,
        region="us-west1",
        state_dir=tmp_path,
        port=_free_port(),
        workspace="posix-stop",
        user="sci_rag",
    )
    pid = 4343
    config.pid_file.write_text(f"{pid}\n", encoding="utf-8")

    helper_globals = module["_stop_proxy"].__globals__
    monkeypatch.setattr(helper_globals["os"], "name", "posix")

    class FakeSignal:
        SIGTERM = 15
        SIGKILL = 9

    signals: list[int] = []

    def record_kill(_pid: int, signal_number: int) -> None:
        signals.append(signal_number)

    monkeypatch.setitem(helper_globals, "signal", FakeSignal)
    monkeypatch.setattr(helper_globals["os"], "kill", record_kill)
    monkeypatch.setitem(helper_globals, "_proxy_is_running", lambda _config: True)
    commands = iter((f"cloud-sql-proxy {config.connection_name}", ""))
    monkeypatch.setitem(helper_globals, "_process_command", lambda _pid: next(commands))
    clock = iter((0.0, 1.0, 20.0))
    monkeypatch.setattr(helper_globals["time"], "monotonic", lambda: next(clock))
    monkeypatch.setattr(helper_globals["time"], "sleep", lambda _seconds: None)

    stopped = module["_stop_proxy"](config)

    assert stopped is True
    assert signals == [FakeSignal.SIGTERM, FakeSignal.SIGKILL]
    assert not config.pid_file.exists()


def test_start_without_required_tools_has_install_guidance(tmp_path: Path) -> None:
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    result = _run("start", cwd=tmp_path, env={"PATH": str(empty_bin)})

    assert result.returncode != 0
    message = result.stdout + result.stderr
    assert "gcloud" in message
    assert "cloud-sql-proxy" in message
    assert "psql" in message
    assert not (tmp_path / ".cloudsql").exists()


def test_start_is_idempotent_and_creates_both_workspace_databases(
    tmp_path: Path, fake_cloud_tools: dict[str, str]
) -> None:
    workspace = tmp_path / "workspace-one"
    workspace.mkdir()
    env = {
        **fake_cloud_tools,
        "SCI_RAG_CLOUD_PG_PORT": str(_free_port()),
    }
    try:
        first = _run("start", cwd=workspace, env=env)
        assert first.returncode == 0, first.stdout + first.stderr
        assert "ready:" in first.stdout

        state_dir = workspace / ".cloudsql"
        password = state_dir / "password"
        pgpass = state_dir / "pgpass"
        assert password.read_text(encoding="utf-8") == "unit-test-secret"
        _assert_owner_only(password)
        _assert_owner_only(pgpass)
        assert "unit-test-secret" not in first.stdout + first.stderr

        databases = Path(env["FAKE_DATABASES"]).read_text(encoding="utf-8").splitlines()
        assert databases == ["sci_rag_workspace_one", "sci_rag_test_workspace_one"]
        psql_calls = [
            json.loads(line)
            for line in Path(env["FAKE_PSQL_LOG"]).read_text(encoding="utf-8").splitlines()
        ]
        assert len(psql_calls) == 2
        assert {call["args"][call["args"].index("-d") + 1] for call in psql_calls} == set(databases)
        assert all(call["pgpass"] == str(pgpass) for call in psql_calls)

        again = _run("start", cwd=workspace, env=env)
        assert again.returncode == 0, again.stdout + again.stderr
        assert "already running" in again.stdout.lower()
        assert Path(env["FAKE_DATABASES"]).read_text(encoding="utf-8").splitlines() == databases

        status_result = _run("status", cwd=workspace, env=env)
        assert status_result.returncode == 0, status_result.stdout + status_result.stderr
        assert "RUNNABLE" in status_result.stdout
        assert "proxy=running" in status_result.stdout
        assert "sci_rag_workspace_one" in status_result.stdout
    finally:
        stopped = _run("stop", cwd=workspace, env=env)
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr

    assert "not running" in _run("stop", cwd=workspace, env=env).stdout.lower()


def test_pause_stops_only_the_workspace_proxy_and_resume_reactivates_the_instance(
    tmp_path: Path, fake_cloud_tools: dict[str, str]
) -> None:
    workspace = tmp_path / "workspace-two"
    workspace.mkdir()
    env = {
        **fake_cloud_tools,
        "SCI_RAG_CLOUD_PG_PORT": str(_free_port()),
    }
    started = _run("start", cwd=workspace, env=env)
    assert started.returncode == 0, started.stdout + started.stderr

    paused = _run("pause", cwd=workspace, env=env)
    assert paused.returncode == 0, paused.stdout + paused.stderr
    assert "NEVER" in paused.stdout
    status_result = _run("status", cwd=workspace, env=env)
    assert status_result.returncode == 1
    assert "STOPPED" in status_result.stdout
    assert "proxy=stopped" in status_result.stdout

    resumed = _run("resume", cwd=workspace, env=env)
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert "ALWAYS" in resumed.stdout
    assert Path(fake_cloud_tools["FAKE_INSTANCE_STATE"]).read_text(encoding="utf-8") == "RUNNABLE"


def test_two_running_workspaces_choose_distinct_database_names_and_ports(
    tmp_path: Path, fake_cloud_tools: dict[str, str]
) -> None:
    base_port = _free_port()
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    env = {**fake_cloud_tools, "SCI_RAG_CLOUD_PG_PORT": str(base_port)}
    try:
        first_start = _run("start", cwd=first, env=env)
        assert first_start.returncode == 0, first_start.stdout + first_start.stderr
        second_start = _run("start", cwd=second, env=env)
        assert second_start.returncode == 0, second_start.stdout + second_start.stderr
        first_values = dict(
            line.split("=", 1)
            for line in _run("config", cwd=first, env=env).stdout.strip().splitlines()
        )
        second_values = dict(
            line.split("=", 1)
            for line in _run("config", cwd=second, env=env).stdout.strip().splitlines()
        )
    finally:
        _run("stop", cwd=first, env=env)
        _run("stop", cwd=second, env=env)

    assert first_values["database"] != second_values["database"]
    assert first_values["test_database"] != second_values["test_database"]
    assert first_values["port"] != second_values["port"]
