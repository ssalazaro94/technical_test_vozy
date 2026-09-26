import pytest

from callaudit.domain.text.numbers import extract_amounts, extract_spoken_digits, format_cop


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("un millón doscientos cincuenta mil pesos", 1_250_000),
        ("ochocientos treinta mil pesos", 830_000),
        ("dos millones cuatrocientos mil pesos", 2_400_000),
        ("un millón novecientos ochenta mil pesos", 1_980_000),
        ("un millón quinientos ochenta y cuatro mil pesos", 1_584_000),
        ("tres millones cien mil pesos", 3_100_000),
        ("novecientos veinte mil pesos", 920_000),
        ("dos millones seiscientos veinte mil pesos", 2_620_000),
        ("un millón cincuenta mil pesos", 1_050_000),
        ("trescientos diez mil pesos", 310_000),
        ("mil pesos", 1_000),
        ("un millón de pesos", 1_000_000),
        ("un saldo de $1.250.000", 1_250_000),
        ("un saldo de 830000 pesos", 830_000),
        ("un saldo de 2,400,000", 2_400_000),
    ],
)
def test_extracts_a_single_amount(text: str, expected: int) -> None:
    assert extract_amounts(text) == [expected]


def test_ignores_small_counts_and_percentages() -> None:
    text = "Si paga esta semana le podemos aplicar un 20% de descuento, con un asesor."
    assert extract_amounts(text) == []


def test_ignores_document_digits_and_years() -> None:
    assert extract_amounts("Mis últimos dígitos son 4821, vence en 2026.") == []


def test_extracts_several_amounts_in_order() -> None:
    text = "Era de un millón novecientos ochenta mil, quedaría en un millón quinientos mil."
    assert extract_amounts(text) == [1_980_000, 1_500_000]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("4821.", "4821"),
        ("A ver... uno, tres, cinco, dos.", "1352"),
        ("cero cuatro nueve uno", "0491"),
        ("Primero dígame quién habla.", ""),
    ],
)
def test_extracts_spoken_digits(text: str, expected: str) -> None:
    assert extract_spoken_digits(text) == expected


def test_formats_colombian_pesos() -> None:
    assert format_cop(1_250_000) == "$1.250.000"
