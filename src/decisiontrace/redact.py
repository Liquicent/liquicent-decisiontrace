"""Secret and PII redaction, applied to every record before it is written.

Secrets are replaced outright (``[REDACTED:aws_key]``). Personal identifiers are replaced
with a stable pseudonym (``[EMAIL:3f9a1c07]``) derived from a per-store salt, so traces about
the same customer can still be linked without the identifier ever reaching disk.

Redaction is conservative on purpose: a false positive costs a little readability, a false
negative leaks a secret into an append-only store that can't be edited.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections import Counter

TYPE_CHECKING = False
if TYPE_CHECKING:  # typing costs ~7 ms to import; the hook can't afford it
    from collections.abc import Callable
    from typing import Any

# Keys whose values are structural (ids, hashes, enums, timestamps). They are skipped only
# when the value also *looks* structural, so an e-mail used as an actor id is still caught.
STRUCTURAL_KEYS = frozenset(
    {
        "record_type",
        "schema_version",
        "id",
        "trace_id",
        "target_id",
        "namespace",
        "decision_kind",
        "workflow",
        "type",
        "status",
        "result",
        "engine",
        "enforced",
        "rejected_by",
        "hash",
        "prev_hash",
        "parameters_hash",
        "diff_hash",
        "started_at",
        "ended_at",
        "at",
        "recorded_at",
        "corrected_at",
        "provider",
        "capabilities",
    }
)

_STRUCTURAL_VALUE = re.compile(
    r"^(?:[0-9A-HJKMNP-TV-Z]{26}"  # ULID
    r"|sha256:[0-9a-f]{64}"
    r"|\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+-]\d{2}:\d{2})"
    r"|[a-z0-9_.\-]{1,128})$"
)

_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "private_key",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----(?s:.*?)(?:-----END [A-Z ]*PRIVATE KEY-----|$)"
        ),
    ),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai_key", re.compile(r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{20,}")),
    ("stripe_key", re.compile(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{16,}")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})")),
    ("slack_token", re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}")),
    ("aws_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")),
    ("url_credentials", re.compile(r"(?<=://)[^\s/:@]+:[^\s/@]+(?=@)")),
    ("bearer_token", re.compile(r"(?i:(?<=bearer ))[A-Za-z0-9_\-\.=+/]{16,}")),
    (
        "secret_assignment",
        re.compile(
            r"(?i:(?<![A-Za-z0-9])(?P<assign_key>(?:api[_-]?key|secret|password|passwd|pwd|"
            r"token|access[_-]?key|private[_-]?key|client[_-]?secret|auth)"
            r"[A-Za-z0-9_\-]*\s*[:=]\s*[\"']?)[^\s\"',;]{6,})"
        ),
    ),
]

_SECRETS = re.compile(
    "|".join(f"(?P<{kind}>{pattern.pattern})" for kind, pattern in _SECRET_PATTERNS),
)
_DROP_DIGITS = str.maketrans("", "", "0123456789")

# Every pattern below needs one of these; text without them is returned untouched (fast path).
_MAYBE_SENSITIVE = re.compile(r"[\d@:=]|sk-|---|xox|AKIA|ASIA|AIza|eyJ|bearer", re.I)

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_CARD = re.compile(r"(?<!\d)(?:\d[ \-]?){12,18}\d(?!\d)")
_AADHAAR = re.compile(r"(?<!\d)[2-9]\d{3}[ \-]?\d{4}[ \-]?\d{4}(?!\d)")
_PAN = re.compile(r"\b[A-Z]{3}[ABCFGHLJPTK][A-Z]\d{4}[A-Z]\b")
_PHONE = re.compile(
    r"(?<![\w+])(?:"
    r"\+\d{1,3}[ \-]?(?:\(?\d{1,4}\)?[ \-]?){1,4}\d{2,4}"  # international, +CC ...
    r"|\(\d{3}\) ?\d{3}-\d{4}"  # (415) 555-0100
    r"|\d{3}-\d{3}-\d{4}"  # 415-555-0100
    r"|[6-9]\d{9}"  # Indian mobile
    r")(?!\w)"
)


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


_VERHOEFF_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_VERHOEFF_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def _verhoeff_ok(digits: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(ch)]]
    return c == 0


class Redactor:
    """Redacts strings and whole records. ``salt`` keys the PII pseudonyms.

    (A plain class, not a dataclass: importing ``dataclasses`` costs ~15 ms, which matters
    inside a hook that must finish in under 50 ms.)
    """

    def __init__(self, salt: bytes = b"decisiontrace") -> None:
        self.salt = salt
        self.counts: Counter[str] = Counter()

    def _pseudonym(self, kind: str, value: str) -> str:
        normalised = re.sub(r"[\s\-()]", "", value).lower()
        digest = hmac.new(self.salt, normalised.encode(), hashlib.sha256).hexdigest()[:8]
        self.counts[kind] += 1
        return f"[{kind.upper()}:{digest}]"

    def _secret(self, kind: str) -> str:
        self.counts[kind] += 1
        return f"[REDACTED:{kind}]"

    def text(self, value: str) -> str:
        """Return ``value`` with secrets removed and personal identifiers pseudonymised."""
        if not _MAYBE_SENSITIVE.search(value):
            return value
        out = _SECRETS.sub(self._secret_match, value)
        if "@" in out:
            out = _EMAIL.sub(lambda m: self._pseudonym("email", m.group()), out)
        digits = len(out) - len(out.translate(_DROP_DIGITS))
        if digits >= 4:
            out = _PAN.sub(lambda m: self._pseudonym("pan", m.group()), out)
        if digits >= 10:
            out = self._checked(out, _CARD, _luhn_ok, "card", lambda d: 13 <= len(d) <= 19)
            out = self._checked(out, _AADHAAR, _verhoeff_ok, "aadhaar", lambda d: len(d) == 12)
            out = _PHONE.sub(self._phone, out)
        return out

    def _secret_match(self, match: re.Match[str]) -> str:
        kind = match.lastgroup or "secret"
        if kind == "secret_assignment":
            return match.group("assign_key") + self._secret(kind)
        return self._secret(kind)

    def _phone(self, match: re.Match[str]) -> str:
        if sum(c.isdigit() for c in match.group()) < 10:
            return match.group()
        return self._pseudonym("phone", match.group())

    def _checked(
        self,
        text: str,
        pattern: re.Pattern[str],
        check: Callable[[str], bool],
        kind: str,
        length_ok: Callable[[str], bool],
    ) -> str:
        def sub(match: re.Match[str]) -> str:
            digits = re.sub(r"\D", "", match.group())
            if length_ok(digits) and check(digits):
                return self._pseudonym(kind, match.group())
            return match.group()

        return pattern.sub(sub, text)

    def record(self, data: Any, key: str | None = None) -> Any:
        """Redact every free-text string in a JSON-compatible structure."""
        if isinstance(data, dict):
            return {k: self.record(v, k) for k, v in data.items()}
        if isinstance(data, list):
            return [self.record(v, key) for v in data]
        if isinstance(data, str):
            if key in STRUCTURAL_KEYS and _STRUCTURAL_VALUE.match(data):
                return data
            return self.text(data)
        return data


def redact_text(value: str, salt: bytes = b"decisiontrace") -> str:
    """Convenience wrapper for one-off strings."""
    return Redactor(salt=salt).text(value)


def hash_text(value: str) -> str:
    """SHA-256 reference for a body that is not stored."""
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def summarize(value: str, limit: int = 200, salt: bytes = b"decisiontrace") -> str:
    """Redacted, single-line, length-capped summary of a body."""
    flat = " ".join(redact_text(value, salt).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"
