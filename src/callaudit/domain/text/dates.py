"""Deterministic extraction of calendar dates from Spanish utterances.

Dates in a call are anchored to the call date: "el sábado 26" said on
2026-09-22 means 2026-09-26. Resolving that anchor with code avoids asking a
language model to do calendar arithmetic, which it routinely gets wrong.
"""

import re
from calendar import monthrange
from collections.abc import Iterator
from contextlib import suppress
from datetime import date, timedelta
from itertools import chain

from callaudit.domain.text.normalize import fold

MONTHS: dict[str, int] = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}  # fmt: skip
WEEKDAYS: dict[str, int] = {
    "lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3,
    "viernes": 4, "sabado": 5, "domingo": 6,
}  # fmt: skip
_MONTH_NAMES_ES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
    "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)  # fmt: skip

_MONTH_ALTERNATION = "|".join(MONTHS)
_WEEKDAY_ALTERNATION = "|".join(WEEKDAYS)

_DAY_OF_MONTH = re.compile(
    rf"\b(\d{{1,2}}|primero) de ({_MONTH_ALTERNATION})(?: de(?:l)? (\d{{4}}))?\b"
)
_WEEKDAY_AND_DAY = re.compile(rf"\b({_WEEKDAY_ALTERNATION}) (\d{{1,2}})\b")
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_RELATIVE: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(r"\bpasado manana\b"), 2),
    # "mañana" as a day, not as "en/por la mañana" (the morning).
    (re.compile(r"(?<!la )(?<!pasado )\bmanana\b"), 1),
    (re.compile(r"\bhoy\b"), 0),
    (re.compile(r"\bayer\b"), -1),
)


def _nearest_year(day: int, month: int, reference: date) -> date | None:
    candidates = [
        date(year, month, day)
        for year in (reference.year - 1, reference.year, reference.year + 1)
        if day <= monthrange(year, month)[1]
    ]
    return min(candidates, key=lambda candidate: abs(candidate - reference), default=None)


def _nearest_month(day: int, weekday: int, reference: date) -> date | None:
    """Pick the month that makes "<weekday> <day>" closest to the call date.

    A candidate whose weekday matches what was said wins over one that does not.
    """
    candidates: list[date] = []
    for offset in (-1, 0, 1):
        month_index = reference.month - 1 + offset
        year = reference.year + month_index // 12
        month = month_index % 12 + 1
        if day <= monthrange(year, month)[1]:
            candidates.append(date(year, month, day))
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda candidate: (candidate.weekday() != weekday, abs(candidate - reference)),
    )


def _overlaps(span: tuple[int, int], taken: list[tuple[int, int]]) -> bool:
    return any(span[0] < end and start < span[1] for start, end in taken)


def _iso_dates(folded: str) -> Iterator[tuple[tuple[int, int], date]]:
    for match in _ISO_DATE.finditer(folded):
        year, month, day = (int(group) for group in match.groups())
        with suppress(ValueError):
            yield match.span(), date(year, month, day)


def _day_of_month_dates(folded: str, reference: date) -> Iterator[tuple[tuple[int, int], date]]:
    for match in _DAY_OF_MONTH.finditer(folded):
        day_text, month_name, year_text = match.groups()
        day = 1 if day_text == "primero" else int(day_text)
        month = MONTHS[month_name]
        resolved: date | None = None
        if year_text:
            with suppress(ValueError):
                resolved = date(int(year_text), month, day)
        elif 1 <= day <= 31:
            resolved = _nearest_year(day, month, reference)
        if resolved is not None:
            yield match.span(), resolved


def _weekday_dates(folded: str, reference: date) -> Iterator[tuple[tuple[int, int], date]]:
    for match in _WEEKDAY_AND_DAY.finditer(folded):
        weekday_name, day_text = match.groups()
        resolved = _nearest_month(int(day_text), WEEKDAYS[weekday_name], reference)
        if resolved is not None:
            yield match.span(), resolved


def _relative_dates(folded: str, reference: date) -> Iterator[tuple[tuple[int, int], date]]:
    for pattern, offset in _RELATIVE:
        for match in pattern.finditer(folded):
            yield match.span(), reference + timedelta(days=offset)


def extract_dates(text: str, reference: date, *, relative: bool = False) -> list[date]:
    """Return the dates mentioned in the text, in order of appearance.

    Explicit forms are tried from most to least specific; a later form never
    reuses text already claimed by an earlier one, so "sábado 26 de septiembre"
    yields a single date. `relative=True` also resolves "hoy", "mañana",
    "pasado mañana" and "ayer"; it is meant for payment commitments, not for
    reading a due date back.
    """
    folded = fold(text)
    sources = [
        _iso_dates(folded),
        _day_of_month_dates(folded, reference),
        _weekday_dates(folded, reference),
    ]
    if relative:
        sources.append(_relative_dates(folded, reference))

    taken: list[tuple[int, int]] = []
    found: list[tuple[int, date]] = []
    for span, resolved in chain.from_iterable(sources):
        if not _overlaps(span, taken):
            taken.append(span)
            found.append((span[0], resolved))
    return [resolved for _, resolved in sorted(found)]


def format_date_es(value: date) -> str:
    """Spanish long date: 2026-09-15 -> "15 de septiembre de 2026"."""
    return f"{value.day} de {_MONTH_NAMES_ES[value.month - 1]} de {value.year}"
