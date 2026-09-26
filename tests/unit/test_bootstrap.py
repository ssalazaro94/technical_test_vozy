from typing import Any

from pydantic import SecretStr

from callaudit.adapters.llm.disabled import DisabledLanguageModel
from callaudit.adapters.llm.gemini import GeminiLanguageModel
from callaudit.bootstrap import build_audit_service, build_language_model
from callaudit.config import Settings
from callaudit.domain.audit import AnalysisStatus
from callaudit.domain.conversation import Conversation, Dataset


def _settings(**overrides: Any) -> Settings:
    # `_env_file=None` keeps the developer's local .env out of the tests.
    return Settings(_env_file=None, **overrides)


def test_provider_none_disables_the_model() -> None:
    llm = build_language_model(_settings(llm_provider="none", gemini_api_key=SecretStr("k")))
    assert isinstance(llm, DisabledLanguageModel)


def test_missing_key_degrades_instead_of_crashing() -> None:
    llm = build_language_model(_settings(llm_provider="gemini", gemini_api_key=None))
    assert isinstance(llm, DisabledLanguageModel)


def test_gemini_is_built_when_a_key_is_present() -> None:
    llm = build_language_model(_settings(gemini_api_key=SecretStr("fake-key"), llm_model="m"))
    assert isinstance(llm, GeminiLanguageModel)
    assert llm.model_name == "m"


async def test_service_without_key_still_audits(
    dataset: Dataset, conversations: dict[str, Conversation]
) -> None:
    service = build_audit_service(_settings(llm_provider="none"))

    audit = await service.audit_conversation(conversations["C16"], dataset.agent_spec)

    assert audit.analysis is AnalysisStatus.PARTIAL
    assert "LLM_PROVIDER=none" in audit.warnings[0]
    assert {"R1.a", "R1.b"} <= set(audit.failed_criteria)
