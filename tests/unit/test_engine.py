import pytest
from pydantic import ValidationError

from callaudit.domain.audit import (
    AnalysisStatus,
    CriterionResult,
    Evidence,
    Method,
    Severity,
    Status,
)
from callaudit.domain.conversation import Conversation, Speaker
from callaudit.domain.engine import audit_conversation
from callaudit.domain.facts import ConversationFacts, Interlocutor, Outcome, PaymentCommitment
from callaudit.domain.report import build_report
from callaudit.domain.scoring import overall_severity, weighted_score

CODE_ONLY = {"R1.a", "R1.b", "R2.a", "R10.a"}


def _result(status: Status, severity: Severity) -> CriterionResult:
    return CriterionResult(
        criterion_id="X",
        rule_id="R0",
        title="test",
        method=Method.CODE,
        severity=severity,
        status=status,
        evidence=[Evidence(turn=0, speaker=Speaker.AGENT, quote="hola")],
        explanation="test",
    )


class TestDegradedMode:
    def test_without_facts_code_criteria_still_run(
        self, conversations: dict[str, Conversation]
    ) -> None:
        audit = audit_conversation(conversations["C14"], None)

        assert audit.analysis is AnalysisStatus.PARTIAL
        assert audit.outcome is None
        by_id = {r.criterion_id: r for r in audit.criteria}
        for criterion_id, result in by_id.items():
            if criterion_id in CODE_ONLY:
                assert result.status is not Status.UNDETERMINED
            else:
                assert result.status is Status.UNDETERMINED
        # The legal threat is still caught by the lexicon alone.
        assert by_id["R10.a"].status is Status.VIOLATES

    def test_without_facts_the_output_shape_is_unchanged(
        self,
        conversations: dict[str, Conversation],
        golden_facts: dict[str, ConversationFacts],
    ) -> None:
        full = audit_conversation(conversations["C01"], golden_facts["C01"])
        partial = audit_conversation(conversations["C01"], None)

        assert full.model_dump().keys() == partial.model_dump().keys()
        assert [r.criterion_id for r in full.criteria] == [r.criterion_id for r in partial.criteria]


class TestFactsConsistency:
    def test_rejects_out_of_range_turn(self, conversations: dict[str, Conversation]) -> None:
        facts = ConversationFacts(
            interlocutor=Interlocutor.HOLDER,
            debt_disclosure_turn=99,
            outcome=Outcome.NO_RESULT,
        )
        with pytest.raises(ValueError, match="debt_disclosure_turn=99"):
            audit_conversation(conversations["C01"], facts)

    def test_rejects_turn_with_wrong_speaker(self, conversations: dict[str, Conversation]) -> None:
        facts = ConversationFacts(
            interlocutor=Interlocutor.HOLDER,
            payment_commitment=PaymentCommitment(agent_confirmation_turn=5),
            outcome=Outcome.PAYMENT_COMMITMENT,
        )
        problems = facts.inconsistencies(conversations["C01"])
        assert problems == [
            "payment_commitment.agent_confirmation_turn=5: se esperaba un turno de 'agente'"
        ]

    def test_rejects_unknown_fields_from_the_model(self) -> None:
        with pytest.raises(ValidationError):
            ConversationFacts.model_validate(
                {"interlocutor": "titular", "outcome": "sin_resultado", "verdict": "cumple"}
            )


class TestEvidenceGuarantee:
    def test_violation_without_evidence_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="requiere al menos una cita"):
            CriterionResult(
                criterion_id="R1.a",
                rule_id="R1",
                title="test",
                method=Method.CODE,
                severity=Severity.MINOR,
                status=Status.VIOLATES,
                evidence=[],
                explanation="sin cita",
            )


class TestScoring:
    def test_weights_by_severity(self) -> None:
        results = [
            _result(Status.COMPLIES, Severity.CRITICAL),
            _result(Status.VIOLATES, Severity.MAJOR),
            _result(Status.NOT_APPLICABLE, Severity.CRITICAL),
            _result(Status.UNDETERMINED, Severity.CRITICAL),
        ]
        # 5 met out of 5 + 3 judged; not applicable and undetermined are ignored.
        assert weighted_score(results) == 62.5

    def test_nothing_applicable_scores_full(self) -> None:
        assert weighted_score([_result(Status.NOT_APPLICABLE, Severity.MINOR)]) == 100.0

    def test_overall_severity_is_the_worst_failure(self) -> None:
        results = [
            _result(Status.VIOLATES, Severity.MINOR),
            _result(Status.VIOLATES, Severity.MAJOR),
            _result(Status.VIOLATES, Severity.CRITICAL),
            _result(Status.COMPLIES, Severity.CRITICAL),
        ]
        assert overall_severity(results) is Severity.CRITICAL

    def test_no_failures_means_no_severity(self) -> None:
        assert overall_severity([_result(Status.COMPLIES, Severity.MAJOR)]) is Severity.NONE


class TestReport:
    def test_aggregates_the_twenty_conversations(
        self,
        conversations: dict[str, Conversation],
        golden_facts: dict[str, ConversationFacts],
    ) -> None:
        audits = [audit_conversation(conversations[cid], golden_facts[cid]) for cid in golden_facts]

        report = build_report(audits)

        assert report.total_conversations == 20
        assert report.fully_analyzed == 20
        assert report.severity_distribution == {
            Severity.NONE: 7,
            Severity.MINOR: 1,
            Severity.MAJOR: 5,
            Severity.CRITICAL: 7,
        }
        r9a = next(s for s in report.criteria if s.criterion_id == "R9.a")
        assert r9a.violated == 5
        assert r9a.compliance_rate == 0.75
        assert report.most_frequent_failures[0].criterion_id == "R9.a"

    def test_rate_is_null_when_criterion_never_applied(
        self, conversations: dict[str, Conversation], golden_facts: dict[str, ConversationFacts]
    ) -> None:
        report = build_report([audit_conversation(conversations["C01"], golden_facts["C01"])])

        r8a = next(s for s in report.criteria if s.criterion_id == "R8.a")
        assert r8a.compliance_rate is None
        assert r8a.not_applicable == 1
