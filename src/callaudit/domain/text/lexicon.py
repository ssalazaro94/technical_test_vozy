"""Fixed vocabularies the deterministic criteria search for.

All patterns run against `fold()`-ed text: lowercase, without diacritics.
"""

import re

AGENT_NAME = re.compile(r"\blina\b")
VIRTUAL_ASSISTANT = re.compile(r"\basistente virtual\b")
COMPANY_NAME = re.compile(r"\bbanco andino\b")
RECORDING_NOTICE = re.compile(r"\bgrab(ada|ando|acion|ara|amos)\b")

# The agent asking for the identity document digits.
DIGITS_REQUEST = re.compile(r"\b(digitos|documento|cedula)\b")

# R10 forbids even mentioning these, so a negated mention still counts.
LEGAL_ACTION_TERMS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bembarg\w*"),
    re.compile(r"\bcentral(es)? de riesgo\b"),
    re.compile(r"\b(datacredito|cifin|transunion)\b"),
    re.compile(r"\bjuridic\w*"),
    re.compile(r"\bjudicial\w*"),
    re.compile(r"\baccion(es)? legal(es)?\b"),
    re.compile(r"\bproceso legal\b"),
    re.compile(r"\bdemand(a|ar|aremos|ado|ada)\b"),
    re.compile(r"\babogad\w*"),
    re.compile(r"\bjuzgad\w*"),
)
