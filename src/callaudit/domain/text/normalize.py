"""Accent- and case-insensitive text normalization for Spanish transcripts."""

import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")
_TOKEN = re.compile(r"[a-z0-9]+")


def fold(text: str) -> str:
    """Lowercase, strip diacritics and collapse whitespace.

    Transcripts come from speech-to-text, so "cédula" and "cedula" must match.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _WHITESPACE.sub(" ", stripped.lower()).strip()


def tokenize(text: str) -> list[str]:
    """Split folded text into alphanumeric tokens, dropping punctuation."""
    return _TOKEN.findall(fold(text))
