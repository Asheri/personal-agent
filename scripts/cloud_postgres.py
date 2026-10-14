#!/usr/bin/env python
"""Run this workspace against a shared Cloud SQL development instance.

Each checkout gets its own proxy process, loopback port, development database,
and disposable test database. The Cloud SQL instance is shared, but database
names and all local state are derived from the workspace directory. Normal
output never contains the database password. Connection URLs point asyncpg at
a mode-0600 pgpass file instead.

The instance may have a public IPv4 address, but it must have no authorized
networks. The Cloud SQL Auth Proxy is the only connection path and supplies IAM
authorization plus TLS. This is a development backend, never a deployment path.

    python scripts/cloud_postgres.py config
    python scripts/cloud_postgres.py start
    python scripts/cloud_postgres.py status
    python scripts/cloud_postgres.py stop
    python scripts/cloud_postgres.py pause
    python scripts/cloud_postgres.py resume

The project and instance have no defaults. `pause` and `resume` act on
whatever they name, so a shipped default would aim a lifecycle change at
somebody else's infrastructure. Provision an instance with
infra/terraform/dev-database and take its settings from
`terraform output -raw sci_rag_cloud_pg_config`.

Environment:
    SCI_RAG_CLOUD_PG_PROJECT    Google Cloud project (required)
    SCI_RAG_CLOUD_PG_INSTANCE   Cloud SQL instance (required)
    SCI_RAG_CLOUD_PG_REGION     Cloud SQL region (us-west1)
    SCI_RAG_CLOUD_PG_DIR        local state directory (.cloudsql)
    SCI_RAG_CLOUD_PG_PORT       first loopback port to try (5433)
    SCI_RAG_CLOUD_PG_WORKSPACE  database-name suffix (workspace directory)
    SCI_RAG_CLOUD_PG_USER       PostgreSQL user (sci_rag)
    SCI_RAG_CLOUD_PG_CONFIG     KEY=VALUE file holding any of the above
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_REGION = "us-west1"
DEFAULT_CONFIG_NAME = "config.env"
DEFAULT_STATE_DIR = ".cloudsql"
DEFAULT_PORT = 5433
DEFAULT_USER = "sci_rag"
_MAX_IDENTIFIER = 63
_INSTANCE_WAIT_SECONDS = 900
_PROXY_WAIT_SECONDS = 30
_WINDOWS_HELPER_TIMEOUT_S = 10
_STOP_WAIT_SECONDS = 10

_MISSING_CONFIG = """\
The cloud database backend needs the Cloud SQL project and instance to use.
This template ships no default for either, because `pause` and `resume` act on
whatever they name and a default would aim them at somebody else's instance.

Provision one with the development module, then read its settings back:

    terraform -chdir=infra/terraform/dev-database output -raw sci_rag_cloud_pg_config

Export those lines, or save them where the helper looks:

    ... > .cloudsql/config.env

Point SCI_RAG_CLOUD_PG_CONFIG at that file to share one across several
checkouts. Missing: {missing}
"""

_MISSING_TOOLS = """\
The cloud database backend needs `gcloud`, `cloud-sql-proxy`, and `psql` on PATH.

Install the Google Cloud CLI:
    https://cloud.google.com/sdk/docs/install

Install the Cloud SQL Auth Proxy on macOS:
    brew install cloud-sql-proxy

Install the PostgreSQL client on macOS:
    brew install libpq
    # or add /Applications/Postgres.app/Contents/Versions/16/bin to PATH
"""


def _workspace_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "workspace"
    if slug[0].isdigit():
        slug = f"workspace_{slug}"
    max_length = _MAX_IDENTIFIER - len("sci_rag_test_")
    if len(slug) > max_length:
        digest = hashlib.sha256(slug.encode()).hexdigest()[:8]
        slug = f"{slug[: max_length - 9].rstrip('_')}_{digest}"
    return slug


def _pid_from(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None


def _process_command(pid: int) -> str:
    if os.name == "nt":
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell:
            try:
                result = subprocess.run(
                    [
                        powershell,
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=_WINDOWS_HELPER_TIMEOUT_S,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"timed out querying Windows process {pid} after "
                    f"{_WINDOWS_HELPER_TIMEOUT_S} seconds"
                ) from exc
            if result.returncode == 0:
                return result.stdout.strip()
        return ""
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _port_is_available(port: int) -> bool:
    with socket.socket() as candidate:
        try:
            candidate.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _available_port(start: int) -> int:
    for port in range(start, 65536):
        if _port_is_available(port):
            return port
    raise RuntimeError(f"no loopback port is available at or above {start}")


@dataclass(frozen=True)
class Config:
    project: str
    instance: str
    region: str
    state_dir: Path
    port: int
    workspace: str
    user: str

    @property
    def connection_name(self) -> str:
        return f"{self.project}:{self.region}:{self.instance}"

    @property
    def database(self) -> str:
        return f"sci_rag_{self.workspace}"

    @property
    def test_database(self) -> str:
        return f"sci_rag_test_{self.workspace}"

    @property
    def password_secret(self) -> str:
        return f"{self.instance}-password"

    @property
    def password_file(self) -> Path:
        return self.state_dir / "password"

    @property
    def pgpass_file(self) -> Path:
        return self.state_dir / "pgpass"

    @property
    def pid_file(self) -> Path:
        return self.state_dir / "proxy.pid"

    @property
    def port_file(self) -> Path:
        return self.state_dir / "proxy.port"

    @property
    def logfile(self) -> Path:
        return self.state_dir / "proxy.log"

    def url_for(self, database: str) -> str:
        user = urllib.parse.quote(self.user, safe="")
        db = urllib.parse.quote(database, safe="")
        passfile = urllib.parse.quote(str(self.pgpass_file), safe="")
        return f"postgresql+asyncpg://{user}@127.0.0.1:{self.port}/{db}?passfile={passfile}"

    @property
    def url(self) -> str:
        return self.url_for(self.database)

    @property
    def test_url(self) -> str:
        return self.url_for(self.test_database)

    def as_lines(self) -> list[str]:
        return [
            f"project={self.project}",
            f"instance={self.instance}",
            f"region={self.region}",
            f"state_dir={self.state_dir}",
            f"port={self.port}",
            f"workspace={self.workspace}",
            f"user={self.user}",
            f"database={self.database}",
            f"test_database={self.test_database}",
            f"connection_name={self.connection_name}",
            f"pgpass_file={self.pgpass_file}",
            f"url={self.url}",
            f"test_url={self.test_url}",
            f"SCI_RAG_DATABASE_URL={self.url}",
            f"SCI_RAG_TEST_DATABASE_URL={self.test_url}",
        ]


def _proxy_is_running(config: Config) -> bool:
    pid = _pid_from(config.pid_file)
    if pid is None:
        return False
    command = _process_command(pid)
    return "cloud-sql-proxy" in command and config.connection_name in command


def _config_file_settings(state_dir: Path) -> dict[str, str]:
    """Settings from a KEY=VALUE file, which is the shape Terraform emits.

    `terraform output -raw sci_rag_cloud_pg_config` already prints exactly
    these lines, so saving that output is the whole setup step. A file is
    needed as well as the environment because this workspace's setup script
    asks the helper for its configuration before any `.env` exists, so the
    values cannot live there.

    The environment wins over the file: an explicit export is a deliberate
    override of a stored default.
    """
    raw = os.environ.get("SCI_RAG_CLOUD_PG_CONFIG", "")
    path = Path(raw).expanduser() if raw else state_dir / DEFAULT_CONFIG_NAME
    values: dict[str, str] = {}
    with contextlib.suppress(OSError):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            values[key.strip()] = value.strip()
    return values


def _setting(name: str, from_file: dict[str, str], default: str = "") -> str:
    key = f"SCI_RAG_CLOUD_PG_{name}"
    return os.environ.get(key) or from_file.get(key) or default


def resolve_config() -> Config:
    raw_dir = os.environ.get("SCI_RAG_CLOUD_PG_DIR", DEFAULT_STATE_DIR)
    state_dir = (Path.cwd() / raw_dir).resolve()
    from_file = _config_file_settings(state_dir)
    project = _setting("PROJECT", from_file)
    instance = _setting("INSTANCE", from_file)
    missing = [
        f"SCI_RAG_CLOUD_PG_{name}"
        for name, value in (("PROJECT", project), ("INSTANCE", instance))
        if not value
    ]
    if missing:
        print(_MISSING_CONFIG.format(missing=", ".join(missing)), file=sys.stderr)
        raise SystemExit(1)
    requested_port = int(os.environ.get("SCI_RAG_CLOUD_PG_PORT", str(DEFAULT_PORT)))
    saved_port: int | None = None
    with contextlib.suppress(FileNotFoundError, ValueError):
        saved_port = int((state_dir / "proxy.port").read_text(encoding="utf-8").strip())
    workspace = _workspace_slug(os.environ.get("SCI_RAG_CLOUD_PG_WORKSPACE", Path.cwd().name))
    provisional = Config(
        project=project,
        instance=instance,
        region=_setting("REGION", from_file, DEFAULT_REGION),
        state_dir=state_dir,
        port=saved_port or requested_port,
        workspace=workspace,
        user=_setting("USER", from_file, DEFAULT_USER),
    )
    if saved_port is not None and _proxy_is_running(provisional):
        return provisional
    return Config(
        project=provisional.project,
        instance=provisional.instance,
        region=provisional.region,
        state_dir=state_dir,
        port=_available_port(requested_port),
        workspace=workspace,
        user=provisional.user,
    )


def _require_binaries(*names: str) -> None:
    if all(shutil.which(name) for name in names):
        return
    print(_MISSING_TOOLS, file=sys.stderr)
    raise SystemExit(1)


def _platform_command(command: list[str]) -> list[str]:
    """Run a Windows batch shim through cmd.exe when direct CreateProcess cannot."""
    if os.name != "nt" or not command:
        return command
    resolved = shutil.which(command[0])
    if resolved and Path(resolved).suffix.lower() in {".cmd", ".bat"}:
        return [
            os.environ.get("COMSPEC", "cmd.exe"),
            "/d",
            "/s",
            "/c",
            subprocess.list2cmdline(command),
        ]
    return command


def _run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(_platform_command(command), capture_output=True, text=True, **kwargs)  # type: ignore[call-overload,no-any-return]


def _set_owner_only(path: Path) -> None:
    path.chmod(0o600)
    if os.name != "nt":
        return
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        raise RuntimeError("PowerShell is required to set a Windows owner-only ACL")
    target = str(path).replace("'", "''")
    script = (
        f"$path = '{target}'; "
        "$acl = Get-Acl -LiteralPath $path; "
        "$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent(); "
        "$rules = @($acl.Access); "
        "$isOwnerOnly = $acl.AreAccessRulesProtected -and $rules.Count -eq 1 -and "
        "$rules[0].IdentityReference.Value -eq $identity.Name -and "
        "$rules[0].AccessControlType -eq 'Allow' -and "
        "(($rules[0].FileSystemRights -band "
        "[System.Security.AccessControl.FileSystemRights]::FullControl) -eq "
        "[System.Security.AccessControl.FileSystemRights]::FullControl); "
        "if (-not $isOwnerOnly) { "
        "$acl.SetAccessRuleProtection($true, $false); "
        "$acl.Access | ForEach-Object { $null = $acl.RemoveAccessRule($_) }; "
        "$rule = New-Object System.Security.AccessControl.FileSystemAccessRule("
        "$identity.User, 'FullControl', 'Allow'); "
        "$null = $acl.AddAccessRule($rule); "
        "Set-Acl -LiteralPath $path -AclObject $acl }"
    )
    try:
        result = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=_WINDOWS_HELPER_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"timed out making {path.name} owner-only after {_WINDOWS_HELPER_TIMEOUT_S} seconds"
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(f"could not make {path.name} owner-only: {result.stderr.strip()}")


def _gcloud(config: Config, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return _run(["gcloud", *arguments, f"--project={config.project}", "--quiet"])


def _checked(result: subprocess.CompletedProcess[str], operation: str) -> str:
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"{operation} failed: {detail}")
    return result.stdout


def _instance_details(config: Config) -> dict[str, Any]:
    output = _checked(
        _gcloud(
            config,
            ["sql", "instances", "describe", config.instance, "--format=json"],
        ),
        f"describe Cloud SQL instance {config.instance}",
    )
    details = json.loads(output)
    if details.get("connectionName") != config.connection_name:
        raise RuntimeError(
            f"instance connection name is {details.get('connectionName')!r}, "
            f"expected {config.connection_name!r}"
        )
    return details


def _activation_policy(details: dict[str, Any]) -> str:
    settings = details.get("settings")
    if not isinstance(settings, dict):
        return "unknown"
    return str(settings.get("activationPolicy", "unknown"))


def _set_activation_policy(config: Config, policy: str) -> None:
    _checked(
        _gcloud(
            config,
            [
                "sql",
                "instances",
                "patch",
                config.instance,
                f"--activation-policy={policy}",
            ],
        ),
        f"set activation policy {policy}",
    )


def _wait_for_instance(config: Config, *, running: bool) -> dict[str, Any]:
    deadline = time.monotonic() + _INSTANCE_WAIT_SECONDS
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = _instance_details(config)
        state = last.get("state")
        if running and state == "RUNNABLE":
            return last
        if not running and state in {"STOPPED", "SUSPENDED"}:
            return last
        time.sleep(2)
    wanted = "RUNNABLE" if running else "stopped"
    raise RuntimeError(
        f"instance did not become {wanted}; last state was {last.get('state', 'unknown')}"
    )


def _resume_if_needed(config: Config) -> None:
    details = _instance_details(config)
    if details.get("state") == "RUNNABLE" and _activation_policy(details) == "ALWAYS":
        return
    _set_activation_policy(config, "ALWAYS")
    _wait_for_instance(config, running=True)
    print("instance activation_policy=ALWAYS")


def _ensure_databases(config: Config) -> None:
    output = _checked(
        _gcloud(
            config,
            [
                "sql",
                "databases",
                "list",
                f"--instance={config.instance}",
                "--format=value(name)",
            ],
        ),
        "list Cloud SQL databases",
    )
    existing = set(output.splitlines())
    for database in (config.database, config.test_database):
        if database in existing:
            continue
        _checked(
            _gcloud(
                config,
                ["sql", "databases", "create", database, f"--instance={config.instance}"],
            ),
            f"create database {database}",
        )
        print(f"created database {database}")


def _write_private(path: Path, value: str) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(value)
    _set_owner_only(temporary)
    temporary.replace(path)
    _set_owner_only(path)


def _ensure_password(config: Config) -> str:
    if config.password_file.exists():
        _set_owner_only(config.password_file)
        return config.password_file.read_text(encoding="utf-8")
    output = _checked(
        _gcloud(
            config,
            [
                "secrets",
                "versions",
                "access",
                "latest",
                f"--secret={config.password_secret}",
            ],
        ),
        f"read password secret {config.password_secret}",
    )
    password = output.rstrip("\n")
    if not password:
        raise RuntimeError(f"password secret {config.password_secret} is empty")
    _write_private(config.password_file, password)
    return password


def _write_pgpass(config: Config, password: str) -> None:
    escaped = password.replace("\\", "\\\\").replace(":", "\\:")
    _write_private(
        config.pgpass_file,
        f"127.0.0.1:{config.port}:*:{config.user}:{escaped}\n",
    )


def _start_proxy(config: Config) -> bool:
    if _proxy_is_running(config):
        print(f"proxy already running on port {config.port}")
        return False
    config.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    config.state_dir.chmod(0o700)
    with config.logfile.open("a", encoding="utf-8") as logfile:
        process = subprocess.Popen(
            _platform_command(
                [
                    "cloud-sql-proxy",
                    "--address",
                    "127.0.0.1",
                    "--port",
                    str(config.port),
                    config.connection_name,
                ]
            ),
            stdin=subprocess.DEVNULL,
            stdout=logfile,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    _write_private(config.pid_file, f"{process.pid}\n")
    _write_private(config.port_file, f"{config.port}\n")
    return True


def _wait_for_proxy(config: Config) -> None:
    deadline = time.monotonic() + _PROXY_WAIT_SECONDS
    while time.monotonic() < deadline:
        pid = _pid_from(config.pid_file)
        if pid is None:
            break
        command = _process_command(pid)
        if not command:
            time.sleep(0.1)
            continue
        if "cloud-sql-proxy" not in command or config.connection_name not in command:
            break
        try:
            with socket.create_connection(("127.0.0.1", config.port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    detail = ""
    if config.logfile.exists():
        detail = config.logfile.read_text(encoding="utf-8", errors="replace")[-2000:]
    raise RuntimeError(f"proxy did not become ready on port {config.port}: {detail.strip()}")


def _ensure_vector_extension(config: Config, database: str) -> None:
    environment = {**os.environ, "PGPASSFILE": str(config.pgpass_file)}
    result = _run(
        [
            "psql",
            "-h",
            "127.0.0.1",
            "-p",
            str(config.port),
            "-U",
            config.user,
            "-d",
            database,
            "-v",
            "ON_ERROR_STOP=1",
            "-tAc",
            "CREATE EXTENSION IF NOT EXISTS vector",
        ],
        env=environment,
    )
    _checked(result, f"create pgvector extension in {database}")


def _windows_taskkill(pid: int) -> str | None:
    """Terminate a Windows process tree, returning an error only on failure."""

    def run_taskkill(command: list[str]) -> subprocess.CompletedProcess[str] | str:
        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=_WINDOWS_HELPER_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return f"taskkill timed out after {_WINDOWS_HELPER_TIMEOUT_S} seconds"
        except OSError as exc:
            return f"taskkill failed: {exc}"

    result = run_taskkill(["taskkill", "/PID", str(pid), "/T", "/F"])
    if isinstance(result, str):
        return result
    if result.returncode == 0:
        return None

    try:
        command = _process_command(pid)
    except (subprocess.TimeoutExpired, RuntimeError) as exc:
        return str(exc)
    if not command:
        return None

    retry = run_taskkill(["taskkill", "/PID", str(pid), "/F"])
    if isinstance(retry, str):
        return retry
    try:
        command = _process_command(pid)
    except (subprocess.TimeoutExpired, RuntimeError) as exc:
        return str(exc)
    if not command:
        return None
    if retry.returncode != 0:
        detail = (retry.stderr or retry.stdout).strip() or "no diagnostic output"
        return f"taskkill exited {retry.returncode}: {detail}"
    return f"process {pid} survived wrapper taskkill"


def _posix_sigkill(pid: int) -> str | None:
    """Force-kill a POSIX process after its graceful shutdown window."""
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return None
    except OSError as exc:
        return str(exc)
    return None


def _stop_proxy(config: Config, *, quiet: bool = False) -> bool:
    pid = _pid_from(config.pid_file)
    if pid is None or not _proxy_is_running(config):
        config.pid_file.unlink(missing_ok=True)
        if not quiet:
            print("proxy not running")
        return True

    failure: str | None = None
    if os.name == "nt":
        try:
            failure = _windows_taskkill(pid)
        except subprocess.TimeoutExpired as exc:
            failure = str(exc)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError as exc:
            failure = str(exc)

    deadline = time.monotonic() + _STOP_WAIT_SECONDS
    command = ""
    try:
        while time.monotonic() < deadline:
            command = _process_command(pid)
            if not command:
                break
            time.sleep(0.1)
        else:
            failure = failure or f"process {pid} still exists after {_STOP_WAIT_SECONDS} seconds"
    except (subprocess.TimeoutExpired, RuntimeError) as exc:
        failure = str(exc)

    if os.name != "nt" and command:
        kill_failure = _posix_sigkill(pid)
        if kill_failure is not None:
            failure = kill_failure
        else:
            try:
                command = _process_command(pid)
            except (subprocess.TimeoutExpired, RuntimeError) as exc:
                failure = str(exc)
            else:
                failure = None if not command else failure or f"process {pid} survived SIGKILL"

    if command and failure is None:
        failure = f"process {pid} still exists after {_STOP_WAIT_SECONDS} seconds"
    if failure is not None:
        print(f"could not stop proxy pid={pid}: {failure}", file=sys.stderr)
        return False

    config.pid_file.unlink(missing_ok=True)
    if not quiet:
        print(f"stopped proxy pid={pid}")
    return True


def start(config: Config) -> int:
    _require_binaries("gcloud", "cloud-sql-proxy", "psql")
    try:
        _resume_if_needed(config)
        _ensure_databases(config)
        config.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        config.state_dir.chmod(0o700)
        password = _ensure_password(config)
        _write_pgpass(config, password)
        started = _start_proxy(config)
        _wait_for_proxy(config)
        for database in (config.database, config.test_database):
            _ensure_vector_extension(config, database)
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        _stop_proxy(config, quiet=True)
        return 1
    if started:
        print(f"proxy pid={_pid_from(config.pid_file)} port={config.port}")
    print(f"ready: {config.url}")
    return 0


def stop(config: Config) -> int:
    return 0 if _stop_proxy(config) else 1


def status(config: Config) -> int:
    _require_binaries("gcloud")
    try:
        details = _instance_details(config)
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    proxy = "running" if _proxy_is_running(config) else "stopped"
    pid = _pid_from(config.pid_file)
    print(
        f"instance={details.get('state', 'unknown')} "
        f"activation_policy={_activation_policy(details)} "
        f"proxy={proxy} pid={pid or 'none'} port={config.port} url={config.url}"
    )
    return 0 if details.get("state") == "RUNNABLE" and proxy == "running" else 1


def pause(config: Config) -> int:
    _require_binaries("gcloud")
    try:
        if not _stop_proxy(config, quiet=True):
            return 1
        _set_activation_policy(config, "NEVER")
        details = _wait_for_instance(config, running=False)
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"instance={details.get('state', 'unknown')} activation_policy=NEVER")
    return 0


def resume(config: Config) -> int:
    _require_binaries("gcloud")
    try:
        _set_activation_policy(config, "ALWAYS")
        details = _wait_for_instance(config, running=True)
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"instance={details.get('state', 'unknown')} activation_policy=ALWAYS")
    return 0


def config_command(config: Config) -> int:
    print("\n".join(config.as_lines()))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run this workspace against the shared Cloud SQL dev database.",
    )
    parser.add_argument(
        "command",
        choices=("start", "stop", "status", "config", "pause", "resume"),
    )
    arguments = parser.parse_args(argv)
    try:
        config = resolve_config()
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return {
        "start": start,
        "stop": stop,
        "status": status,
        "config": config_command,
        "pause": pause,
        "resume": resume,
    }[arguments.command](config)


if __name__ == "__main__":
    raise SystemExit(main())
