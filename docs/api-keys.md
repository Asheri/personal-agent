# Storing a provider key

A model key is different from other configuration: editing the file later does
not undo a leak. Once a key is in a commit, every clone, fork, and pull request
carries a copy, and the only fix is revoking it at the provider.

So this repository asks for three things from the machine that holds the key:
it is not in a file git can see, it is not in a command line, and it is not in
a report.

## Where the key lives

macOS keychain. Create the entry once, in a terminal, with a silent read so the
value never reaches the shell history or the screen:

```bash
read -rs KEY && security add-generic-password -U -s pcmem-siliconflow \
  -a "$USER" -w "$KEY" && unset KEY
```

`read -rs` means no echo; `-U` overwrites an existing entry with the same
service name; `unset` drops the variable from the shell.

Linux has the same shape with a different store: `secret-tool store` (Secret
Service) or `pass insert`. The property that matters is unchanged: the secret
sits in an encrypted store, not in a dotfile.

## How a process gets it

Source the loader, which reads the entry and exports it for that shell only:

```bash
source scripts/load_keychain_secret.sh SCI_RAG_OPENAI_API_KEY pcmem-siliconflow
uv run python scripts/run_benchmark_eval.py --dataset ... --output ...
```

The loader prints nothing, so `set -x`, a pasted transcript, or a CI log cannot
echo the value. If the keychain item is missing it says so and exports nothing,
which turns into a credential error instead of a silent run against no key.

## What the repository refuses

- `.env` and `.env.*` are ignored by git, and `scripts/check_no_secrets.py`
  fails the commit if one is ever staged anyway.
- The same script fails on a credential-shaped string in any tracked file: an
  OpenAI-style `sk-` key of 32 characters or more, a GitHub token, an AWS key,
  a Google key, a private key block, a Bilibili `SESSDATA`, a Hugging Face
  token. The length is the discriminator, so a test fixture such as
  `sk-topsecret1234567890` passes and a real key does not.
- A line may opt out with a trailing `# allow-secret`, which is a decision a
  reviewer can see in the diff.
- Pre-commit runs the check on staged files, and CI runs it on the whole tree,
  so a local hook that was never installed does not matter.

## What a report contains

Evaluation reports record the model identity (`provider:model`), the embedding
identity, the domain digest, and the decoding settings. They do not record the
key, the base URL, or the environment. `sci_rag.evals.report.provenance_block`
is the function that decides this, and it is the place to look before adding a
field.

The benchmark runner writes under `.context/`, which git ignores. If a report
ever has to leave the machine, it is safe to hand over as it is.

## If a key does leak

Revoke it at the provider first; deleting the file does not help. Then rotate
the entry in the keychain with the same command, and check whether the key
reached a fork, a cached pull request page, or a CI log, because a rewritten
history does not remove copies that were already fetched.
