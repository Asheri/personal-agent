# Security policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately through GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository (Security tab, "Report a vulnerability"). Do not open
a public issue for security problems. You can expect an acknowledgment
within a week.

## Scope notes for deployers

Things worth knowing when you run this kit:

- With no `SCI_RAG_API_KEYS` configured, the server runs open and says
  so at startup. That mode is for localhost only.
- `GET /health` and `GET /v1/corpus-manifest` are intentionally
  unauthenticated; they expose counts and configuration, never document
  content.
- Retrieval license scoping is enforced in SQL before ranking, and an
  empty allowlist returns nothing. If you host restricted documents,
  give external callers keys and make them pass an explicit
  `license_classes` allowlist.
- Bring-your-own LLM keys are used per request and never persisted or
  logged; generation failures return the exception class only, with
  detail kept in server logs.
- The bundled rate limiter is per-process. Put a shared limiter or
  gateway in front of multi-instance deployments.
