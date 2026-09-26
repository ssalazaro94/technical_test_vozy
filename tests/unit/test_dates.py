from datetime import date

import pytest

from callaudit.domain.text.dates import extract_dates, format_date_es

CALL_DATE = date(2026, 9, 22)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("con fecha de vencimiento el 15 de septiembre", date(2026, 9, 15)),
        ("con vencimiento el 30 de agosto", date(2026, 8, 30)),
        ("para el 4 de octubre", date(2026, 10, 4)),
        ("para el sábado 26 de septiembre", date(2026, 9, 26)),
        ("el primero de octubre", date(2026, 10, 1)),
        ("el 5 de enero", date(2027, 1, 5)),
        ("el 3 de marzo de 2025", date(2025, 3, 3)),
        ("registrado para 2026-09-25", date(2026, 9, 25)),
    ],
)
def test_resolves_explicit_dates(text: str, expected: date) -> None:
    assert extract_dates(text, CALL_DATE) == [expected]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("puedo pagar el sábado 26", date(2026, 9, 26)),
        ("El domingo 27 lo pago.", date(2026, 9, 27)),
        ("ayer, el lunes 21", date(2026, 9, 21)),
        # Weekday and day agree only in the previous month.
        ("el lunes 31", date(2026, 8, 31)),
    ],
)
def test_resolves_weekday_and_day_against_call_date(text: str, expected: date) -> None:
    assert extract_dates(text, CALL_DATE)[0] == expected


def test_bare_weekday_is_not_a_concrete_date() -> None:
    assert extract_dates("El sábado.", CALL_DATE, relative=True) == []


def test_relative_expressions_only_when_requested() -> None:
    text = "mañana hago la transferencia"
    assert extract_dates(text, CALL_DATE) == []
    assert extract_dates(text, CALL_DATE, relative=True) == [date(2026, 9, 23)]


def test_morning_is_not_tomorrow() -> None:
    assert extract_dates("lo llamo por la mañana", CALL_DATE, relative=True) == []


def test_day_and_month_are_not_read_twice() -> None:
    assert extract_dates("el viernes 25 de septiembre", CALL_DATE) == [date(2026, 9, 25)]


def test_times_are_not_dates() -> None:
    assert extract_dates("después de las 6 de la tarde", CALL_DATE) == []


def test_formats_spanish_long_date() -> None:
    assert format_date_es(date(2026, 9, 15)) == "15 de septiembre de 2026"
