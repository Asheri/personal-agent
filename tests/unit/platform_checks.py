"""Platform-specific assertions shared by unit tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

WINDOWS_HELPER_TIMEOUT_S = 10


def posix_shell(name: str) -> tuple[str, Path | None]:
    """Find Git for Windows' POSIX shell without falling through to WSL."""
    if os.name != "nt":
        return name, None

    git = shutil.which("git")
    candidates = []
    if git:
        candidates.append(Path(git).resolve().parent.parent / "usr" / "bin" / f"{name}.exe")
    candidates.append(Path(r"C:\Program Files\Git\usr\bin") / f"{name}.exe")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate), candidate.parent
    pytest.skip(
        f"Git for Windows {name}.exe was not found; install Git for Windows "
        "with its POSIX tools to run this documentation command"
    )


def windows_acl_snapshot(path: Path) -> dict[str, object]:
    """Read a Windows ACL as structured data without exposing file contents."""
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        raise AssertionError("PowerShell is required to inspect a Windows ACL")
    target = str(path).replace("'", "''")
    script = (
        f"$path = '{target}'; "
        "$acl = Get-Acl -LiteralPath $path; "
        "$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent(); "
        "$rules = @($acl.Access); "
        "$rule = $rules | Select-Object -First 1; "
        "$sid = ''; "
        "$rights = ''; "
        "$accessType = ''; "
        "$inherited = $false; "
        "if ($null -ne $rule) { "
        "$sid = $rule.IdentityReference.Translate("
        "[System.Security.Principal.SecurityIdentifier]).Value; "
        "$rights = $rule.FileSystemRights.ToString(); "
        "$accessType = $rule.AccessControlType.ToString(); "
        "$inherited = [bool]$rule.IsInherited } "
        "[pscustomobject]@{ "
        "Protected = [bool]$acl.AreAccessRulesProtected; "
        "Count = $rules.Count; Sid = $sid; CurrentSid = $identity.User.Value; "
        "Rights = $rights; "
        "AccessType = $accessType; Inherited = $inherited "
        "} | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=WINDOWS_HELPER_TIMEOUT_S,
    )
    if result.returncode != 0:
        raise AssertionError(f"could not inspect ACL for {path.name}: {result.stderr.strip()}")
    return json.loads(result.stdout)
