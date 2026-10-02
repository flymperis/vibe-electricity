"""The fields of one electricity bill: the single list that the parsers fill,
the validator checks, the database stores and the UI shows / edits."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    kind: str  # money | kwh | rate | date | int | text | kva
    group: str
    hint: str = ""  # one line for the LLM prompt


GROUPS = {
    "info": "Στοιχεία λογαριασμού",
    "usage": "Κατανάλωση",
    "supply": "Χρεώσεις προμήθειας",
    "regulated": "Ρυθμιζόμενες χρεώσεις",
    "misc": "Δήμος, ΕΡΤ και λοιπά",
    "totals": "Σύνολα",
}

FIELDS: list[Field] = [
    Field("supplier", "Πάροχος", "text", "info", "electricity supplier name, e.g. ΔΕΗ, Heron, Protergia"),
    Field("bill_kind", "Είδος", "text", "info", "'final' for εκκαθαριστικός (actual reading), 'estimate' for έναντι"),
    Field("tariff", "Τιμολόγιο", "text", "info", "tariff / product name, e.g. 'Γ1 Οικιακό Τιμολόγιο'"),
    Field("bill_number", "Αριθμός λογαριασμού", "text", "info", "bill serial number (Α/Α Λογαριασμού)"),
    Field("issue_date", "Ημερομηνία έκδοσης", "date", "info", "issue date"),
    Field("due_date", "Εξόφληση έως", "date", "info", "payment due date"),
    Field("period_start", "Αρχή περιόδου", "date", "usage", "start of the consumption period"),
    Field("period_end", "Τέλος περιόδου", "date", "usage", "end of the consumption period"),
    Field("days", "Ημέρες", "int", "usage", "number of days of the period"),
    Field("next_reading_date", "Επόμενη καταμέτρηση", "date", "info", "next meter reading date"),
    Field("kwh", "Κατανάλωση (kWh)", "kwh", "usage", "total consumption of the period in kWh"),
    Field("kwh_night", "Νυχτερινή κατανάλωση (kWh)", "kwh", "usage", "night/reduced-rate kWh, null if none"),
    Field("meter_current", "Ένδειξη μετρητή (τελευταία)", "int", "usage", "latest meter reading"),
    Field("meter_previous", "Ένδειξη μετρητή (προηγούμενη)", "int", "usage", "previous meter reading"),
    Field("contracted_kva", "Συμφωνημένη ισχύς (kVA)", "kva", "usage", "contracted power in kVA"),
    Field("supply_total", "Σύνολο προμήθειας", "money", "supply", "total supplier charges (Χρεώσεις προμήθειας)"),
    Field("fixed_charge", "Πάγια χρέωση", "money", "supply", "fixed/standing charge"),
    Field("energy_charge", "Χρέωση ενέργειας", "money", "supply", "energy charge (kWh x price)"),
    Field("energy_rate", "Τιμή ενέργειας (€/kWh)", "rate", "supply", "supplier energy price per kWh (weighted if tiers)"),
    Field("subsidy", "Επιδότηση", "money", "supply", "state subsidy, negative number, null if none"),
    Field("discount", "Εκπτώσεις", "money", "supply", "discounts, negative number, null if none"),
    Field("regulated_total", "Σύνολο ρυθμιζόμενων", "money", "regulated", "total regulated charges (Ρυθμιζόμενες χρεώσεις)"),
    Field("admie", "ΑΔΜΗΕ (μεταφορά)", "money", "regulated", "ΑΔΜΗΕ transmission charge"),
    Field("deddie", "ΔΕΔΔΗΕ (διανομή)", "money", "regulated", "ΔΕΔΔΗΕ distribution charge"),
    Field("yko", "ΥΚΩ", "money", "regulated", "ΥΚΩ public service charge"),
    Field("etmear", "ΕΤΜΕΑΡ", "money", "regulated", "ΕΤΜΕΑΡ renewables levy"),
    Field("misc_total", "Σύνολο Δήμος/ΕΡΤ/διάφορα", "money", "misc", "total of Διάφορα - Δήμος - ΕΡΤ"),
    Field("municipal", "Δημοτικά τέλη (ΔΤ+ΔΦ+ΤΑΠ)", "money", "misc", "municipal fees total"),
    Field("ert", "ΕΡΤ", "money", "misc", "ΕΡΤ TV fee"),
    Field("efk", "ΕΦΚ", "money", "misc", "special consumption tax ΕΦΚ"),
    Field("special_fee", "Ειδ. τέλος 5‰", "money", "misc", "ΕΙΔ.ΤΕΛ. 5ο/οο"),
    Field("rounding_current", "Στρογγυλοποίηση τρέχοντος", "money", "misc", "rounding added to this bill"),
    Field("rounding_previous", "Στρογγυλοποίηση προηγούμενου", "money", "misc", "rounding carried from previous bill (usually negative)"),
    Field("vat", "ΦΠΑ", "money", "totals", "VAT amount"),
    Field("previous_unpaid", "Προηγούμενο ανεξόφλητο", "money", "totals", "previous unpaid amount, null if none"),
    Field("total_payable", "Σύνολο πληρωμής", "money", "totals", "total amount to pay"),
]
FIELD_BY_NAME = {f.name: f for f in FIELDS}
MONEY_FIELDS = [f.name for f in FIELDS if f.kind == "money"]


@dataclass
class BillData:
    supplier: str | None = None
    bill_kind: str | None = None
    tariff: str | None = None
    bill_number: str | None = None
    issue_date: date | None = None
    due_date: date | None = None
    period_start: date | None = None
    period_end: date | None = None
    days: int | None = None
    next_reading_date: date | None = None
    kwh: float | None = None
    kwh_night: float | None = None
    meter_current: int | None = None
    meter_previous: int | None = None
    contracted_kva: float | None = None
    supply_total: float | None = None
    fixed_charge: float | None = None
    energy_charge: float | None = None
    energy_rate: float | None = None
    subsidy: float | None = None
    discount: float | None = None
    regulated_total: float | None = None
    admie: float | None = None
    deddie: float | None = None
    yko: float | None = None
    etmear: float | None = None
    misc_total: float | None = None
    municipal: float | None = None
    ert: float | None = None
    efk: float | None = None
    special_fee: float | None = None
    rounding_current: float | None = None
    rounding_previous: float | None = None
    vat: float | None = None
    previous_unpaid: float | None = None
    total_payable: float | None = None
    # not a stored column: energy tiers as [kwh, €/kWh] pairs, for validation
    energy_tiers: list[tuple[float, float]] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = asdict(self)
        d.pop("energy_tiers", None)
        return d

    def missing(self, names: list[str]) -> list[str]:
        return [n for n in names if getattr(self, n) is None]


# Without these a bill is not usable for history/charts.
REQUIRED = ["period_start", "period_end", "kwh", "total_payable"]
