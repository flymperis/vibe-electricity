"""Cross-checks between the fields of a bill: do the parts add up to the totals?

A bill whose sums agree was almost certainly read correctly, whichever reader
(rules or LLM) produced it; a failed check points at the exact field to fix.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .schema import REQUIRED, BillData

TOL = 0.03  # € (amounts are rounded per line)


@dataclass
class Check:
    name: str
    ok: bool
    message: str

    def as_dict(self) -> dict:
        return asdict(self)


def _sum(*values: float | None) -> float:
    return round(sum(v or 0.0 for v in values), 2)


def _money_check(name: str, label: str, total: float | None, parts: list[float | None]) -> Check | None:
    if total is None or all(p is None for p in parts):
        return None
    s = _sum(*parts)
    ok = abs(s - total) <= TOL
    return Check(name, ok, f"{label}: {s:.2f} € {'=' if ok else '≠'} {total:.2f} €")


def checks(b: BillData) -> list[Check]:
    out: list[Check] = []
    missing = b.missing(REQUIRED)
    out.append(Check("required", not missing,
                     "Υπάρχουν όλα τα βασικά πεδία" if not missing else "Λείπουν: " + ", ".join(missing)))

    c = _money_check("total", "Προμήθεια + ρυθμιζόμενες + διάφορα + ΦΠΑ (+ ανεξόφλητο)", b.total_payable,
                     [b.supply_total, b.regulated_total, b.misc_total, b.vat, b.previous_unpaid])
    if c and None in (b.supply_total, b.regulated_total, b.misc_total, b.vat):
        c = Check(c.name, False, c.message + " (λείπουν μερικά σύνολα)")
    if c:
        out.append(c)

    for c in (
        _money_check("supply", "Πάγιο + ενέργεια + επιδότηση/εκπτώσεις", b.supply_total,
                     [b.fixed_charge, b.energy_charge, b.subsidy, b.discount]),
        _money_check("regulated", "ΑΔΜΗΕ + ΔΕΔΔΗΕ + ΥΚΩ + ΕΤΜΕΑΡ", b.regulated_total,
                     [b.admie, b.deddie, b.yko, b.etmear]),
        _money_check("misc", "Δήμος + ΕΡΤ + ΕΦΚ + ειδ. τέλος + στρογγυλοποιήσεις", b.misc_total,
                     [b.municipal, b.ert, b.efk, b.special_fee, b.rounding_current, b.rounding_previous]),
    ):
        if c:
            out.append(c)

    if b.kwh is not None and b.meter_current is not None and b.meter_previous is not None:
        diff = b.meter_current - b.meter_previous
        ok = diff == round(b.kwh) or diff < 0  # meter replaced / rolled over: cannot check
        out.append(Check("meter", ok, f"Διαφορά ενδείξεων {diff} kWh {'=' if ok else '≠'} κατανάλωση {b.kwh:g} kWh"))

    if b.energy_tiers and b.kwh is not None:
        tier_kwh = sum(k for k, _ in b.energy_tiers)
        ok = abs(tier_kwh - b.kwh) < 0.5
        out.append(Check("tiers_kwh", ok, f"kWh κλιμακίων {tier_kwh:g} {'=' if ok else '≠'} {b.kwh:g}"))
        if b.energy_charge is not None:
            est = round(sum(k * r for k, r in b.energy_tiers), 2)
            ok = abs(est - b.energy_charge) <= 0.05 + 0.002 * b.energy_charge
            out.append(Check("tiers_amount", ok,
                             f"kWh × τιμή = {est:.2f} € {'≈' if ok else '≠'} χρέωση ενέργειας {b.energy_charge:.2f} €"))

    if b.period_start and b.period_end and b.days:
        span = (b.period_end - b.period_start).days
        ok = b.days in (span, span + 1)
        out.append(Check("days", ok, f"Ημέρες {b.days} {'σωστές' if ok else 'δεν ταιριάζουν'} με την περίοδο ({span + 1})"))

    if b.period_start and b.period_end and b.period_end < b.period_start:
        out.append(Check("period", False, "Η περίοδος τελειώνει πριν αρχίσει"))
    return out


def status(results: list[Check]) -> str:
    """ok = everything adds up; warn = usable but a secondary check failed; fail = unusable."""
    by = {c.name: c for c in results}
    if not by["required"].ok:
        return "fail"
    if all(c.ok for c in results):
        return "ok"
    if "total" in by and not by["total"].ok:
        return "warn"
    return "warn"
