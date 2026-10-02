"""Pick the best reading of a bill: the rules for known layouts, the LLM for the
rest or to fill gaps, judged by the validator."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from . import dei, validate
from .schema import FIELDS, BillData

log = logging.getLogger("vibe_electricity.extract")

_RANK = {"ok": 2, "warn": 1, "fail": 0}


@dataclass
class Extraction:
    data: BillData
    method: str  # rules | rules+llm | llm
    status: str  # ok | warn | fail
    checks: list[validate.Check] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def looks_like_electricity_bill(text: str) -> bool:
    if not re.search(r"kWh", text, re.I):
        return False
    return bool(re.search(r"ηλεκτρικ|ΗΛΕΚΤΡΙΚ|ρεύμα|ΔΕΔΔΗΕ|ΑΔΜΗΕ|ΕΤΜΕΑΡ|Παροχής|παροχής", text))


def _judge(data: BillData, method: str, errors: list[str]) -> Extraction:
    checks = validate.checks(data)
    return Extraction(data, method, validate.status(checks), checks, errors)


def _score(e: Extraction) -> tuple[int, int]:
    return _RANK[e.status], sum(c.ok for c in e.checks)


def _merge(base: BillData, extra: BillData) -> BillData:
    merged = BillData(**{f.name: getattr(base, f.name) for f in FIELDS})
    merged.energy_tiers = list(base.energy_tiers)
    for f in FIELDS:
        if getattr(merged, f.name) is None and getattr(extra, f.name) is not None:
            setattr(merged, f.name, getattr(extra, f.name))
    return merged


def extract(text: str, llm: Callable[[str], BillData] | None = None, force_llm: bool = False) -> Extraction:
    candidates: list[Extraction] = []
    errors: list[str] = []
    rules = None
    if dei.is_dei(text):
        rules = dei.parse(text)
        candidates.append(_judge(rules, "rules", errors))
        if candidates[0].status == "ok" and not force_llm:
            return candidates[0]

    if llm is not None:
        try:
            from_llm = llm(text)
        except Exception as exc:  # noqa: BLE001  (network / model errors are reported, not fatal)
            log.warning("LLM extraction failed: %s", exc)
            errors.append(f"LLM: {exc}"[:300])
        else:
            if rules is not None:
                candidates.append(_judge(_merge(rules, from_llm), "rules+llm", errors))
            candidates.append(_judge(from_llm, "llm", errors))

    if not candidates:
        return Extraction(BillData(), "none", "fail",
                          [validate.Check("required", False, "Άγνωστη μορφή λογαριασμού και το AI δεν είναι διαθέσιμο")],
                          errors)
    best = max(candidates, key=_score)  # max() keeps the first on ties: rules win
    best.errors = errors
    return best
