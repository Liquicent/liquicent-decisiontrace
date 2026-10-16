"""Where the store lives and how it is configured.

Default home is ``~/.decisiontrace`` (override with ``DT_HOME`` or ``dt --home``). It holds
``traces.db`` (the store) and ``config.toml``. Nothing ever leaves this directory.
"""

from __future__ import annotations

import os
import secrets
import tomllib
from dataclasses import dataclass
from pathlib import Path

DB_NAME = "traces.db"
CONFIG_NAME = "config.toml"

_TEMPLATE = """\
# DecisionTrace configuration. Everything stays on this machine.

[store]
# Store prompt/response bodies? Off by default: records keep hashes and summaries only.
bodies = false
# Namespace for records written by local adapters.
namespace = "local"

[redaction]
# Keys the pseudonyms used for e-mails, phones, PAN/Aadhaar. Keep it secret; changing it
# breaks linking between old and new traces about the same person.
salt = "{salt}"
"""


def default_home() -> Path:
    return Path(os.environ.get("DT_HOME") or Path.home() / ".decisiontrace")


@dataclass(frozen=True)
class Config:
    home: Path
    store_bodies: bool = False
    namespace: str = "local"
    salt: bytes = b"decisiontrace"

    @property
    def db_path(self) -> Path:
        return self.home / DB_NAME

    @property
    def config_path(self) -> Path:
        return self.home / CONFIG_NAME


def init_home(home: Path | None = None) -> Config:
    """Create the home directory and config file if missing (idempotent)."""
    home = home or default_home()
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = home / CONFIG_NAME
    if not path.exists():
        path.write_text(_TEMPLATE.format(salt=secrets.token_hex(16)), encoding="utf-8")
        path.chmod(0o600)
    return load_config(home)


def load_config(home: Path | None = None) -> Config:
    home = home or default_home()
    path = home / CONFIG_NAME
    if not path.exists():
        return Config(home=home)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    store = data.get("store", {})
    redaction = data.get("redaction", {})
    return Config(
        home=home,
        store_bodies=bool(store.get("bodies", False)),
        namespace=str(store.get("namespace", "local")),
        salt=str(redaction.get("salt", "decisiontrace")).encode(),
    )
