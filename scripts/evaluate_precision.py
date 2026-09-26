"""Precision and recall of a saved run (results.json) against the manual ground truth.

No language model call, no API key and no dataset needed: it only reads the
service's response and tests/fixtures/ground_truth.json.

Usage:
    uv run python scripts/evaluate_precision.py results.json [--out evaluation/precision.json]
"""

import argparse
import json
import sys
from pathlib import Path

from callaudit.application.models import DatasetAudit
from callaudit.domain.criteria import RUBRIC
from callaudit.evaluation import GroundTruthEntry, compare_run, render_text

ROOT = Path(__file__).resolve().parent.parent
GROUND_TRUTH = ROOT / "tests" / "fixtures" / "ground_truth.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("results", type=Path, help="respuesta de POST /v1/audits/dataset[/file]")
    parser.add_argument("--ground-truth", type=Path, default=GROUND_TRUTH)
    parser.add_argument("--out", type=Path, help="guardar el detalle completo en JSON")
    args = parser.parse_args()

    run = DatasetAudit.model_validate_json(args.results.read_text(encoding="utf-8"))
    raw = json.loads(args.ground_truth.read_text(encoding="utf-8"))
    truth = {cid: GroundTruthEntry.model_validate(entry) for cid, entry in raw.items()}

    report = compare_run(run, truth, [criterion.id for criterion in RUBRIC])
    print(render_text(report))

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        print(f"Detalle en {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
