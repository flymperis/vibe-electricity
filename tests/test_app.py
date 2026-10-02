import json

import pytest
from fastapi.testclient import TestClient

from conftest import FakePaperless, fixture_text
from vibe_electricity import jobs
from vibe_electricity.db import session_scope
from vibe_electricity.models import Bill, Document

DOCS = {
    10: ("Bill a", fixture_text("dei_flat"), "sum-a"),
    11: ("Bill a again", fixture_text("dei_flat"), "sum-a"),  # same file twice
    12: ("Bill b", fixture_text("dei_tiered_subsidy"), "sum-b"),
    13: ("Bill c", fixture_text("dei_star_total"), "sum-c"),
    14: ("Water", "ΛΟΓΑΡΙΑΣΜΟΣ ΥΔΡΕΥΣΗΣ 7 m3 ΣΥΝΟΛΟ 23,40", "sum-w"),
}


@pytest.fixture
def fake(monkeypatch, db):
    pl = FakePaperless(dict(DOCS))
    monkeypatch.setattr(jobs, "Paperless", lambda: pl)
    return pl


@pytest.fixture
def client(fake):
    from vibe_electricity.main import app

    with TestClient(app) as c:
        yield c


def test_sync_reads_bills_and_handles_duplicates_and_non_bills(fake):
    counts = jobs.run_sync()
    assert counts == {"parsed": 3, "duplicate": 1, "skipped": 1}
    with session_scope() as s:
        assert s.query(Bill).count() == 3
        assert {b.status for b in s.query(Bill)} == {"ok"}
        dup = s.get(Document, 11)
        assert dup.status == "duplicate" and dup.bill_id == s.get(Document, 10).bill_id
    assert jobs.run_sync() == {"parsed": 3, "duplicate": 1, "skipped": 1}  # unchanged documents are not re-read


def test_document_that_loses_the_tag(fake):
    jobs.run_sync()
    del fake.docs[13]
    jobs.run_sync()
    with session_scope() as s:
        assert s.get(Document, 13).status == "untagged"


def test_manual_correction_survives_reread(client):
    jobs.run_sync()
    with session_scope() as s:
        bill_id = s.query(Bill).filter(Bill.bill_number == "1000000061").one().id
    r = client.post(f"/bills/{bill_id}/edit", data={"vat": "3,93", "kwh": "234"}, follow_redirects=False)
    assert r.status_code == 303
    with session_scope() as s:
        b = s.get(Bill, bill_id)
        assert b.vat == 3.93 and json.loads(b.overrides_json) == {"vat": 3.93} and b.status == "warn"
    jobs.process_one(10)
    with session_scope() as s:
        assert s.get(Bill, bill_id).vat == 3.93
    client.post(f"/bills/{bill_id}/clear-overrides")
    with session_scope() as s:
        b = s.get(Bill, bill_id)
        assert b.vat == 2.93 and b.status == "ok"


def test_pages_render(client):
    for path in ("/", "/bills", "/analysis", "/settings"):  # empty database
        assert client.get(path).status_code == 200
    jobs.run_sync()
    with session_scope() as s:
        ids = [b.id for b in s.query(Bill)]
    for path in ["/", "/bills", "/bills?year=2025", "/analysis", "/settings", "/api/bills", "/export.csv", "/healthz"] + \
            [f"/bills/{i}" for i in ids] + [f"/bills/{ids[0]}?edit=1"]:
        r = client.get(path)
        assert r.status_code == 200, path
    assert "63,00 €" in client.get(f"/bills/{ids[0]}").text
    assert client.get("/bills/9999").status_code == 404


def test_webhook_processes_the_document(client):
    r = client.post("/api/webhook", json={"document_id": 12, "tags": ["Electricity"]})
    assert r.status_code == 200 and r.json() == {"queued": 12}
    with session_scope() as s:
        assert s.get(Document, 12).status == "parsed"
    assert client.post("/api/webhook", json={"doc_url": "http://p/api/documents/13/"}).json() == {"queued": 13}
    assert client.post("/api/webhook", json={"nothing": 1}).status_code == 422


def test_webhook_secret(client, monkeypatch):
    from vibe_electricity.config import get_settings

    monkeypatch.setattr(get_settings(), "webhook_secret", "s3cret")
    assert client.post("/api/webhook", json={"document_id": 12}).status_code == 401
    assert client.post("/api/webhook", json={"document_id": 12}, headers={"X-Webhook-Secret": "s3cret"}).status_code == 200


def test_delete_bill(client):
    jobs.run_sync()
    with session_scope() as s:
        bill_id = s.query(Bill).first().id
    assert client.post(f"/bills/{bill_id}/delete", follow_redirects=False).status_code == 303
    with session_scope() as s:
        assert s.get(Bill, bill_id) is None


def test_settings_save(client):
    r = client.post("/settings", data={"paperless_tag": "Ρεύμα", "ollama_url": "", "ollama_model": "m",
                                       "sync_interval_minutes": "1"}, follow_redirects=False)
    assert r.status_code == 303
    from vibe_electricity import runtime_settings

    with session_scope() as s:
        rt = runtime_settings.load(s)
    assert rt.paperless_tag == "Ρεύμα" and rt.sync_interval_minutes == 5 and rt.llm_enabled is False
