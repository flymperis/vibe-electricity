"""Numbers for the dashboard and the charts, computed from the stored bills."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from .models import Bill

MONTHS = ["Ιαν", "Φεβ", "Μαρ", "Απρ", "Μάι", "Ιουν", "Ιουλ", "Αυγ", "Σεπ", "Οκτ", "Νοε", "Δεκ"]
MONTHS_FULL = ["Ιανουάριος", "Φεβρουάριος", "Μάρτιος", "Απρίλιος", "Μάιος", "Ιούνιος", "Ιούλιος",
               "Αύγουστος", "Σεπτέμβριος", "Οκτώβριος", "Νοέμβριος", "Δεκέμβριος"]


def month_label(d: date | None, full: bool = False) -> str:
    if d is None:
        return "—"
    return f"{(MONTHS_FULL if full else MONTHS)[d.month - 1]} {d.year if full else str(d.year)[2:]}"


def usable_bills(s: Session) -> list[Bill]:
    bills = s.query(Bill).filter(Bill.status != "fail").all()
    bills = [b for b in bills if b.period_end and b.kwh is not None and b.total_payable is not None]
    return sorted(bills, key=lambda b: (b.period_end, b.id))


def _months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + b.month - a.month


def _window(bills: list[Bill], end: date, months: int) -> list[Bill]:
    return [b for b in bills if 0 <= _months_between(b.month, end) < months]


def _agg(bills: list[Bill]) -> dict | None:
    if not bills:
        return None
    kwh = sum(b.kwh for b in bills)
    cost = sum(b.period_cost for b in bills)
    days = sum(b.period_days or 0 for b in bills)
    return {
        "bills": len(bills),
        "kwh": kwh,
        "cost": round(cost, 2),
        "days": days,
        "kwh_per_day": round(kwh / days, 2) if days else None,
        "cost_per_month": round(cost / days * 30.44, 2) if days else None,
        "rate": round(cost / kwh, 4) if kwh else None,
    }


def _pct(new: float | None, old: float | None) -> float | None:
    if new is None or not old:
        return None
    return round((new - old) / old * 100, 1)


def summary(bills: list[Bill]) -> dict:
    if not bills:
        return {}
    last = bills[-1]
    end = last.month
    cur = _agg(_window(bills, end, 12))
    prev_bills = [b for b in bills if 12 <= _months_between(b.month, end) < 24]
    prev = _agg(prev_bills)
    same_month_last_year = next((b for b in bills if _months_between(b.month, end) == 12), None)
    previous = bills[-2] if len(bills) > 1 else None
    return {
        "last": last,
        "previous": previous,
        "same_month_last_year": same_month_last_year,
        "last_vs_prev_kwh_day": _pct(last.kwh_per_day, previous.kwh_per_day if previous else None),
        "last_vs_year_ago_kwh_day": _pct(last.kwh_per_day,
                                         same_month_last_year.kwh_per_day if same_month_last_year else None),
        "y": cur,
        "prev_y": prev if prev and prev["days"] >= 300 else None,
        "y_vs_prev_cost": _pct(cur["cost_per_month"], prev["cost_per_month"]) if prev and prev["days"] >= 300 else None,
        "y_vs_prev_kwh": _pct(cur["kwh_per_day"], prev["kwh_per_day"]) if prev and prev["days"] >= 300 else None,
        "all": _agg(bills),
        "first": bills[0],
    }


def series(bills: list[Bill]) -> dict:
    """Per-bill series for the charts (x axis = the month of the bill)."""
    def r(v, n=2):
        return round(v, n) if v is not None else None

    return {
        "labels": [month_label(b.month) for b in bills],
        "periods": [f"{b.period_start:%d/%m/%y}–{b.period_end:%d/%m/%y}" if b.period_start else "" for b in bills],
        "ids": [b.id for b in bills],
        "kwh": [b.kwh for b in bills],
        "kwh_per_day": [b.kwh_per_day for b in bills],
        "days": [b.period_days for b in bills],
        "cost": [b.period_cost for b in bills],
        "cost_per_day": [b.cost_per_day for b in bills],
        "supply": [r(b.supply_total) for b in bills],
        "regulated": [r(b.regulated_total) for b in bills],
        "taxes": [r(b.taxes_and_fees) for b in bills],
        "all_in_rate": [r(b.all_in_rate, 4) for b in bills],
        "energy_rate": [r(b.energy_rate, 4) for b in bills],
        "supply_rate": [r(b.supply_total / b.kwh, 4) if b.supply_total is not None and b.kwh else None for b in bills],
        "regulated_rate": [r(b.regulated_total / b.kwh, 4) if b.regulated_total is not None and b.kwh else None
                           for b in bills],
        "fixed": [r(b.fixed_charge) for b in bills],
        "subsidy": [r(b.subsidy) for b in bills],
    }


def by_year(bills: list[Bill], key: str = "kwh_per_day") -> dict:
    """{year: [12 values or None]} on the calendar month of each bill, for the year-over-year chart."""
    years: dict[int, list] = {}
    for b in bills:
        m = b.month
        row = years.setdefault(m.year, [None] * 12)
        row[m.month - 1] = getattr(b, key)
    return dict(sorted(years.items()))


def composition(bills: list[Bill]) -> list[dict]:
    """Where the money of the given bills went (for the doughnut)."""
    parts = [
        ("Ενέργεια (προμηθευτής)", sum((b.energy_charge or 0) for b in bills)),
        ("Πάγιο", sum((b.fixed_charge or 0) for b in bills)),
        ("Επιδοτήσεις / εκπτώσεις", sum((b.subsidy or 0) + (b.discount or 0) for b in bills)),
        ("Δίκτυο ΑΔΜΗΕ + ΔΕΔΔΗΕ", sum((b.admie or 0) + (b.deddie or 0) for b in bills)),
        ("ΥΚΩ + ΕΤΜΕΑΡ", sum((b.yko or 0) + (b.etmear or 0) for b in bills)),
        ("Δημοτικά τέλη", sum((b.municipal or 0) for b in bills)),
        ("ΕΡΤ", sum((b.ert or 0) for b in bills)),
        ("ΕΦΚ + ειδ. τέλος", sum((b.efk or 0) + (b.special_fee or 0) for b in bills)),
        ("ΦΠΑ", sum((b.vat or 0) for b in bills)),
    ]
    total = sum(v for _, v in parts if v > 0)
    return [{"label": k, "value": round(v, 2), "pct": round(v / total * 100, 1) if total else 0}
            for k, v in parts if abs(v) >= 0.005]
