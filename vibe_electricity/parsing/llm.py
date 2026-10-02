"""Generic bill reader via a local Ollama model, for bills the rules do not
cover (other suppliers, a changed layout). It reads the same OCR text and
answers in a fixed JSON schema; the validator then checks the sums like for
any other reader.
"""

from __future__ import annotations

import json
import logging
import re

import httpx

from .numbers import to_date
from .schema import FIELDS, BillData

log = logging.getLogger("vibe_electricity.llm")

MAX_CHARS = 14000

_TYPES = {"money": "number", "kwh": "number", "rate": "number", "kva": "number", "int": "integer",
          "date": "string", "text": "string"}


def _schema() -> dict:
    props = {f.name: {"type": [_TYPES[f.kind], "null"]} for f in FIELDS}
    return {"type": "object", "properties": props, "required": [f.name for f in FIELDS]}


def _prompt(text: str) -> str:
    lines = "\n".join(
        f"- {f.name}: {f.hint}" + (" (DD/MM/YYYY)" if f.kind == "date" else "") for f in FIELDS
    )
    return (
        "You read Greek household electricity bills. Below is the OCR text of one bill. "
        "Extract these fields; use null when a value is not printed on the bill. Do not compute or guess "
        "values that are not printed. Amounts are in euro with '.' as decimal separator in your answer "
        "(the bill uses ',' as decimal separator and may split digits with spaces, e.g. '1 2 , 94' = 12.94). "
        "Credits, subsidies and discounts are negative.\n\n"
        f"{lines}\n\nBILL TEXT:\n{text[:MAX_CHARS]}"
    )


def _coerce(raw: dict) -> BillData:
    b = BillData()
    for f in FIELDS:
        v = raw.get(f.name)
        if v in (None, "", "null"):
            continue
        try:
            if f.kind == "date":
                v = to_date(str(v)) if re.match(r"\d{1,2}/", str(v)) else _iso(str(v))
            elif f.kind == "int":
                v = int(float(v))
            elif f.kind in ("money", "kwh", "rate", "kva"):
                v = float(str(v).replace(",", "."))
            else:
                v = str(v).strip()
        except (TypeError, ValueError):
            continue
        setattr(b, f.name, v)
    if b.bill_kind not in (None, "final", "estimate"):
        b.bill_kind = "estimate" if "έναντι" in b.bill_kind.lower() else "final"
    return b


def _iso(s: str):
    from datetime import date

    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def extract(text: str, url: str, model: str, timeout: float = 300.0) -> BillData:
    """Raises on transport/model errors; the caller records them."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": _prompt(text)}],
        "format": _schema(),
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_ctx": 16384},
        "keep_alive": "2m",
    }
    with httpx.Client(timeout=timeout) as client:
        r = client.post(url.rstrip("/") + "/api/chat", json=payload)
        if r.status_code == 400 and "think" in r.text:
            payload.pop("think")  # models without a thinking switch reject the flag
            r = client.post(url.rstrip("/") + "/api/chat", json=payload)
        r.raise_for_status()
    content = r.json()["message"]["content"]
    try:
        raw = json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.S)
        raw = json.loads(m.group(0)) if m else {}
    return _coerce(raw)


def list_models(url: str, timeout: float = 5.0) -> list[str]:
    with httpx.Client(timeout=timeout) as client:
        r = client.get(url.rstrip("/") + "/api/tags")
        r.raise_for_status()
    return sorted(m["name"] for m in r.json().get("models", []))
