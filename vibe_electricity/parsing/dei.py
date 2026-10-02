"""Rule-based parser for ΔΕΗ (DEI / PPC) household bills, from the OCR text that
Paperless stores for the PDF (`content`).

The PDFs downloaded from myΔΕΗ are digital, so the text is reliable, but the
two-column layout interleaves lines from both columns and splits digits with
spaces. Every pattern is therefore anchored on a label and reads the amount on
the same line; the page-1 summary box amounts always end in '€'.
"""

from __future__ import annotations

import re

from .numbers import AMOUNT, DATE, RATE, amount_after, first, to_date, to_float
from .schema import BillData


def is_dei(text: str) -> bool:
    return bool(re.search(r"ΔΕΗ A\.?E\.|dei\.gr|Χρεώσεις [Ππ]ρομήθειας ΔΕΗ", text))


def _int(s: str | None) -> int | None:
    return int(s) if s and s.isdigit() else None


def _kwh(s: str | None) -> float | None:
    if not s:
        return None
    return to_float(s.replace(".", "")) if "," in s else float(s.replace(".", ""))


_ENERGY_LINE = re.compile(rf"Χρέωση Ενέργειας[ ]+([^\d\n]*?)[ ]*({AMOUNT})(?![\d,])")
_TIER = re.compile(rf"(\d+(?:,\d+)?)\s*kWh\s*x\s*({RATE})\s*€/kWh")
_SECTION_END = re.compile(r"Ρυθμιζόμενες Χρεώσεις|ΑΔΜΗΕ:|Ενδείξεις Μετρητή|Χρέωση Ενέργειας")
_METER_ROW = re.compile(r"^(\d{6,})[ ]+(\d{1,3})[ ]+(\d+)[ ]+(\d+)[ ]+(\d+)[ ]+(\d+)[ ]+(\d+)[ ]*$", re.M)


def _energy(text: str, bill: BillData) -> None:
    charge = 0.0
    found = False
    night_kwh = 0.0
    for m in _ENERGY_LINE.finditer(text):
        label = m.group(1).strip()
        amount = to_float(m.group(2))
        if amount is None:
            continue
        found = True
        charge += amount
        # the "(kWh x €/kWh)" breakdown sits on the next line or two, before the next section
        rest = text[m.end(): m.end() + 400]
        stop = _SECTION_END.search(rest)
        seg = rest[: stop.start()] if stop else rest
        tiers = [(_kwh(k) or 0.0, to_float(r) or 0.0) for k, r in _TIER.findall(seg)]
        bill.energy_tiers.extend(tiers)
        if re.search(r"Νύχτας|Μειωμένη|Νυχτ", label):
            night_kwh += sum(k for k, _ in tiers)
    if found:
        bill.energy_charge = round(charge, 2)
    if night_kwh:
        bill.kwh_night = night_kwh
    kwh_sum = sum(k for k, _ in bill.energy_tiers)
    if kwh_sum:
        bill.energy_rate = round(sum(k * r for k, r in bill.energy_tiers) / kwh_sum, 5)


def _meters(text: str, bill: BillData) -> None:
    rows = _METER_ROW.findall(text)
    if not rows:
        return
    # columns: meter no, reading type, latest, previous, difference, added kWh, total
    bill.meter_current = int(rows[0][2])
    bill.meter_previous = int(rows[0][3])
    if bill.kwh is None:
        bill.kwh = float(sum(int(r[6]) for r in rows))


def parse(text: str) -> BillData:
    b = BillData(supplier="ΔΕΗ")

    if "Εκκαθαριστικός" in text:
        b.bill_kind = "final"
    elif re.search(r"Έναντι\s+λογαριασμός|ΕΝΑΝΤΙ\s+ΛΟΓΑΡΙΑΣΜΟΣ", text):
        b.bill_kind = "estimate"

    tariff = first(r"Τιμολόγιο:[ ]*(.+?)(?:[ ]+ΕΞΟΦΛΗΣΗ|\n)", text)
    b.tariff = tariff.strip() if tariff else None
    b.bill_number = first(r"Α/Α Λογαριασμού[ ]+(\d{6,})", text)
    b.issue_date = to_date(first(rf"Ημ/νία Έκδοσης[ ]+({DATE})", text))
    b.due_date = to_date(first(rf"ΕΞΟΦΛΗΣΗ ΕΩΣ[\s\S]{{0,160}}?({DATE})", text))
    b.next_reading_date = to_date(first(rf"Επόμενη καταμέτρηση:[ ]*({DATE})", text))

    period = re.search(rf"Περίοδος Κατανάλωσης[ ]+({DATE})[ ]*-[ ]*({DATE})", text)
    if period:
        b.period_start, b.period_end = to_date(period.group(1)), to_date(period.group(2))
    b.days = _int(first(r"Ημέρες[ ]+(\d{1,3})\b", text))
    b.kwh = _kwh(first(r"Κατανάλωση Ηλεκτρικής Ενέργειας[ ]+([\d.,]+)[ ]*kWh", text))
    kva = first(r"\((\d+(?:,\d+)?)[ ]?kVA[ ]?x", text)
    b.contracted_kva = to_float(kva) if kva and "," in kva else (float(kva) if kva else None)

    # page 1 summary box (amounts end in €)
    b.supply_total = amount_after(r"Χρεώσεις [Ππ]ρομήθειας[^\d\n€]*?", text, euro=True)
    b.regulated_total = amount_after(r"Ρυθμιζόμενες [Χχ]ρεώσεις", text, euro=True)
    b.misc_total = amount_after(r"Διάφορα - Δήμος - ΕΡΤ", text, euro=True)
    b.vat = amount_after(r"ΦΠΑ", text, euro=True)
    b.previous_unpaid = amount_after(r"Προηγούμενο Ανεξόφλητο Ποσό", text, euro=True)
    b.total_payable = amount_after(r"Συνολικό ποσό πληρωμής", text, euro=True)

    # page 2 analysis
    b.fixed_charge = amount_after(r"Πάγια Χρέωση", text)
    _energy(text, b)
    b.subsidy = amount_after(r"Επιδότηση Κράτους", text)
    discounts = [to_float(a) for a in re.findall(rf"Έκπτωση[^\d\n]*?[ ]({AMOUNT})(?![\d,])", text)]
    discounts = [d for d in discounts if d is not None]
    if discounts:
        b.discount = round(-sum(abs(d) for d in discounts), 2)

    b.admie = amount_after(r"ΑΔΜΗΕ:[^\d\n]*?", text)
    b.deddie = amount_after(r"ΔΕΔΔΗΕ:[^\d\n]*?", text)
    b.yko = amount_after(r"ΥΚΩ:[^\d\n]*?", text)
    b.etmear = amount_after(r"ΕΤΜΕΑΡ", text)

    b.municipal = amount_after(r"Δήμος (?!- )[^\d\n]*?", text)
    if b.municipal is None:
        b.municipal = amount_after(r"ΔΗΜΟΣ\.*", text)
    b.ert = amount_after(r"ΕΡΤ[ .]*:", text)
    if b.ert is None:
        b.ert = amount_after(r"\nΕΡΤ", text)
    b.efk = amount_after(r"ΕΦΚ \(Ν\.3336/05\)", text)
    b.special_fee = amount_after(r"ΕΙΔ\.ΤΕΛ\. 5ο/οο Ν\.2093/92", text)
    b.rounding_current = amount_after(r"Στρογγ/ση Πληρ\.Ποσού", text)
    b.rounding_previous = amount_after(r"Ποσό Στρογγ\.Προηγ\.Λογ\.", text)

    _meters(text, b)
    if b.energy_rate is None and b.energy_charge and b.kwh:
        b.energy_rate = round(b.energy_charge / b.kwh, 5)
    return b
