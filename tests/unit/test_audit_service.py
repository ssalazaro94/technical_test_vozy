from datetime import UTC, datetime
from typing import Any

from callaudit.adapters.persistence.null import NullAuditRepository
from callaudit.application.audit_service import AuditService
from callaudit.application.fact_extraction import FactExtractor
from callaudit.application.ports import AuditRepository
from callaudit.domain.audit import AnalysisStatus, Status
from callaudit.domain.conversation import Conversation, Dataset
from callaudit.domain.facts import ConversationFacts
from tests.fakes import (
    BrokenAuditRepository,
    GoldenLanguageModel,
    InMemoryAuditRepository,
    ScriptedLanguageModel,
)

FIXED_NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def _service(
    llm: GoldenLanguageModel,
    max_concurrency: int = 4,
    repository: AuditRepository | None = None,
) -> AuditService:
    return AuditService(
        FactExtractor(llm),
        repository or InMemoryAuditRepository(),
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
    service = AuditService(FactExtractor(llm), NullAuditRepository())

    audit = await service.audit_conversation(conversations["C01"], dataset.agent_spec)

    assert audit.analysis is AnalysisStatus.PARTIAL
    assert "RuntimeError: SDK bug" in audit.warnings[0]


class TestPersistence:
    async def test_single_audit_is_saved_and_readable(
        self,
        dataset: Dataset,
        conversations: dict[str, Conversation],
        golden_facts: dict[str, ConversationFacts],
    ) -> None:
        repository = InMemoryAuditRepository()
        service = _service(GoldenLanguageModel(conversations, golden_facts), repository=repository)

        audit = await service.audit_conversation(conversations["C05"], dataset.agent_spec)

        assert audit.persisted is True
        stored = await service.get_audit(audit.audit_id)
        assert stored is not None
        assert stored.failed_criteria == ["R6.a", "R6.b"]

    async def test_run_is_saved_with_all_its_audits(
        self,
        dataset: Dataset,
        conversations: dict[str, Conversation],
        golden_facts: dict[str, ConversationFacts],
    ) -> None:
        repository = InMemoryAuditRepository()
        service = _service(GoldenLanguageModel(conversations, golden_facts), repository=repository)

        run = await service.audit_dataset(dataset)

        assert run.persisted is True
        assert all(audit.persisted for audit in run.audits)
        assert (await service.get_run(run.run_id)) is not None
        assert len(repository.audits) == 20

    async def test_database_failure_does_not_lose_the_audit(
        self,
        dataset: Dataset,
        conversations: dict[str, Conversation],
        golden_facts: dict[str, ConversationFacts],
    ) -> None:
        service = _service(
            GoldenLanguageModel(conversations, golden_facts), repository=BrokenAuditRepository()
        )

        audit = await service.audit_conversation(conversations["C05"], dataset.agent_spec)
        run = await service.audit_dataset(dataset)

        assert audit.persisted is False
        assert audit.failed_criteria == ["R6.a", "R6.b"]
        assert "no se guardó" in audit.warnings[-1]
        assert run.persisted is False
        assert len(run.audits) == 20

    async def test_without_database_nothing_is_persisted_and_no_warning(
        self, dataset: Dataset, conversations: dict[str, Conversation]
    ) -> None:
        service = AuditService(
            FactExtractor(ScriptedLanguageModel([RuntimeError("x")])), NullAuditRepository()
        )

        audit = await service.audit_conversation(conversations["C01"], dataset.agent_spec)

        assert audit.persisted is False
        assert len(audit.warnings) == 1  # only the model warning
