"""Development-only fact source: replays hand-annotated facts instead of calling a model.

It lets the whole service run end to end (complete audits, persistence,
reports) without an API key. Its name travels in every response ("model"
and /health), so a replayed result can never pass for a real one.
"""

import json
from pathlib import Path

from callaudit.domain.conversation import AgentSpec, Conversation
from callaudit.domain.facts import ConversationFacts


class ReplayFactSource:
    def __init__(self, path: Path) -> None:
        raw = json.loads(path.read_text(encoding="utf-8"))
        self._facts = {cid: ConversationFacts.model_validate(item) for cid, item in raw.items()}
        self._name = f"replay:{path.name}"

    @property
    def name(self) -> str:
        return self._name

    async def extract(self, conversation: Conversation, spec: AgentSpec) -> ConversationFacts:
        facts = self._facts.get(conversation.id)
        if facts is None:
            raise LookupError(f"sin hechos anotados para la conversación {conversation.id}")
        return facts
