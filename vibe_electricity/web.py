from __future__ import annotations

import csv
import io
import json
import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from . import jobs, runtime_settings, stats
from .config import get_settings
from .db import get_session
from .models import Bill, Document, Event
from .paperless import Paperless, PaperlessError, document_link
from .parsing import llm
from .parsing.schema import FIELD_BY_NAME, FIELDS, GROUPS

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(HERE / "templates"))
router = APIRouter()


# ---------------------------------------------------------------- formatting
def _num(v, decimals=2) -> str:
    if v is None:
        return "—"
    s = f"{v:,.{decimals}f}"
    return s.replace(",", " ").replace(".", ",")


def eur(v, decimals=2) -> str:
    return "—" if v is None else f"{_num(v, decimals)} €"


def kwh(v) -> str:
    return "—" if v is None else f"{_num(v, 0 if float(v).is_integer() else 1)} kWh"


def rate(v) -> str:
    return "—" if v is None else f"{_num(v, 4)} €/kWh"


def dt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, datetime):
        try:
            v = v.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(get_settings().timezone))
        except Exception:  # noqa: BLE001  (unknown zone name: show UTC)
            pass
        return v.strftime("%d/%m/%Y %H:%M")
    return v.strftime("%d/%m/%Y")


def pct(v) -> str:
    return "" if v is None else f"{'+' if v > 0 else ''}{_num(v, 1)}%"


def field_value(name: str, value) -> str:
    kind = FIELD_BY_NAME[name].kind
    if value is None:
        return "—"
    if kind == "money":
        return eur(value)
    if kind == "kwh":
        return kwh(value)
    if kind == "rate":
        return rate(value)
    if kind == "date":
        return dt(value)
    if kind == "kva":
        return f"{_num(value, 0 if float(value).is_integer() else 1)} kVA"
    if name == "bill_kind":
        return {"final": "Εκκαθαριστικός", "estimate": "Έναντι"}.get(value, value)
    return str(value)


def _static_v(name: str) -> str:
    try:
        return str(int((HERE / "static" / name).stat().st_mtime))
    except OSError:
        return "0"


templates.env.filters.update(eur=eur, kwh=kwh, rate=rate, dt=dt, pct=pct, num=_num)
templates.env.globals.update(
    static_v=_static_v, field_value=field_value, month_label=stats.month_label, doc_link=document_link,
    FIELDS=FIELDS, GROUPS=GROUPS,
)


def render(request: Request, name: str, **ctx) -> HTMLResponse:
    ctx.setdefault("running", jobs.state["running"])
    return templates.TemplateResponse(request, name, ctx)


def mount_static(app) -> None:
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")


# ---------------------------------------------------------------- pages
@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, s: Session = Depends(get_session)):
    bills = stats.usable_bills(s)
    summ = stats.summary(bills)
    recent = list(reversed(bills[-13:]))
    pending = s.query(Document).filter(Document.status == "error").count()
    warn = s.query(Bill).filter(Bill.status == "warn").count()
    comp = stats.composition(stats._window(bills, bills[-1].month, 12)) if bills else []
    return render(request, "dashboard.html", bills=bills, s=summ, recent=recent, series=stats.series(bills[-24:]),
                  composition=comp, errors=pending, warn=warn,
                  tag=runtime_settings.load(s).paperless_tag)


@router.get("/bills", response_class=HTMLResponse)
def bills_page(request: Request, year: int | None = None, s: Session = Depends(get_session)):
    bills = list(reversed(stats.usable_bills(s)))
    years = sorted({b.month.year for b in bills}, reverse=True)
    shown = [b for b in bills if year is None or b.month.year == year]
    failed = s.query(Document).filter(Document.status == "error").order_by(Document.paperless_id.desc()).all()
    return render(request, "bills.html", bills=shown, years=years, year=year, failed=failed,
                  totals=stats._agg(shown) if shown else None)


@router.get("/bills/{bill_id}", response_class=HTMLResponse)
def bill_page(request: Request, bill_id: int, edit: bool = False, s: Session = Depends(get_session)):
    bill = s.get(Bill, bill_id)
    if bill is None:
        raise HTTPException(404)
    docs = s.query(Document).filter(Document.bill_id == bill_id).order_by(Document.paperless_id).all()
    bills = stats.usable_bills(s)
    idx = next((i for i, b in enumerate(bills) if b.id == bill_id), None)
    prev_bill = bills[idx - 1] if idx else None
    next_bill = bills[idx + 1] if idx is not None and idx + 1 < len(bills) else None
    return render(request, "bill.html", b=bill, docs=docs, edit=edit, prev_bill=prev_bill, next_bill=next_bill,
                  msg=request.query_params.get("msg"))


@router.post("/bills/{bill_id}/edit")
async def bill_edit(request: Request, bill_id: int, s: Session = Depends(get_session)):
    bill = s.get(Bill, bill_id)
    if bill is None:
        raise HTTPException(404)
    form = await request.form()
    overrides = bill.overrides
    for f in FIELDS:
        if f.name not in form:
            continue
        raw = str(form[f.name]).strip()
        current = getattr(bill, f.name)
        current_txt = "" if current is None else (current.isoformat() if isinstance(current, date) else str(current))
        if f.kind in ("money", "kwh", "rate", "kva", "int"):
            raw = raw.replace(",", ".")
        try:
            new = jobs._coerce_override(f.name, raw)
        except ValueError:
            return RedirectResponse(f"/bills/{bill_id}?edit=1&msg=Μη έγκυρη τιμή στο «{f.label}»", 303)
        if (new.isoformat() if isinstance(new, date) else ("" if new is None else str(new))) == current_txt:
            continue
        if isinstance(current, float) and isinstance(new, float) and abs(current - new) < 1e-9:
            continue
        overrides[f.name] = new.isoformat() if isinstance(new, date) else new
        setattr(bill, f.name, new)
    bill.overrides_json = json.dumps(overrides, ensure_ascii=False)
    jobs.revalidate(bill)
    jobs.event(s, f"Λογαριασμός {bill.bill_number}: διορθώθηκαν με το χέρι {', '.join(overrides) or 'κανένα πεδίο'}")
    return RedirectResponse(f"/bills/{bill_id}?msg=Αποθηκεύτηκε", 303)


@router.post("/bills/{bill_id}/clear-overrides")
def bill_clear_overrides(bill_id: int, s: Session = Depends(get_session)):
    bill = s.get(Bill, bill_id)
    if bill is None:
        raise HTTPException(404)
    pid = bill.paperless_id
    bill.overrides_json = None
    s.commit()
    if pid:
        jobs.process_one(pid)
    return RedirectResponse(f"/bills/{bill_id}?msg=Οι διορθώσεις αφαιρέθηκαν, ξαναδιαβάστηκε", 303)


@router.post("/bills/{bill_id}/reread")
def bill_reread(bill_id: int, s: Session = Depends(get_session)):
    bill = s.get(Bill, bill_id)
    if bill is None or not bill.paperless_id:
        raise HTTPException(404)
    pid = bill.paperless_id
    s.close()
    st = jobs.process_one(pid)
    return RedirectResponse(f"/bills/{bill_id}?msg=Ξαναδιαβάστηκε ({st})", 303)


@router.post("/bills/{bill_id}/delete")
def bill_delete(bill_id: int, s: Session = Depends(get_session)):
    bill = s.get(Bill, bill_id)
    if bill is None:
        raise HTTPException(404)
    for doc in s.query(Document).filter(Document.bill_id == bill_id).all():
        doc.bill_id, doc.status, doc.message = None, "skipped", "Ο λογαριασμός διαγράφηκε από την εφαρμογή"
    jobs.event(s, f"Διαγράφηκε ο λογαριασμός {bill.bill_number} ({bill.period_start}–{bill.period_end})", "warn")
    s.delete(bill)
    return RedirectResponse("/bills", 303)


@router.get("/analysis", response_class=HTMLResponse)
def analysis(request: Request, s: Session = Depends(get_session)):
    bills = stats.usable_bills(s)
    years = stats.by_year(bills, "kwh_per_day")
    cost_years = stats.by_year(bills, "period_cost")
    year_totals = {}
    for y in years:
        yb = [b for b in bills if b.month.year == y]
        year_totals[y] = stats._agg(yb)
    return render(request, "analysis.html", bills=bills, series=stats.series(bills), years=years,
                  cost_years=cost_years, year_totals=year_totals, months=stats.MONTHS,
                  composition=stats.composition(bills))


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, s: Session = Depends(get_session)):
    rt = runtime_settings.load(s)
    docs = s.query(Document).order_by(Document.paperless_id.desc()).all()
    events = s.query(Event).order_by(Event.id.desc()).limit(60).all()
    counts: dict[str, int] = {}
    for d in docs:
        counts[d.status] = counts.get(d.status, 0) + 1
    return render(request, "settings.html", rt=rt, docs=docs, events=events, counts=counts, state=jobs.state,
                  env=get_settings(), msg=request.query_params.get("msg"))


@router.post("/settings")
def settings_save(
    paperless_tag: str = Form(...),
    ollama_url: str = Form(""),
    ollama_model: str = Form(""),
    llm_enabled: bool = Form(False),
    sync_interval_minutes: int = Form(30),
    s: Session = Depends(get_session),
):
    from .main import reschedule

    interval = max(5, min(sync_interval_minutes, 24 * 60))
    runtime_settings.save(s, paperless_tag=paperless_tag.strip(), ollama_url=ollama_url.strip(),
                          ollama_model=ollama_model.strip(), llm_enabled=llm_enabled,
                          sync_interval_minutes=interval)
    reschedule(interval)
    return RedirectResponse("/settings?msg=Οι ρυθμίσεις αποθηκεύτηκαν", 303)


@router.post("/sync")
def sync_now(background: BackgroundTasks, force: bool = Form(False), back: str = Form("/settings")):
    if not jobs.state["running"]:
        jobs.state["running"] = True  # shown immediately on the next page, the task resets it
        background.add_task(jobs.run_sync, force)
    if not back.startswith("/") or back.startswith("//"):
        back = "/settings"
    if back == "/settings":
        back += "?msg=" + ("Ξαναδιάβασμα όλων ξεκίνησε" if force else "Συγχρονισμός ξεκίνησε")
    return RedirectResponse(back, 303)


@router.post("/documents/{paperless_id}/process")
def document_process(paperless_id: int):
    st = jobs.process_one(paperless_id)
    return RedirectResponse(f"/settings?msg=Έγγραφο #{paperless_id}: {st}", 303)


# ---------------------------------------------------------------- API
def _doc_id(payload: dict) -> int | None:
    for key in ("document_id", "paperless_id", "id"):
        v = payload.get(key)
        if isinstance(v, int) or (isinstance(v, str) and v.isdigit()):
            return int(v)
    url = payload.get("doc_url") or payload.get("url") or ""
    m = re.search(r"/documents/(\d+)", str(url))
    return int(m.group(1)) if m else None


@router.post("/api/webhook")
async def webhook(request: Request, background: BackgroundTasks):
    secret = get_settings().webhook_secret
    if secret and request.headers.get("x-webhook-secret") != secret:
        raise HTTPException(401, "bad secret")
    try:
        payload = await request.json()
    except ValueError:
        form = await request.form()
        payload = dict(form)
    pid = _doc_id(payload if isinstance(payload, dict) else {})
    if pid is None:
        raise HTTPException(422, "document_id missing")
    background.add_task(jobs.process_one, pid)
    return {"queued": pid}


@router.get("/api/bills")
def api_bills(s: Session = Depends(get_session)):
    out = []
    for b in stats.usable_bills(s):
        row = {f.name: (getattr(b, f.name).isoformat() if isinstance(getattr(b, f.name), date)
                        else getattr(b, f.name)) for f in FIELDS}
        row.update(id=b.id, paperless_id=b.paperless_id, status=b.status, method=b.method,
                   period_cost=b.period_cost, all_in_rate=b.all_in_rate, kwh_per_day=b.kwh_per_day)
        out.append(row)
    return out


@router.get("/export.csv")
def export_csv(s: Session = Depends(get_session)):
    rows = api_bills(s)
    buf = io.StringIO()
    buf.write("﻿")  # Excel opens UTF-8 correctly with a BOM
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), delimiter=";")
        w.writeheader()
        for r in rows:
            w.writerow({k: (str(v).replace(".", ",") if isinstance(v, float) else v) for k, v in r.items()})
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=vibe-electricity.csv"})


@router.get("/api/check")
def api_check(s: Session = Depends(get_session)):
    """Connection test for the Settings page."""
    rt = runtime_settings.load(s)
    out = {"paperless": None, "tag": None, "ollama": None, "models": []}
    try:
        with Paperless() as pl:
            pl.ping()
            tag_id = pl.tag_id(rt.paperless_tag)
            out["paperless"] = "ok"
            out["tag"] = (f"ok ({len(pl.tagged_documents(tag_id))} έγγραφα)" if tag_id
                          else f"δεν υπάρχει tag «{rt.paperless_tag}»")
    except (PaperlessError, Exception) as exc:  # noqa: BLE001
        out["paperless"] = str(exc)[:200]
    if rt.ollama_url:
        try:
            out["models"] = llm.list_models(rt.ollama_url)
            out["ollama"] = "ok" if rt.ollama_model in out["models"] else f"δεν υπάρχει το μοντέλο {rt.ollama_model}"
        except Exception as exc:  # noqa: BLE001
            out["ollama"] = f"δεν απαντά: {exc}"[:200]
    return out


@router.get("/status")
def status():
    return {"running": jobs.state["running"],
            "last_sync": jobs.state["last_sync"].isoformat() if jobs.state["last_sync"] else None}


@router.get("/healthz")
def healthz():
    return JSONResponse({"ok": True})
