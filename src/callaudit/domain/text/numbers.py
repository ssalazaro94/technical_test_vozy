"""Deterministic parsing of amounts and document digits spoken in Spanish.

A voice agent says "un millón doscientos cincuenta mil pesos", never "1.250.000".
Comparing that phrase against the customer record is arithmetic, not judgment,
so it is solved here instead of being delegated to the language model.
"""

import re

from callaudit.domain.text.normalize import fold, tokenize

_SMALL_NUMBERS: dict[str, int] = {
    "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11,
    "doce": 12, "trece": 13, "catorce": 14, "quince": 15, "dieciseis": 16,
    "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
    "veintiun": 21, "veintiuno": 21, "veintiuna": 21, "veintidos": 22,
    "veintitres": 23, "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26,
    "veintisiete": 27, "veintiocho": 28, "veintinueve": 29, "treinta": 30,
    "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70,
    "ochenta": 80, "noventa": 90, "cien": 100, "ciento": 100,
    "doscientos": 200, "doscientas": 200, "trescientos": 300, "trescientas": 300,
    "cuatrocientos": 400, "cuatrocientas": 400, "quinientos": 500, "quinientas": 500,
    "seiscientos": 600, "seiscientas": 600, "setecientos": 700, "setecientas": 700,
    "ochocientos": 800, "ochocientas": 800, "novecientos": 900, "novecientas": 900,
}  # fmt: skip
_THOUSAND = "mil"
_MILLIONS = frozenset({"millon", "millones"})
_CONNECTOR = "y"

_DIGIT_WORDS: dict[str, str] = {
    "cero": "0", "uno": "1", "un": "1", "dos": "2", "tres": "3", "cuatro": "4",
    "cinco": "5", "seis": "6", "siete": "7", "ocho": "8", "nueve": "9",
}  # fmt: skip

# Written amounts only count when they are unmistakably money: thousands
# separators ("1.250.000"), a currency sign ("$830000") or a currency word.
_WRITTEN_AMOUNT = re.compile(r"\$\s?(\d[\d.,]*)|(\d{1,3}(?:[.,]\d{3})+)|(\d+)\s?(?:pesos|cop)\b")

# Anything below this is a count ("un asesor", "20%"), not a debt amount.
MIN_AMOUNT = 1_000


def _is_number_word(token: str) -> bool:
    return token in _SMALL_NUMBERS or token == _THOUSAND or token in _MILLIONS


def _words_to_int(tokens: list[str]) -> int:
    total = 0
    current = 0
    for token in tokens:
        if token in _SMALL_NUMBERS:
            current += _SMALL_NUMBERS[token]
        elif token == _THOUSAND:
            current = (current or 1) * 1_000
        elif token in _MILLIONS:
            total += (current or 1) * 1_000_000
            current = 0
    return total + current


def _spoken_runs(tokens: list[str]) -> list[list[str]]:
    """Group consecutive number words, allowing "y" only between two of them."""
    runs: list[list[str]] = []
    run: list[str] = []
    for position, token in enumerate(tokens):
        if _is_number_word(token):
            run.append(token)
            continue
        next_token = tokens[position + 1] if position + 1 < len(tokens) else ""
        if token == _CONNECTOR and run and _is_number_word(next_token):
            continue
        if run:
            runs.append(run)
            run = []
    if run:
        runs.append(run)
    return runs


def _written_amounts(text: str) -> list[int]:
    amounts: list[int] = []
    for match in _WRITTEN_AMOUNT.finditer(fold(text)):
        raw = next(group for group in match.groups() if group)
        amounts.append(int(re.sub(r"\D", "", raw)))
    return amounts


def extract_amounts(text: str) -> list[int]:
    """Return every money amount mentioned in the text, spoken or written."""
    spoken = [_words_to_int(run) for run in _spoken_runs(tokenize(text))]
    return [amount for amount in (*spoken, *_written_amounts(text)) if amount >= MIN_AMOUNT]


def extract_spoken_digits(text: str) -> str:
    """Concatenate the digits a caller dictates: "uno, tres, cinco, dos" -> "1352"."""
    digits: list[str] = []
    for token in tokenize(text):
        if token.isdigit():
            digits.append(token)
        elif token in _DIGIT_WORDS:
            digits.append(_DIGIT_WORDS[token])
    return "".join(digits)


def format_cop(amount: int) -> str:
    """Colombian peso format: 1250000 -> "$1.250.000"."""
    return "$" + f"{amount:,}".replace(",", ".")
