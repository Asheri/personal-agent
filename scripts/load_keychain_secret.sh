#!/usr/bin/env bash
# Load one provider key from the macOS keychain into an environment variable.
#
#   source scripts/load_keychain_secret.sh SCI_RAG_OPENAI_API_KEY pcmem-siliconflow
#
# The value is read into a local variable, exported, and the variable cleared.
# Nothing is printed, so the key stays out of the terminal scrollback, out of
# the shell history, and out of any transcript that quotes this session.
#
# Create the entry once, without putting the key in a command line:
#
#   read -rs KEY && security add-generic-password -U -s pcmem-siliconflow \
#     -a "$USER" -w "$KEY" && unset KEY
#
# Linux equivalents: `secret-tool store --label=... service ...` (Secret
# Service) or `pass insert ...`. Both have the same property: the secret lives
# in an encrypted store, not in a dotfile.

set -euo pipefail

variable="${1:?usage: source load_keychain_secret.sh <ENV_VAR> <keychain-service>}"
service="${2:?usage: source load_keychain_secret.sh <ENV_VAR> <keychain-service>}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "load_keychain_secret.sh needs macOS; use secret-tool or pass on Linux" >&2
  return 1 2>/dev/null || exit 1
fi

if ! value="$(security find-generic-password -s "$service" -w 2>/dev/null)"; then
  echo "no keychain item named '$service'; see docs/api-keys.md" >&2
  return 1 2>/dev/null || exit 1
fi

export "${variable}=${value}"
unset value
