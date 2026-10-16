# Security policy

DecisionTrace stores records of decisions that may reference sensitive business data, so we
treat security and privacy bugs as high priority.

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private reporting:
**Security → Report a vulnerability** on this repository. We aim to acknowledge reports
within 3 working days and to agree a disclosure date with you.

Especially in scope:

- secrets or PII reaching disk despite redaction
- ways to alter or delete records without `dt verify` detecting it
- any path where traces leave the machine without the user's explicit action

## Supported versions

Pre-1.0: only the latest release receives fixes.
