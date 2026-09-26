"""Measure how well the real language model extracts facts, against the manual annotation.

Two levels:
  1. Facts: field-by-field agreement with tests/fixtures/golden_facts.json.
  2. Verdicts: failed criteria vs tests/fixtures/ground_truth.json, as
     precision (flagged failures that are real) and recall (real failures found).

Usage (needs GEMINI_API_KEY, and LOCAL_DATASET_PATH or --dataset):
    uv run python scripts/evaluate_extraction.py [--dataset PATH] [--out evaluation/extraction.json]
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from callaudit.adapters.llm.disabled import DisabledLanguageModel
from callaudit.application.fact_extraction import FactExtractor
from callaudit.bootstrap import build_language_model
from callaudit.config import Settings
from callaudit.domain.conversation import Conversation, Dataset
from callaudit.domain.engine import audit_conversation
from callaudit.domain.facts import ConversationFacts

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_FACTS = ROOT / "tests" / "fixtures" / "golden_facts.json"
GROUND_TRUTH = ROOT / "tests" / "fixtures" / "ground_truth.json"


def _flatten(facts: ConversationFacts) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for name, value in facts.model_dump(mode="json").items():
        if name == "payment_commitment":
            commitment = value or {}
            flat["payment_commitment.client_proposal_turn"] = commitment.get("client_proposal_turn")
            flat["payment_commitment.agent_confirmation_turn"] = commitment.get(
                "agent_confirmation_turn"
            )
        elif isinstance(value, list):
            flat[name] = sorted(value)
        else:
            flat[name] = value
    return flat


async def _extract_all(
    extractor: FactExtractor, dataset: Dataset, concurrency: int
) -> dict[str, ConversationFacts | str]:
    semaphore = asyncio.Semaphore(concurrency)

    async def one(conversation: Conversation) -> tuple[str, ConversationFacts | str]:
        async with semaphore:
            try:
                return conversation.id, await extractor.extract(conversation, dataset.agent_spec)
            except Exception as exc:
                return conversation.id, f"{type(exc).__name__}: {exc}"

    return dict(await asyncio.gather(*(one(c) for c in dataset.conversations)))


def _compare(
    dataset: Dataset,
    extracted: dict[str, ConversationFacts | str],
    golden: dict[str, ConversationFacts],
    truth: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    field_hits: dict[str, int] = {}
    field_total: dict[str, int] = {}
    field_mismatches: list[dict[str, Any]] = []
    true_pos = false_pos = false_neg = 0
    verdict_mismatches: list[dict[str, Any]] = []
    errors: dict[str, str] = {}

    for conversation in dataset.conversations:
        cid = conversation.id
        facts = extracted[cid]
        if isinstance(facts, str):
            errors[cid] = facts
            continue
        expected, actual = _flatten(golden[cid]), _flatten(facts)
        for name, value in expected.items():
            field_total[name] = field_total.get(name, 0) + 1
            if actual[name] == value:
                field_hits[name] = field_hits.get(name, 0) + 1
            else:
                field_mismatches.append(
                    {"conversation": cid, "field": name, "expected": value, "got": actual[name]}
                )

        failed = set(audit_conversation(conversation, facts).failed_criteria)
        should_fail = set(truth[cid]["failed"])
        true_pos += len(failed & should_fail)
        false_pos += len(failed - should_fail)
        false_neg += len(should_fail - failed)
        if failed != should_fail:
            verdict_mismatches.append(
                {
                    "conversation": cid,
                    "false_positives": sorted(failed - should_fail),
                    "false_negatives": sorted(should_fail - failed),
                }
            )

    flagged, real = true_pos + false_pos, true_pos + false_neg
    return {
        "extraction_errors": errors,
        "field_accuracy": {
            name: round(field_hits.get(name, 0) / total, 3) for name, total in field_total.items()
        },
        "field_mismatches": field_mismatches,
        "verdicts": {
            "true_positives": true_pos,
            "false_positives": false_pos,
            "false_negatives": false_neg,
            "precision": round(true_pos / flagged, 3) if flagged else None,
            "recall": round(true_pos / real, 3) if real else None,
            "mismatches": verdict_mismatches,
        },
    }


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
    truth = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))

    extractor = FactExtractor(llm, max_attempts=settings.extraction_max_attempts)
    extracted = await _extract_all(extractor, dataset, settings.llm_max_concurrency)
    result = {"model": llm.model_name, **_compare(dataset, extracted, golden, truth)}

    verdicts = result["verdicts"]
    print(f"Modelo: {llm.model_name}")
    print(f"Errores de extracción: {len(result['extraction_errors'])}")
    print(f"Veredictos -> precisión: {verdicts['precision']}  recall: {verdicts['recall']}")
    print(f"  FP={verdicts['false_positives']}  FN={verdicts['false_negatives']}")
    for mismatch in verdicts["mismatches"]:
        print(f"  {mismatch}")
    print("Exactitud por campo:")
    for name, accuracy in sorted(result["field_accuracy"].items(), key=lambda item: item[1]):
        print(f"  {accuracy:5.2f}  {name}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Detalle en {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
