"""Reading bills from Paperless: one document (webhook / button) or a full sync
(scheduled poll). Processing is serialised by one lock, so a webhook arriving
during a sync simply waits its turn."""

from __future__ import annotations

import json
import logging
import threading

from sqlalchemy.orm import Session

from . import runtime_settings
from .db import session_scope
from .models import Bill, Document, Event, utcnow
from .paperless import Paperless, PaperlessError
from .parsing import llm, validate
from .parsing.extract import extract, looks_like_electricity_bill
from .parsing.schema import FIELD_BY_NAME, FIELDS, BillData

log = logging.getLogger("vibe_electricity.jobs")

_lock = threading.Lock()
state = {"running": False, "last_sync": None, "last_result": None, "last_error": None}


def event(s: Session, message: str, level: str = "info", paperless_id: int | None = None) -> None:
    s.add(Event(message=message[:1000], level=level, paperless_id=paperless_id))
    getattr(log, "warning" if level == "warn" else level)(message)


def _llm_reader(s: Session):
    rt = runtime_settings.load(s)
    if not rt.llm_enabled or not rt.ollama_url:
        return None
    return lambda text: llm.extract(text, rt.ollama_url, rt.ollama_model)


def bill_data(bill: Bill) -> BillData:
    data = BillData(**{f.name: getattr(bill, f.name) for f in FIELDS})
    data.energy_tiers = [tuple(t) for t in bill.tiers]
    return data


def revalidate(bill: Bill) -> None:
    checks = validate.checks(bill_data(bill))
    bill.checks_json = json.dumps([c.as_dict() for c in checks], ensure_ascii=False)
    bill.status = validate.status(checks)


def _coerce_override(name: str, value):
    from .parsing.numbers import to_date

    kind = FIELD_BY_NAME[name].kind
    if value in (None, ""):
        return None
    if kind == "date":
        from datetime import date

        return date.fromisoformat(value) if "-" in str(value) else to_date(str(value))
    if kind == "int":
        return int(float(value))
    if kind in ("money", "kwh", "rate", "kva"):
        return float(str(value).replace(",", "."))
    return str(value)


def apply_overrides(bill: Bill) -> None:
    for name, value in bill.overrides.items():
        if name in FIELD_BY_NAME:
            setattr(bill, name, _coerce_override(name, value))


def _find_bill(s: Session, data: BillData) -> Bill | None:
    q = s.query(Bill)
    if data.bill_number:
        return q.filter(Bill.bill_number == data.bill_number).first()
    if data.period_start and data.period_end:
        return q.filter(Bill.period_start == data.period_start, Bill.period_end == data.period_end,
                        Bill.supplier == data.supplier).first()
    return None


def process_document(s: Session, pl: Paperless, paperless_id: int, *, force: bool = False,
                     known_modified: str | None = None) -> str:
    """Read one Paperless document into a bill. Returns the document status."""
    doc = s.get(Document, paperless_id) or Document(paperless_id=paperless_id)
    if (not force and doc.status in ("parsed", "duplicate", "skipped") and known_modified
            and doc.modified == known_modified):
        return doc.status
    s.add(doc)

    remote = pl.document(paperless_id)
    doc.title = remote.get("title")
    doc.modified = remote.get("modified")
    doc.checksum = pl.checksum(paperless_id)
    doc.processed_at = utcnow()
    text = remote.get("content") or ""

    # same file uploaded twice: link it to the bill of the first copy
    twin = (s.query(Document).filter(Document.checksum == doc.checksum, Document.paperless_id != paperless_id,
                                     Document.bill_id.isnot(None)).order_by(Document.paperless_id).first()
            if doc.checksum else None)
    if twin and twin.paperless_id < paperless_id:
        doc.status, doc.bill_id = "duplicate", twin.bill_id
        doc.message = f"Ίδιο αρχείο με το έγγραφο #{twin.paperless_id}"
        return doc.status

    if not looks_like_electricity_bill(text):
        doc.status, doc.bill_id = "skipped", None
        doc.message = "Δεν μοιάζει με λογαριασμό ρεύματος (δεν υπάρχουν kWh / χρεώσεις δικτύου)"
        event(s, f"Έγγραφο #{paperless_id} «{doc.title}»: {doc.message}", "warn", paperless_id)
        return doc.status

    result = extract(text, _llm_reader(s))
    if result.status == "fail":
        doc.status = "error"
        failed = [c.message for c in result.checks if not c.ok] + result.errors
        doc.message = "; ".join(failed)[:900]
        event(s, f"Έγγραφο #{paperless_id}: δεν διαβάστηκε ({doc.message})", "error", paperless_id)
        return doc.status

    bill = _find_bill(s, result.data)
    if bill is not None and bill.paperless_id not in (None, paperless_id):
        primary = s.get(Document, bill.paperless_id)
        if primary is not None and primary.status == "parsed":
            doc.status, doc.bill_id = "duplicate", bill.id
            doc.message = f"Ίδιος λογαριασμός με το έγγραφο #{bill.paperless_id}"
            return doc.status
    if bill is None:
        bill = Bill()
        s.add(bill)

    bill.paperless_id = paperless_id
    for f in FIELDS:
        setattr(bill, f.name, getattr(result.data, f.name))
    bill.tiers_json = json.dumps(result.data.energy_tiers)
    bill.method = result.method
    apply_overrides(bill)
    revalidate(bill)
    s.flush()

    doc.status, doc.bill_id = "parsed", bill.id
    doc.message = None if bill.status == "ok" else "Κάποιοι έλεγχοι δεν ταιριάζουν, δες τον λογαριασμό"
    event(s, f"Έγγραφο #{paperless_id}: λογαριασμός {bill.bill_number or ''} "
             f"{bill.period_start}–{bill.period_end}, {bill.kwh:g} kWh, {bill.total_payable} € "
             f"({result.method}, {bill.status})", "info" if bill.status == "ok" else "warn", paperless_id)
    return doc.status


def process_one(paperless_id: int, force: bool = True) -> str:
    with _lock, session_scope() as s, Paperless() as pl:
        try:
            return process_document(s, pl, paperless_id, force=force)
        except PaperlessError as exc:
            event(s, f"Έγγραφο #{paperless_id}: {exc}", "error", paperless_id)
            return "error"


def run_sync(force: bool = False) -> dict:
    """Read every document that carries the electricity tag and is new or changed."""
    state["running"] = True
    if not _lock.acquire(timeout=900):  # a webhook being processed: wait for it
        state["running"] = False
        return {"skipped": "busy"}
    counts: dict[str, int] = {}
    try:
        with session_scope() as s, Paperless() as pl:
            tag = runtime_settings.load(s).paperless_tag
            tag_id = pl.tag_id(tag)
            if tag_id is None:
                raise PaperlessError(f"Δεν υπάρχει tag «{tag}» στο Paperless")
            remote = pl.tagged_documents(tag_id)
            for d in remote:
                try:
                    st = process_document(s, pl, d["id"], force=force, known_modified=d.get("modified"))
                except PaperlessError as exc:
                    event(s, f"Έγγραφο #{d['id']}: {exc}", "error", d["id"])
                    st = "error"
                counts[st] = counts.get(st, 0) + 1
                s.commit()
            # documents that lost the tag are no longer bills
            remote_ids = {d["id"] for d in remote}
            for doc in s.query(Document).filter(Document.status != "untagged").all():
                if doc.paperless_id not in remote_ids:
                    doc.status, doc.message = "untagged", f"Δεν έχει πια το tag «{tag}»"
        state["last_error"] = None
    except Exception as exc:  # noqa: BLE001
        log.exception("sync failed")
        state["last_error"] = str(exc)[:300]
        with session_scope() as s:
            event(s, f"Συγχρονισμός απέτυχε: {exc}", "error")
    finally:
        state["running"] = False
        state["last_sync"] = utcnow()
        state["last_result"] = counts
        _lock.release()
    return counts
