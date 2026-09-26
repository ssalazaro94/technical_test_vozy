"""Precision of a run against the manual ground truth, without any model call."""

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from callaudit.application.models import DatasetAudit
from callaudit.domain.audit import AnalysisStatus, ConversationAudit, Severity
from callaudit.domain.conversation import Conversation
from callaudit.domain.criteria import RUBRIC
from callaudit.domain.engine import audit_conversation
from callaudit.domain.facts import ConversationFacts
from callaudit.domain.report import build_report
from callaudit.evaluation import GroundTruthEntry, compare_run, render_text
from tests.conftest import ROOT

CRITERIA = [criterion.id for criterion in RUBRIC]


def _run(audits: list[ConversationAudit]) -> DatasetAudit:
    return DatasetAudit(
        run_id=uuid4(),
        generated_at=datetime(2026, 9, 26, tzinfo=UTC),
        rubric_version="2026-09-25",
        model="test",
        report=build_report(audits),
        audits=audits,
    )


@pytest.fixture
def truth(ground_truth: dict[str, dict[str, Any]]) -> dict[str, GroundTruthEntry]:
    return {cid: GroundTruthEntry.model_validate(entry) for cid, entry in ground_truth.items()}


@pytest.fixture
def perfect_run(
    conversations: dict[str, Conversation], golden_facts: dict[str, ConversationFacts]
) -> DatasetAudit:
    return _run([audit_conversation(conversations[cid], golden_facts[cid]) for cid in golden_facts])


def test_a_perfect_run_scores_one(
    perfect_run: DatasetAudit, truth: dict[str, GroundTruthEntry]
) -> None:
    report = compare_run(perfect_run, truth, CRITERIA)

    assert report.conversations_compared == 20
    assert report.exact_matches == 20
    assert report.severity_matches == 20
    assert report.true_positives == 30  # all the failures in the ground truth
    assert (report.false_positives, report.false_negatives) == (0, 0)
    assert (report.precision, report.recall, report.f1) == (1.0, 1.0, 1.0)
    assert report.mismatches == []
    assert [m.criterion_id for m in report.per_criterion] == CRITERIA


def test_a_false_alarm_lowers_precision_only(
    conversations: dict[str, Conversation],
    golden_facts: dict[str, ConversationFacts],
    truth: dict[str, GroundTruthEntry],
) -> None:
    # The model reads the "¿Tanto?" of C11 as a dispute: R7.a becomes a false positive.
    facts = dict(golden_facts)
    facts["C11"] = golden_facts["C11"].model_copy(update={"escalation_request_turn": 5})
    run = _run([audit_conversation(conversations[cid], facts[cid]) for cid in facts])

    report = compare_run(run, truth, CRITERIA)

    assert (report.true_positives, report.false_positives, report.false_negatives) == (30, 1, 0)
    assert report.precision == 0.968  # 30 / 31
    assert report.recall == 1.0
    assert report.exact_matches == 19
    [mismatch] = report.mismatches
    assert mismatch.conversation_id == "C11"
    assert mismatch.false_positives == ["R7.a"]
    r7a = next(m for m in report.per_criterion if m.criterion_id == "R7.a")
    assert (r7a.true_positives, r7a.false_positives) == (2, 1)


def test_a_missed_failure_lowers_recall_only(
    conversations: dict[str, Conversation],
    golden_facts: dict[str, ConversationFacts],
    truth: dict[str, GroundTruthEntry],
) -> None:
    # The model misses the discount offered in C05: R6.a and R6.b are not detected.
    facts = dict(golden_facts)
    facts["C05"] = golden_facts["C05"].model_copy(
        update={"benefit_offer_turn": None, "benefit_referral_turn": 6}
    )
    run = _run([audit_conversation(conversations[cid], facts[cid]) for cid in facts])

    report = compare_run(run, truth, CRITERIA)

    assert (report.false_positives, report.false_negatives) == (0, 2)
    assert report.precision == 1.0
    assert report.recall == 0.933  # 28 / 30
    assert report.mismatches[0].false_negatives == ["R6.a", "R6.b"]


def test_partial_and_missing_conversations_are_listed_not_counted(
    conversations: dict[str, Conversation],
    golden_facts: dict[str, ConversationFacts],
    truth: dict[str, GroundTruthEntry],
) -> None:
    audits = [
        audit_conversation(conversations[cid], None if cid == "C14" else golden_facts[cid])
        for cid in golden_facts
        if cid != "C20"
    ]
    assert next(a for a in audits if a.conversation_id == "C14").analysis is AnalysisStatus.PARTIAL

    report = compare_run(_run(audits), truth, CRITERIA)

    assert report.conversations_compared == 18
    assert report.skipped_partial == ["C14"]
    assert report.missing_from_run == ["C20"]
    assert report.false_positives == report.false_negatives == 0


def test_undefined_metrics_are_null_not_zero() -> None:
    empty = _run([])
    report = compare_run(empty, {"C01": GroundTruthEntry(failed=[], severity=Severity.NONE)})

    assert report.precision is None
    assert report.recall is None
    assert report.f1 is None
    assert report.missing_from_run == ["C01"]


def test_text_summary_names_the_differences(
    conversations: dict[str, Conversation],
    golden_facts: dict[str, ConversationFacts],
    truth: dict[str, GroundTruthEntry],
) -> None:
    facts = dict(golden_facts)
    facts["C11"] = golden_facts["C11"].model_copy(update={"escalation_request_turn": 5})
    run = _run([audit_conversation(conversations[cid], facts[cid]) for cid in facts])

    text = render_text(compare_run(run, truth, CRITERIA))

    assert "precisión=0.968 recall=1.0" in text
    assert "C11: falsos positivos=['R7.a']" in text


def test_the_script_reads_a_saved_results_file(perfect_run: DatasetAudit, tmp_path: Path) -> None:
    results = tmp_path / "results.json"
    results.write_text(perfect_run.model_dump_json(), encoding="utf-8")
    out = tmp_path / "precision.json"

    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "evaluate_precision.py"), str(results),
         "--out", str(out)],
        capture_output=True, text=True, check=True, cwd=ROOT,
    )  # fmt: skip

    assert "Coincidencia exacta: 20/20" in completed.stdout
    assert json.loads(out.read_text(encoding="utf-8"))["precision"] == 1.0
