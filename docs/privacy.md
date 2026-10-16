# Privacy & security

## Never leaves your machine

No account, no server, no telemetry. The only network calls are ones you ask for:
`dt ask --llm` (sends the matching, redacted records to Anthropic) and the one-time model
download if you enable embeddings.

## Redacted before anything is written

- **Secrets removed**: Anthropic, OpenAI, Stripe, GitHub, Slack, AWS and Google keys, JWTs,
  private keys, bearer tokens, credentials in URLs, `password=` / `api_key:` style values.
- **Personal data pseudonymised**: e-mail addresses, phone numbers, cards (Luhn-checked),
  Indian PAN and Aadhaar (Verhoeff-checked) become `[EMAIL:3f9a1c07]`-style tokens keyed by
  a per-store salt, so traces about the same person still link.
- The Claude Code hook redacts *before* writing its queue file, too.

## Not stored at all

- model reasoning / chain-of-thought, and assistant replies
- prompt and response bodies (unless `bodies = true` in `config.toml`; even then redacted)
- file contents, command output, tool results, OpenTelemetry message attributes

Records hold references, hashes and short redacted summaries instead.

## Tamper-evident, not tamper-proof

The hash chain detects edited, deleted, inserted or reordered records. Someone who can
rewrite the *entire* file can forge a consistent chain — so anchor it: `dt verify` prints
the head hash; commit or publish it somewhere you trust.

## Erasure

Optional bodies live outside the chain and can be erased without breaking `dt verify`.
Records themselves are append-only by design; keep personal data out of them (redaction
does most of this) and use namespaces to separate stores.

## Reporting a vulnerability

See [SECURITY.md](https://github.com/vpsingh88/liquicent-decisiontrace/blob/main/SECURITY.md).
