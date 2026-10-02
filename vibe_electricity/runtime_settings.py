"""Settings that can be changed on the Settings page without a restart.
Stored as key/value rows; a missing row falls back to the environment default."""

from __future__ import annotations

from dataclasses import dataclass, fields

from sqlalchemy.orm import Session

from .config import get_settings
from .models import Setting


@dataclass
class Runtime:
    paperless_tag: str
    ollama_url: str
    ollama_model: str
    llm_enabled: bool
    sync_interval_minutes: int


def _cast(name: str, raw: str, default):
    if isinstance(default, bool):
        return raw.lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        try:
            return int(raw)
        except ValueError:
            return default
    return raw


def load(s: Session) -> Runtime:
    env = get_settings()
    stored = {row.key: row.value for row in s.query(Setting).all()}
    values = {}
    for f in fields(Runtime):
        default = getattr(env, f.name)
        values[f.name] = _cast(f.name, stored[f.name], default) if f.name in stored else default
    return Runtime(**values)


def save(s: Session, **values) -> None:
    known = {f.name for f in fields(Runtime)}
    for key, value in values.items():
        if key not in known:
            raise KeyError(key)
        row = s.get(Setting, key) or Setting(key=key)
        row.value = str(value)
        s.add(row)
