from __future__ import annotations

import pytest

from decisiontrace.redact import Redactor, hash_text, redact_text, summarize

SECRETS = {
    "anthropic": "sk-ant-api03-Xq7_abcDEF0123456789ghijklmnopqrstuvWX",
    "openai": "sk-proj-AbCdEf0123456789GhIjKlMnOpQrStUv",
    "openai_legacy": "sk-AbCdEf0123456789GhIjKlMnOpQrStUv01",
    "stripe": "sk_live_51HxAbCdEf0123456789",
    "github": "ghp_abcdefghijklmnopqrstuvwxyz0123456789AB",
    "github_pat": "github_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz0123",
    "slack": "xoxb-123456789012-abcdefghijkl",
    "aws": "AKIAIOSFODNN7EXAMPLE",
    "google": "AIzaSyA-1234567890abcdefghijklmnopqrstu",
    "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36",
}


@pytest.mark.parametrize("name", SECRETS)
def test_secrets_removed(name: str) -> None:
    secret = SECRETS[name]
    out = redact_text(f"deploy with {secret} now")
    assert secret not in out
    assert "[REDACTED:" in out
    assert out.startswith("deploy with ") and out.endswith(" now")


@pytest.mark.parametrize(
    "text",
    [
        "password=correct-horse-battery",
        "API_KEY: 'zzTopSecretValue99'",
        "client_secret = abcdef123456",
        "export AUTH_TOKEN=abc123def456ghi",
        "Authorization: Bearer abcdefghijklmnop1234567890",
        "postgres://admin:s3cr3tpw@db.internal:5432/app",
    ],
)
def test_secret_assignments(text: str) -> None:
    out = redact_text(text)
    assert "[REDACTED:" in out
    for leaked in ("correct-horse", "zzTopSecret", "abcdef123456", "abc123def456", "s3cr3tpw"):
        assert leaked not in out


def test_private_key_block() -> None:
    key = (
        "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAA\nAAAA\n"
        "-----END OPENSSH PRIVATE KEY-----"
    )
    out = redact_text(f"key:\n{key}\nend")
    assert "b3BlbnNz" not in out
    assert out.endswith("\nend")


@pytest.mark.parametrize(
    ("text", "kind", "raw"),
    [
        ("mail praveen.singh@example.co.in today", "EMAIL", "praveen.singh@example.co.in"),
        ("call +91 98765 43210", "PHONE", "98765 43210"),
        ("call 9876543210", "PHONE", "9876543210"),
        ("call (415) 555-0100", "PHONE", "555-0100"),
        ("call +1 415-555-0100", "PHONE", "555-0100"),
        ("PAN ABCPE1234F on file", "PAN", "ABCPE1234F"),
        ("Aadhaar 2341 2341 2346", "AADHAAR", "2341 2341 2346"),
        ("card 4111 1111 1111 1111 exp", "CARD", "4111 1111 1111 1111"),
        ("card 5500-0000-0000-0004", "CARD", "5500-0000-0000-0004"),
    ],
)
def test_pii_pseudonymised(text: str, kind: str, raw: str) -> None:
    out = redact_text(text)
    assert raw not in out
    assert f"[{kind}:" in out


@pytest.mark.parametrize(
    "text",
    [
        "Refund $850 for order 7731",
        "Approve PO for 40 laptops ($62,400)",
        "Merge PR #212 at 2026-10-15T09:30:00Z",
        "Fix bug 10023 in billing module",
        "commit 9f3d27e4b1c0a77d2e1f",
        "order 123456789012",  # 12 digits, fails Verhoeff
        "invoice 4111111111111112",  # 16 digits, fails Luhn
        "version 1.4.2 released 2026-10-15",
        "sk-short",
        "the token was rotated yesterday",
        "file src/billing/due_dates.py line 42",
    ],
)
def test_ordinary_text_untouched(text: str) -> None:
    assert redact_text(text) == text


def test_pseudonyms_are_stable_and_salted() -> None:
    a = Redactor(salt=b"one").text("a@b.com")
    assert a == Redactor(salt=b"one").text("A@B.com")
    assert a != Redactor(salt=b"two").text("a@b.com")


def test_record_walk_skips_structural_values_but_not_emails_in_ids() -> None:
    red = Redactor()
    out = red.record(
        {
            "id": "01M4ZCMBM0KTCPX4FH08G1VSBH",
            "hash": "sha256:" + "1" * 64,
            "started_at": "2026-10-15T09:00:00Z",
            "actor": {"type": "human", "id": "praveen@example.com"},
            "intent": "Email bob@example.com",
        }
    )
    assert out["id"] == "01M4ZCMBM0KTCPX4FH08G1VSBH"
    assert out["hash"] == "sha256:" + "1" * 64
    assert out["started_at"] == "2026-10-15T09:00:00Z"
    assert "@" not in out["actor"]["id"]
    assert "@" not in out["intent"]
    assert red.counts["email"] == 2


def test_helpers() -> None:
    assert hash_text("x").startswith("sha256:")
    s = summarize("line one\n\nline two with a@b.com " + "x" * 300, limit=50)
    assert len(s) == 50 and "\n" not in s and "@" not in s
