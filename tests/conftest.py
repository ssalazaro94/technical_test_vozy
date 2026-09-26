import json
from pathlib import Path
from typing import Any

import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict

from callaudit.domain.conversation import Conversation, Dataset
from callaudit.domain.facts import ConversationFacts

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class _LocalFiles(BaseSettings):
    """Location of the client's dataset, which is provided privately and never versioned."""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    local_dataset_path: Path | None = None


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def dataset() -> Dataset:
    path = _LocalFiles().local_dataset_path
    if path is None or not path.exists():
        pytest.skip("dataset not available: set LOCAL_DATASET_PATH (environment or .env)")
    return Dataset.model_validate(_load_json(path))


@pytest.fixture(scope="session")
def conversations(dataset: Dataset) -> dict[str, Conversation]:
    return {conversation.id: conversation for conversation in dataset.conversations}


@pytest.fixture(scope="session")
def golden_facts() -> dict[str, ConversationFacts]:
    raw = _load_json(FIXTURES / "golden_facts.json")
    return {cid: ConversationFacts.model_validate(facts) for cid, facts in raw.items()}


@pytest.fixture(scope="session")
def ground_truth() -> dict[str, dict[str, Any]]:
    data: dict[str, dict[str, Any]] = _load_json(FIXTURES / "ground_truth.json")
    return data
