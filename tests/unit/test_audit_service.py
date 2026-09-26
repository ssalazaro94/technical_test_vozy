from datetime import UTC, datetime
from typing import Any

from callaudit.application.audit_service import AuditService
from callaudit.application.fact_extraction import FactExtractor
from callaudit.domain.audit import AnalysisStatus, Status
from callaudit.domain.conversation import Conversation, Dataset
from callaudit.domain.facts import ConversationFacts
from tests.fakes import GoldenLanguageModel, ScriptedLanguageModel

FIXED_NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def _service(llm: GoldenLanguageModel, max_concurrency: int = 4) -> AuditService:
    return AuditService(
        FactExtractor(llm),
        model_name=llm.model_name,
        max_concurrency=max_concurrency,
        clock=lambda: FIXED_NOW,
    )


async def test_dataset_run_reproduces_ground_truth(
    dataset: Dataset,
    conversations: dict[str, Conversation],
    golden_facts: dict[str, ConversationFacts],
    ground_truth: dict[str, dict[str, Any]],
) -> None:
    llm = GoldenLanguageModel(conversations, golden_facts)

    run = await _service(llm).audit_dataset(dataset)

    assert run.model == "golden-fake"
    assert run.generated_at == FIXED_NOW
    assert [a.conversation_id for a in run.audits] == [f"C{n:02d}" for n in range(1, 21)]
    for audit in run.audits:
        assert sorted(audit.failed_criteria) == sorted(
            ground_truth[audit.conversation_id]["failed"]
        )
    assert run.report.fully_analyzed == 20


async def test_concurrency_never_exceeds_the_limit(
    dataset: Dataset,
    conversations: dict[str, Conversation],
    golden_facts: dict[str, ConversationFacts],
) -> None:
    llm = GoldenLanguageModel(conversations, golden_facts)

    await _service(llm, max_concurrency=3).audit_dataset(dataset)

    assert llm.max_in_flight == 3
    assert sorted(llm.seen) == sorted(conversations)


async def test_a_failing_conversation_degrades_without_breaking_the_run(
    dataset: Dataset,
    conversations: dict[str, Conversation],
    golden_facts: dict[str, ConversationFacts],
) -> None:
    llm = GoldenLanguageModel(conversations, golden_facts, failing=frozenset({"C14", "C03"}))

    run = await _service(llm).audit_dataset(dataset)

    by_id = {a.conversation_id: a for a in run.audits}
    assert run.report.fully_analyzed == 18
    for cid in ("C14", "C03"):
        audit = by_id[cid]
        assert audit.analysis is AnalysisStatus.PARTIAL
        assert audit.warnings
        assert "simulated quota exhausted" in audit.warnings[0]
    # The code-only criterion still catches the legal threat in C14.
    r10a = next(r for r in by_id["C14"].criteria if r.criterion_id == "R10.a")
    assert r10a.status is Status.VIOLATES
    assert by_id["C01"].analysis is AnalysisStatus.COMPLETE


async def test_unexpected_exceptions_from_the_model_side_are_contained(
    dataset: Dataset, conversations: dict[str, Conversation]
) -> None:
    llm = ScriptedLanguageModel([RuntimeError("SDK bug")])
    service = AuditService(FactExtractor(llm), model_name=llm.model_name)

    audit = await service.audit_conversation(conversations["C01"], dataset.agent_spec)

    assert audit.analysis is AnalysisStatus.PARTIAL
    assert "RuntimeError: SDK bug" in audit.warnings[0]
