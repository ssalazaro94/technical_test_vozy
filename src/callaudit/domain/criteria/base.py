"""Building blocks shared by every criterion.

A criterion is a pure function from an `AuditContext` to a `Finding`. It never
formats quotes itself: it names turn indexes, and the engine copies the text
from the transcript. That is what guarantees literal citations.
"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property

from callaudit.domain.audit import Method, Severity, Status
from callaudit.domain.conversation import Conversation, Speaker
from callaudit.domain.facts import ConversationFacts
from callaudit.domain.text import lexicon
from callaudit.domain.text.normalize import fold
from callaudit.domain.text.numbers import extract_spoken_digits


@dataclass(frozen=True)
class Finding:
    status: Status
    explanation: str
    turns: tuple[int, ...] = ()


def complies(explanation: str, *turns: int | None) -> Finding:
    return Finding(Status.COMPLIES, explanation, _present(turns))


def violates(explanation: str, *turns: int | None) -> Finding:
    return Finding(Status.VIOLATES, explanation, _present(turns))


def not_applicable(explanation: str) -> Finding:
    return Finding(Status.NOT_APPLICABLE, explanation)


def _present(turns: tuple[int | None, ...]) -> tuple[int, ...]:
    return tuple(sorted({turn for turn in turns if turn is not None}))


class AuditContext:
    """Everything a criterion may look at, with derived signals computed once."""

    def __init__(self, conversation: Conversation, facts: ConversationFacts | None) -> None:
        self.conversation = conversation
        self._facts = facts

    @property
    def has_facts(self) -> bool:
        return self._facts is not None

    @property
    def facts(self) -> ConversationFacts:
        """Only criteria declared with `requires_facts=True` may read this."""
        if self._facts is None:
            raise LookupError("language model facts are not available")
        return self._facts

    def text(self, turn: int) -> str:
        return fold(self.conversation.transcript[turn].text)

    @cached_property
    def agent_turns(self) -> list[int]:
        return self.conversation.turns_by(Speaker.AGENT)

    @cached_property
    def last_agent_turn(self) -> int | None:
        return self.agent_turns[-1] if self.agent_turns else None

    def next_agent_turn(self, after: int | None) -> int | None:
        """The agent's reply to a client turn: useful evidence when the agent ignored it."""
        if after is None:
            return None
        return self.conversation.next_turn_by(Speaker.AGENT, after)

    @cached_property
    def digits_request_turn(self) -> int | None:
        """First agent turn asking for the identity document digits."""
        return next(
            (turn for turn in self.agent_turns if lexicon.DIGITS_REQUEST.search(self.text(turn))),
            None,
        )

    @cached_property
    def digits_answer_turn(self) -> int | None:
        """First client turn after the request that actually contains digits."""
        if self.digits_request_turn is None:
            return None
        return next(
            (
                turn
                for turn in self.conversation.turns_by(Speaker.CLIENT)
                if turn > self.digits_request_turn
                and extract_spoken_digits(self.conversation.transcript[turn].text)
            ),
            None,
        )

    @cached_property
    def provided_digits(self) -> str:
        if self.digits_answer_turn is None:
            return ""
        return extract_spoken_digits(self.conversation.transcript[self.digits_answer_turn].text)

    @cached_property
    def sensitive_turn(self) -> int | None:
        """First agent turn that asks for personal data or discloses the debt.

        The presentation (R1) must happen at or before this point.
        """
        disclosure = self._facts.debt_disclosure_turn if self._facts is not None else None
        candidates = [turn for turn in (self.digits_request_turn, disclosure) if turn is not None]
        return min(candidates, default=None)

    @cached_property
    def opening_turns(self) -> list[int]:
        """Agent turns up to the first sensitive turn, or all of them if there is none."""
        if self.sensitive_turn is None:
            return self.agent_turns
        return [turn for turn in self.agent_turns if turn <= self.sensitive_turn]

    @cached_property
    def legal_action_turns(self) -> list[int]:
        return [
            turn
            for turn in self.agent_turns
            if any(pattern.search(self.text(turn)) for pattern in lexicon.LEGAL_ACTION_TERMS)
        ]


Evaluator = Callable[[AuditContext], Finding]


@dataclass(frozen=True)
class Criterion:
    id: str
    rule_id: str
    title: str
    severity: Severity
    method: Method
    requires_facts: bool
    evaluate: Evaluator
