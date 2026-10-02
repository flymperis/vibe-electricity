from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String, Text

from .db import Base
from .parsing.schema import FIELDS

_COLUMN_TYPES = {"money": Float, "kwh": Float, "rate": Float, "kva": Float, "int": Integer, "date": Date, "text": String}


def utcnow() -> datetime:
    """Naive UTC (SQLite stores no zone)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Bill(Base):
    """One electricity bill (unique by supplier bill number). Several Paperless
    documents can point to it when the same PDF was uploaded more than once."""

    __tablename__ = "bills"

    id = Column(Integer, primary_key=True)
    paperless_id = Column(Integer, index=True)  # the document it was read from
    # one column per bill field (see parsing/schema.py)
    for _f in FIELDS:
        locals()[_f.name] = Column(_COLUMN_TYPES[_f.kind], index=_f.name in ("bill_number", "period_end"))
    del _f
    tiers_json = Column(Text)  # [[kWh, €/kWh], ...]
    method = Column(String)  # rules | rules+llm | llm | manual
    status = Column(String)  # ok | warn | fail
    checks_json = Column(Text)
    overrides_json = Column(Text)  # {field: value} edited by hand; survive re-reading
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # ---- derived values used by the UI and the charts ----
    @property
    def checks(self) -> list[dict]:
        return json.loads(self.checks_json or "[]")

    @property
    def overrides(self) -> dict:
        return json.loads(self.overrides_json or "{}")

    @property
    def tiers(self) -> list[list[float]]:
        return json.loads(self.tiers_json or "[]")

    @property
    def period_cost(self) -> float | None:
        """What the period's electricity cost: the payable total without the
        previous unpaid balance and without the ±cents rounding carried between bills."""
        if self.total_payable is None:
            return None
        return round(self.total_payable - (self.previous_unpaid or 0) - (self.rounding_current or 0)
                     - (self.rounding_previous or 0), 2)

    @property
    def period_days(self) -> int | None:
        if self.days:
            return self.days
        if self.period_start and self.period_end:
            return (self.period_end - self.period_start).days + 1
        return None

    @property
    def all_in_rate(self) -> float | None:
        cost = self.period_cost
        return round(cost / self.kwh, 4) if cost is not None and self.kwh else None

    @property
    def kwh_per_day(self) -> float | None:
        d = self.period_days
        return round(self.kwh / d, 2) if self.kwh is not None and d else None

    @property
    def cost_per_day(self) -> float | None:
        d, c = self.period_days, self.period_cost
        return round(c / d, 2) if c is not None and d else None

    @property
    def month(self) -> date | None:
        """The calendar month a bill belongs to: the month of the middle of its period."""
        if not (self.period_start and self.period_end):
            return self.issue_date.replace(day=1) if self.issue_date else None
        mid = self.period_start + timedelta(days=(self.period_end - self.period_start).days // 2)
        return mid.replace(day=1)

    @property
    def taxes_and_fees(self) -> float | None:
        """Δήμος, ΕΡΤ, ΕΦΚ, ειδ. τέλος and ΦΠΑ (everything that is neither energy supply nor network)."""
        if self.misc_total is None and self.vat is None:
            return None
        rounding = (self.rounding_current or 0) + (self.rounding_previous or 0)
        return round((self.misc_total or 0) - rounding + (self.vat or 0), 2)


class Document(Base):
    """A Paperless document seen with the electricity tag, and what became of it."""

    __tablename__ = "documents"

    paperless_id = Column(Integer, primary_key=True, autoincrement=False)
    title = Column(String)
    checksum = Column(String, index=True)
    modified = Column(String)  # Paperless 'modified' timestamp: re-read when it changes
    status = Column(String, default="new")  # new | parsed | duplicate | skipped | error
    bill_id = Column(Integer, ForeignKey("bills.id", ondelete="SET NULL"), index=True)
    message = Column(Text)
    processed_at = Column(DateTime)


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String, primary_key=True)
    value = Column(Text)


class Event(Base):
    """Short activity log shown on the Settings page."""

    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    ts = Column(DateTime, default=utcnow, index=True)
    level = Column(String, default="info")  # info | warn | error
    message = Column(Text)
    paperless_id = Column(Integer)
