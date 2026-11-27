"""
Dates and times written in a text, read by code (no AI).

This module is the judge: a date found by the AI is kept only if the same day and month are read here from the
quote the AI copied from the file. Formats used at VŠE and in English/Italian/Czech course documents:
  16.12.2026  16. 12. 2026  16.12.  16. 12.  2026-12-16  16/12/2026 (day first, only when it cannot be read the US way)
  16 December 2026  16th December  December 16, 2026  Dec 16  16. prosince 2026  16 dicembre 2026
Ranges ("16.–18.12.", "16 to 18 December") are not single dates and are left out on purpose.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, time
from typing import List, Optional

MONTHS = {
    # English
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4, "may": 5,
    "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
    # Italian
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
    # Czech (nominative and genitive, without accents: the text is folded before matching)
    "leden": 1, "ledna": 1, "unor": 2, "unora": 2, "brezen": 3, "brezna": 3, "duben": 4, "dubna": 4,
    "kveten": 5, "kvetna": 5, "cerven": 6, "cervna": 6, "cervenec": 7, "cervence": 7, "srpen": 8, "srpna": 8,
    "zari": 9, "rijen": 10, "rijna": 10, "listopad": 11, "listopadu": 11, "prosinec": 12, "prosince": 12,
}
_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))


def fold(text: str) -> str:
    """Lower case, no accents, one kind of dash/quote/space: used to compare a quote with the file text."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r"[‐-―−]", "-", text)
    text = re.sub(r"[‘’‚‛`´]", "'", text)
    text = re.sub(r"[“”„‟«»]", '"', text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class FoundDate:
    day: int
    month: int
    year: Optional[int]      # None = not written
    start: int               # position in the folded text
    end: int
    text: str                # as written (folded)

    def same_day(self, d: date) -> bool:
        return self.day == d.day and self.month == d.month and (self.year is None or self.year == d.year)


_YEAR = r"(?P<y>(?:19|20)\d{2}|'\d{2}|\d{2})"
_RANGE_AFTER = re.compile(r"^\s*(?:-|to|until|till|az|do|al)\s*\d")   # "16.-18.12", "16 to 18 december"
_RANGE_BEFORE = re.compile(r"\d\s*(?:\.|)\s*(?:-|to|az|al)\s*$")

PATTERNS = [
    # 2026-12-16
    re.compile(r"(?<![\d.])(?P<y>(?:19|20)\d{2})-(?P<m>\d{1,2})-(?P<d>\d{1,2})(?![\d-])"),
    # 16.12.2026 / 16. 12. 2026 / 16.12. / 16. 12. / 16.12.26
    re.compile(r"(?<![\d.])(?P<d>\d{1,2})\s?\.\s?(?P<m>\d{1,2})\s?\.(?:\s?" + _YEAR + r"(?![\d.:]))?(?![\d])"),
    # 18.11 in a schedule table (no final dot): only with a two-digit month, never a time ("09.15", "14.00 h", "10.30 am")
    re.compile(r"(?<![\d.])(?P<d>\d{1,2})\.(?P<m>0[1-9]|1[0-2])(?![\d.:])(?!\s?(?:h|hod|am|pm|a\.m|p\.m)\b)"),
    # 16/12/2026 (day first); also 16/12
    re.compile(r"(?<![\d/])(?P<d>\d{1,2})/(?P<m>\d{1,2})(?:/" + _YEAR + r"(?![\d.:]))?(?![\d/])"),
    # 16 December 2026 / 16th of December / 16. prosince 2026 / 16 dicembre
    re.compile(r"(?<!\d)(?P<d>\d{1,2})(?:st|nd|rd|th)?\.?\s*(?:of\s+)?(?P<mn>" + _MONTH_RE + r")\.?(?![a-z])(?:,?\s*(?P<y>(?:19|20)\d{2}))?"),
    # December 16, 2026 / Dec 16th
    re.compile(r"(?<![a-z])(?P<mn>" + _MONTH_RE + r")\.?\s+(?P<d>\d{1,2})(?:st|nd|rd|th)?(?!\d)(?:,?\s*(?P<y>(?:19|20)\d{2}))?"),
]


def _year(raw: Optional[str]) -> Optional[int]:
    if not raw:
        return None
    raw = raw.lstrip("'")
    y = int(raw)
    return y if y >= 1900 else 2000 + y


def find_dates(text: str, folded: bool = False) -> List[FoundDate]:
    """Every single date written in the text (ranges and impossible dates are left out)."""
    t = text if folded else fold(text)
    out: List[FoundDate] = []
    taken: List[range] = []
    for i, pat in enumerate(PATTERNS):
        for m in pat.finditer(t):
            if any(m.start() in r or (m.end() - 1) in r for r in taken):
                continue
            gd = m.groupdict()
            month = MONTHS.get(gd["mn"].rstrip(".")) if gd.get("mn") else int(gd["m"])
            day = int(gd["d"])
            year = _year(gd.get("y"))
            if i == 3:   # d/m: if it could also be m/d (both <= 12, different) it is ambiguous: not a date for us
                if day <= 12 and month <= 12 and day != month:
                    continue
            if not month or not (1 <= month <= 12) or not (1 <= day <= 31):
                continue
            try:
                date(year or 2024, month, day)   # 2024: leap year, so 29.2. without a year is allowed
            except ValueError:
                continue
            if _RANGE_AFTER.match(t[m.end():m.end() + 8]) or _RANGE_BEFORE.search(t[max(0, m.start() - 6):m.start()]):
                continue
            if i == 1:
                nxt = t[m.end():m.end() + 1]
                if year is None and (nxt.isdigit() or nxt == "."):
                    continue   # "1.2.3" section numbers, "12. 09..12" (row number + a broken date)
                if gd.get("y") and len(gd["y"].lstrip("'")) == 2 and re.search(r"\s", m.group(0)):
                    continue   # "11. 02.12" is row 11 + 2 December, not 11 February 2012: two-digit years only in "16.12.26"
            out.append(FoundDate(day, month, year, m.start(), m.end(), m.group(0)))
            taken.append(range(m.start(), m.end()))
    return sorted(out, key=lambda f: f.start)


TIME_RE = re.compile(r"(?<![\d.:])(?P<h>[01]?\d|2[0-3])(?:[:.](?P<mi>[0-5]\d))\s*(?:h\b|hod\b)?(?P<ap>\s*[ap]\.?m\.?)?(?![\d])"
                     r"|(?<![\d.:])(?P<h2>1[0-2]|0?[1-9])\s*(?P<ap2>[ap]\.?m\.?)(?![a-z])")


def find_times(text: str) -> List[time]:
    """Times written in the text ("14:00", "14.00 h", "2 pm"); a "16.12" that is a date is not a time."""
    t = fold(text)
    dates = [range(d.start, d.end) for d in find_dates(t, folded=True)]
    out = []
    for m in TIME_RE.finditer(t):
        if any(m.start() in r or (m.end() - 1) in r for r in dates):
            continue
        if m.group("h") is not None and m.group("ap") is None and ":" not in m.group(0) and not re.search(r"h|hod", m.group(0)) \
                and 1 <= int(m.group("mi")) <= 12 and t[m.end():m.end() + 1] == ".":
            continue   # "16.12." is a date (even inside a range "16.12.-31.1."), never "16:12"
        if m.group("h") is not None:
            h, mi = int(m.group("h")), int(m.group("mi"))
            ap = (m.group("ap") or "").strip()
        else:
            h, mi, ap = int(m.group("h2")), 0, m.group("ap2")
        if ap:
            if h > 12:
                continue
            if ap.startswith("p") and h != 12:
                h += 12
            if ap.startswith("a") and h == 12:
                h = 0
        out.append(time(h, mi))
    return out


def academic_year_bounds(today: date) -> tuple[date, date]:
    """The academic year that contains today: 1 September -> 30 September of the next year (exam resits included)."""
    y = today.year if today.month >= 9 else today.year - 1
    return date(y, 9, 1), date(y + 1, 9, 30)


def complete_year(day: int, month: int, today: date) -> date:
    """A date written without the year: the one in the current academic year."""
    start, _ = academic_year_bounds(today)
    return date(start.year if month >= 9 else start.year + 1, month, day)
