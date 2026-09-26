"""Live evaluation: call the real language model and compare with the manual annotation.

It spends quota (one call per conversation). Prefer scripts/evaluate_precision.py
on a saved results.json, which gives the same verdict metrics for free. Use this
script only to diagnose the model field by field.

Two levels:
  1. Facts: field-by-field agreement with tests/fixtures/golden_facts.json.
  2. Verdicts: the same precision and recall as evaluate_precision.py.

Usage (needs GEMINI_API_KEY, and LOCAL_DATASET_PATH or --dataset):
    uv run python scripts/evaluate_extraction.py [--dataset PATH] [--out evaluation/extraction.json]
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from callaudit.adapters.llm.disabled import DisabledLanguageModel
from callaudit.application.agent_spec import LINA_AGENT_SPEC
from callaudit.application.fact_extraction import FactExtractor
from callaudit.application.models import DatasetAudit
from callaudit.bootstrap import build_language_model
from callaudit.config import Settings
from callaudit.domain.audit import ConversationAudit
from callaudit.domain.conversation import Conversation, Dataset
from callaudit.domain.criteria import RUBRIC, RUBRIC_VERSION
from callaudit.domain.engine import audit_conversation
from callaudit.domain.facts import ConversationFacts
from callaudit.domain.report import build_report
from callaudit.evaluation import GroundTruthEntry, compare_run, render_text

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_FACTS = ROOT / "tests" / "fixtures" / "golden_facts.json"
GROUND_TRUTH = ROOT / "tests" / "fixtures" / "ground_truth.json"


def _flatten(facts: ConversationFacts) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for name, value in facts.model_dump(mode="json").items():
        if name == "payment_commitment":
            commitment = value or {}
            for key in ("client_proposal_turn", "agent_confirmation_turn"):
                flat[f"payment_commitment.{key}"] = commitment.get(key)
        elif isinstance(value, list):
            flat[name] = sorted(value)
        else:
            flat[name] = value
    return flat


async def _extract_all(
    extractor: FactExtractor, dataset: Dataset, concurrency: int
) -> dict[str, ConversationFacts | str]:
    semaphore = asyncio.Semaphore(concurrency)
    spec = dataset.agent_spec or LINA_AGENT_SPEC

    async def one(conversation: Conversation) -> tuple[str, ConversationFacts | str]:
        async with semaphore:
            try:
                return conversation.id, await extractor.extract(conversation, spec)
            except Exception as exc:
                return conversation.id, f"{type(exc).__name__}: {exc}"

    return dict(await asyncio.gather(*(one(c) for c in dataset.conversations)))


def _field_accuracy(
    extracted: dict[str, ConversationFacts | str], golden: dict[str, ConversationFacts]
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    hits: dict[str, int] = {}
    totals: dict[str, int] = {}
    mismatches: list[dict[str, Any]] = []
    for cid, facts in extracted.items():
        if isinstance(facts, str) or cid not in golden:
            continue
        expected, actual = _flatten(golden[cid]), _flatten(facts)
        for name, value in expected.items():
            totals[name] = totals.get(name, 0) + 1
            if actual[name] == value:
                hits[name] = hits.get(name, 0) + 1
            else:
                mismatches.append(
                    {"conversation": cid, "field": name, "expected": value, "got": actual[name]}
                )
    accuracy = {name: round(hits.get(name, 0) / total, 3) for name, total in totals.items()}
    return accuracy, mismatches


def _as_run(
    dataset: Dataset, extracted: dict[str, ConversationFacts | str], model: str
) -> DatasetAudit:
    """The run the service would have returned: failed extractions become partial audits."""
    audits: list[ConversationAudit] = []
    for conversation in dataset.conversations:
        facts = extracted[conversation.id]
        audits.append(audit_conversation(conversation, None if isinstance(facts, str) else facts))
    return DatasetAudit(
        run_id=uuid4(),
        generated_at=datetime.now(UTC),
        rubric_version=RUBRIC_VERSION,
        model=model,
        report=build_report(audits),
        audits=audits,
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, help="client dataset (default: LOCAL_DATASET_PATH)")
    parser.add_argument("--out", type=Path, help="write the full comparison as JSON")
    args = parser.parse_args()

    settings = Settings()
    dataset_path: Path | None = args.dataset or settings.local_dataset_path
    if dataset_path is None or not dataset_path.exists():
        print("No se encontró el dataset: usa --dataset o define LOCAL_DATASET_PATH.")
        return 2
    llm = build_language_model(settings)
    if isinstance(llm, DisabledLanguageModel):
        print("No hay modelo de lenguaje configurado (GEMINI_API_KEY / LLM_PROVIDER).")
        return 2

    dataset = Dataset.model_validate_json(dataset_path.read_text(encoding="utf-8"))
    golden = {
        cid: ConversationFacts.model_validate(raw)
        for cid, raw in json.loads(GOLDEN_FACTS.read_text(encoding="utf-8")).items()
    }
    truth = {
        cid: GroundTruthEntry.model_validate(raw)
        for cid, raw in json.loads(GROUND_TRUTH.read_text(encoding="utf-8")).items()
    }

    extractor = FactExtractor(llm, max_attempts=settings.extraction_max_attempts)
    extracted = await _extract_all(extractor, dataset, settings.llm_max_concurrency)

    verdicts = compare_run(
        _as_run(dataset, extracted, llm.model_name), truth, [c.id for c in RUBRIC]
    )
    accuracy, field_mismatches = _field_accuracy(extracted, golden)
    errors = {cid: facts for cid, facts in extracted.items() if isinstance(facts, str)}

    print(render_text(verdicts))
    print(f"Errores de extracción: {len(errors)}")
    print("Exactitud por campo:")
    for name, value in sorted(accuracy.items(), key=lambda item: item[1]):
        print(f"  {value:5.2f}  {name}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        result = {
            "extraction_errors": errors,
            "field_accuracy": accuracy,
            "field_mismatches": field_mismatches,
            "verdicts": verdicts.model_dump(mode="json"),
        }
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Detalle en {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
