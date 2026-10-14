"""Platform-specific protection for generated credential files."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

WINDOWS_HELPER_TIMEOUT_S = 10


def set_owner_only(path: Path) -> None:
    """Restrict a generated file to its owner on POSIX or Windows."""
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
            timeout=WINDOWS_HELPER_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"timed out making {path.name} owner-only after {WINDOWS_HELPER_TIMEOUT_S} seconds"
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(f"could not make {path.name} owner-only: {result.stderr.strip()}")
