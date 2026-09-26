"""The rubric logic, fed with perfect facts, must reproduce the manual ground truth.

This isolates the deterministic half of the system: if a test here fails, the
bug is in a criterion, not in the language model.
"""

from typing import Any

import pytest

from callaudit.domain.audit import Status
from callaudit.domain.conversation import Conversation
from callaudit.domain.engine import audit_conversation
from callaudit.domain.facts import ConversationFacts

CONVERSATION_IDS = [f"C{number:02d}" for number in range(1, 21)]


@pytest.mark.parametrize("conversation_id", CONVERSATION_IDS)
def test_failed_criteria_match_ground_truth(
    conversation_id: str,
    conversations: dict[str, Conversation],
    golden_facts: dict[str, ConversationFacts],
    ground_truth: dict[str, dict[str, Any]],
) -> None:
    audit = audit_conversation(conversations[conversation_id], golden_facts[conversation_id])

    expected = ground_truth[conversation_id]
    assert sorted(audit.failed_criteria) == sorted(expected["failed"])
    assert audit.severity == expected["severity"]


@pytest.mark.parametrize("conversation_id", CONVERSATION_IDS)
def test_every_quote_is_literal_transcript_text(
    conversation_id: str,
    conversations: dict[str, Conversation],
    golden_facts: dict[str, ConversationFacts],
) -> None:
    conversation = conversations[conversation_id]
    audit = audit_conversation(conversation, golden_facts[conversation_id])

    for result in audit.criteria:
        if result.status is Status.VIOLATES:
            assert result.evidence, f"{result.criterion_id} failed without a quote"
        for evidence in result.evidence:
            assert evidence.quote == conversation.transcript[evidence.turn].text


def test_golden_facts_are_consistent_with_transcripts(
    conversations: dict[str, Conversation],
    golden_facts: dict[str, ConversationFacts],
) -> None:
    problems = {
        cid: facts.inconsistencies(conversations[cid])
        for cid, facts in golden_facts.items()
        if facts.inconsistencies(conversations[cid])
    }
    assert problems == {}
