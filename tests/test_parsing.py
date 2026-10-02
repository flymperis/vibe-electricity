from datetime import date

import pytest

from conftest import fixture_text
from vibe_electricity.parsing import dei, validate
from vibe_electricity.parsing.extract import extract, looks_like_electricity_bill
from vibe_electricity.parsing.numbers import to_float
from vibe_electricity.parsing.schema import BillData


@pytest.mark.parametrize("raw,expected", [
    ("1 2 , 94", 12.94), ("9 1 , 00", 91.0), ("3 ,06", 3.06), ("0, 77", 0.77), ("- 2 , 79", -2.79),
    ("-0 , 38", -0.38), ("1.850,00", 1850.0), ("0,12905", 0.12905), ("*63,00€", 63.0), ("abc", None),
])
def test_to_float(raw, expected):
    assert to_float(raw) == expected


def test_flat_rate_bill():
    b = dei.parse(fixture_text("dei_flat"))
    assert b.supplier == "ΔΕΗ" and b.bill_kind == "final" and b.tariff == "Γ1 Οικιακό Τιμολόγιο"
    assert b.bill_number == "1000000061"
    assert (b.period_start, b.period_end, b.days) == (date(2025, 9, 30), date(2025, 10, 30), 31)
    assert (b.issue_date, b.due_date, b.next_reading_date) == (date(2025, 11, 4), date(2025, 11, 25), date(2025, 11, 28))
    assert b.kwh == 234 and b.meter_current - b.meter_previous == 234
    assert (b.supply_total, b.fixed_charge, b.energy_charge) == (35.37, 5.17, 30.20)
    assert b.energy_rate == pytest.approx(0.12905)
    assert (b.regulated_total, b.admie, b.deddie, b.yko, b.etmear) == (12.94, 2.34, 5.01, 1.61, 3.98)
    assert (b.misc_total, b.municipal, b.ert, b.efk, b.special_fee) == (11.76, 7.93, 3.06, 0.51, 0.22)
    assert (b.rounding_current, b.rounding_previous) == (0.42, -0.38)
    assert (b.vat, b.total_payable, b.contracted_kva) == (2.93, 63.0, 8.0)
    assert b.subsidy is None and b.previous_unpaid is None
    checks = validate.checks(b)
    assert all(c.ok for c in checks), [c.message for c in checks if not c.ok]
    assert validate.status(checks) == "ok"


def test_tiered_bill_with_state_subsidy():
    b = dei.parse(fixture_text("dei_tiered_subsidy"))
    assert b.energy_tiers == [(184.0, 0.1594), (13.0, 0.16391)]
    assert b.energy_charge == 31.46 and b.subsidy == -2.79
    assert b.supply_total == 33.84 and b.total_payable == 58.0
    assert validate.status(validate.checks(b)) == "ok"


def test_total_with_space_after_star():
    b = dei.parse(fixture_text("dei_star_total"))
    assert b.total_payable == 101.0 and b.kwh == 387
    assert validate.status(validate.checks(b)) == "ok"


def test_validation_catches_a_wrong_amount():
    b = dei.parse(fixture_text("dei_flat"))
    b.vat = 3.93
    checks = {c.name: c for c in validate.checks(b)}
    assert not checks["total"].ok
    assert validate.status(list(checks.values())) == "warn"
    b.kwh = None
    assert validate.status(validate.checks(b)) == "fail"


def test_water_bill_is_not_electricity():
    assert not looks_like_electricity_bill("ΛΟΓΑΡΙΑΣΜΟΣ ΥΔΡΕΥΣΗΣ ΚΑΙ ΑΠΟΧΕΤΕΥΣΗΣ\nκατανάλωση 7 m3\nΣΥΝΟΛΟ 23,40")
    assert looks_like_electricity_bill(fixture_text("dei_flat"))


def test_known_layout_does_not_call_the_llm():
    called = []
    e = extract(fixture_text("dei_flat"), llm=lambda t: called.append(1) or BillData())
    assert e.method == "rules" and e.status == "ok" and not called


def test_unknown_supplier_uses_llm():
    data = BillData(supplier="Άλλος πάροχος", period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
                    kwh=200, total_payable=50.0, supply_total=30.0, regulated_total=10.0, misc_total=7.0, vat=3.0)
    e = extract("Λογαριασμός ρεύματος 200 kWh ΔΕΔΔΗΕ", llm=lambda t: data)
    assert e.method == "llm" and e.status == "ok" and e.data.kwh == 200


def test_llm_fills_gaps_of_the_rules():
    text = fixture_text("dei_flat").replace("Συνολικό ποσό πληρωμής", "Σύνολο")
    e = extract(text, llm=lambda t: BillData(total_payable=63.0))
    assert e.method == "rules+llm" and e.status == "ok" and e.data.total_payable == 63.0


def test_llm_failure_is_reported_not_raised():
    def broken(_):
        raise ConnectionError("ollama down")
    e = extract("ρεύμα 100 kWh ΔΕΔΔΗΕ", llm=broken)
    assert e.status == "fail" and "ollama down" in e.errors[0]
