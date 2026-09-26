"""Reuse the model's extraction for a conversation that was already analysed.

The cache key is a SHA-256 fingerprint of everything that determines the
model's answer: the exact prompts (which carry the agent specification, the
customer record, the call date and every turn), the response schema and the
model name. The conversation id is deliberately left out: two files may reuse
an id for different content, and the same content under another id is the
same extraction.

Consequences:
- An identical conversation costs no model call and yields the same facts.
- Any change (one character of a turn, a customer field, the date, the rules,
  the prompt, the schema or the model) produces a different key, so the model
  is called and nothing stale is ever served.
"""

import hashlib
import json
import logging

from callaudit.application.ports import Extraction, FactCache, FactSource
from callaudit.application.prompts import build_system_prompt, build_user_prompt
from callaudit.domain.audit import FactsOrigin
from callaudit.domain.conversation import AgentSpec, Conversation
from callaudit.domain.facts import ConversationFacts

logger = logging.getLogger(__name__)


def fact_cache_key(conversation: Conversation, spec: AgentSpec, model: str) -> str:
    payload = {
        "model": model,
        "system_prompt": build_system_prompt(spec),
        "user_prompt": build_user_prompt(conversation),
        "schema": ConversationFacts.model_json_schema(),
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CachedFactSource:
    """Decorator over a model-backed fact source.

    The cache is an optimisation, never a dependency: if it fails to read or
    write, the audit goes on with the model. Only facts produced by the model
    and already validated against the transcript are stored, and cached facts
    are validated again before use.
    """

    def __init__(self, inner: FactSource, cache: FactCache) -> None:
        self._inner = inner
        self._cache = cache

    @property
    def name(self) -> str:
        return self._inner.name

    async def obtain(self, conversation: Conversation, spec: AgentSpec) -> Extraction:
        key = fact_cache_key(conversation, spec, self._inner.name)
        cached = await self._read(key, conversation)
        if cached is not None:
            return Extraction(cached, FactsOrigin.CACHE)

        extraction = await self._inner.obtain(conversation, spec)
        if extraction.origin is FactsOrigin.MODEL:
            await self._write(key, extraction.facts)
        return extraction

    async def _read(self, key: str, conversation: Conversation) -> ConversationFacts | None:
        try:
            facts = await self._cache.get(key)
        except Exception as exc:
            logger.warning("fact cache read failed for %s: %r", conversation.id, exc)
            return None
        if facts is not None and facts.inconsistencies(conversation):
            logger.warning("cached facts do not fit %s; calling the model", conversation.id)
            return None
        return facts

    async def _write(self, key: str, facts: ConversationFacts) -> None:
        try:
            await self._cache.put(key, self._inner.name, facts)
        except Exception as exc:
            logger.warning("fact cache write failed: %r", exc)
