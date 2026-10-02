"""Greek-format numbers and dates as they come out of Paperless OCR text.

OCR of the DEH layout splits digits with spaces ("1 2 , 94", "9 1 , 00", "3 ,06",
"- 2 , 79"), so every amount pattern tolerates single spaces between digits but
never crosses a line break.
"""

from __future__ import annotations

import re
from datetime import date

# -12,34 | 1 2 , 94 | 1.234,56 | - 2 , 79 | *63 , 00
AMOUNT = r"(?:-[ ]?)?\d(?:[ .]?\d)*[ ]?,[ ]?\d[ ]?\d"
# 0,12905 | 0,00999 (unit prices, more decimals)
RATE = r"\d+[ ]?,[ ]?\d+"
DATE = r"\d{1,2}/\d{1,2}/\d{4}"


def to_float(text: str | None) -> float | None:
    """'1 2 , 94' -> 12.94, '- 2 , 79' -> -2.79, '1.850,00' -> 1850.0, '0,12905' -> 0.12905."""
    if text is None:
        return None
    s = text.replace(" ", "").replace("*", "").replace("€", "")
    neg = s.startswith("-")
    s = s.lstrip("-")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        value = float(s)
    except ValueError:
        return None
    return -value if neg else value


def to_date(text: str | None) -> date | None:
    if not text:
        return None
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if not m:
        return None
    d, mo, y = (int(x) for x in m.groups())
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def first(pattern: str, text: str, flags: int = 0) -> str | None:
    m = re.search(pattern, text, flags)
    return m.group(1) if m else None


def amount_after(label: str, text: str, *, euro: bool = False) -> float | None:
    """The amount that follows `label` (a regex) on the same line; with `euro`
    the amount must end in '€' (the page-1 summary box)."""
    tail = r"[ ]?€" if euro else r"(?![\d,])"
    return to_float(first(rf"{label}[ \t:.*]*({AMOUNT}){tail}", text))
