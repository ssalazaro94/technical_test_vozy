"""HTTP adapter: routes, contracts and error shapes, over ASGI (no server, no network)."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from callaudit.adapters.http.app import create_app
from callaudit.adapters.http.examples import SYNTHETIC_CONVERSATION
from callaudit.adapters.http.routes import MAX_CONVERSATIONS_PER_RUN, MAX_UPLOAD_BYTES
from callaudit.application.audit_service import AuditService
from callaudit.application.fact_extraction import FactExtractor
from callaudit.config import Settings
from callaudit.domain.conversation import Conversation, Dataset
from callaudit.domain.facts import ConversationFacts
from tests.fakes import BrokenAuditRepository, GoldenLanguageModel, InMemoryAuditRepository


@pytest.fixture
def repository() -> InMemoryAuditRepository:
    return InMemoryAuditRepository()


@pytest.fixture
def app(
    conversations: dict[str, Conversation],
    golden_facts: dict[str, ConversationFacts],
    repository: InMemoryAuditRepository,
) -> FastAPI:
    llm = GoldenLanguageModel(conversations, golden_facts, failing=frozenset({"C03"}))
    return create_app(AuditService(FactExtractor(llm), repository))


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _dataset_json(dataset: Dataset) -> dict[str, Any]:
    return dataset.model_dump(mode="json", by_alias=True)


async def test_health_reports_model_and_rubric(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "language_model": "golden-fake",
        "rubric_version": "2026-09-25",
        "persistence": "memoria",
        "database": "ok",
    }


async def test_root_redirects_to_swagger(client: httpx.AsyncClient) -> None:
    response = await client.get("/")
    assert response.status_code == 307
    assert response.headers["location"] == "/docs"


async def test_rubric_lists_the_21_criteria(client: httpx.AsyncClient) -> None:
    body = (await client.get("/v1/rubric")).json()

    assert len(body["criteria"]) == 21
    assert body["severity_weights"] == {"leve": 1, "grave": 3, "critica": 5}
    r2c = next(c for c in body["criteria"] if c["criterion_id"] == "R2.c")
    assert r2c == {
        "criterion_id": "R2.c",
        "rule_id": "R2",
        "title": "Solo revela la deuda si los dígitos coinciden con el registro",
        "severity": "critica",
        "weight": 5,
        "method": "hibrido",
        "requires_language_model": True,
    }


async def test_audits_one_conversation_with_default_spec(
    client: httpx.AsyncClient, conversations: dict[str, Conversation]
) -> None:
    payload = {"conversacion": conversations["C20"].model_dump(mode="json", by_alias=True)}

    response = await client.post("/v1/audits", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == "C20"
    assert body["failed_criteria"] == ["R2.c"]
    assert body["severity"] == "critica"
    r2c = next(c for c in body["criteria"] if c["criterion_id"] == "R2.c")
    assert r2c["evidence"][0]["quote"] == "6295."


async def test_audits_the_dataset_as_json_body(client: httpx.AsyncClient, dataset: Dataset) -> None:
    response = await client.post("/v1/audits/dataset", json=_dataset_json(dataset))

    assert response.status_code == 200
    body = response.json()
    assert len(body["audits"]) == 20
    assert body["report"]["total_conversations"] == 20
    # C03 was configured to fail on the model side: degraded, not an error.
    assert body["report"]["fully_analyzed"] == 19
    c03 = next(a for a in body["audits"] if a["conversation_id"] == "C03")
    assert c03["analysis"] == "parcial"


async def test_audits_the_dataset_as_uploaded_file(
    client: httpx.AsyncClient, dataset: Dataset
) -> None:
    content = json.dumps(_dataset_json(dataset), ensure_ascii=False).encode()

    response = await client.post(
        "/v1/audits/dataset/file", files={"file": ("dataset.json", content, "application/json")}
    )

    assert response.status_code == 200
    assert len(response.json()["audits"]) == 20


async def test_every_audit_in_a_run_has_the_same_shape(
    client: httpx.AsyncClient, dataset: Dataset
) -> None:
    body = (await client.post("/v1/audits/dataset", json=_dataset_json(dataset))).json()

    shapes = {tuple(sorted(audit)) for audit in body["audits"]}
    criterion_shapes = {tuple(sorted(c)) for audit in body["audits"] for c in audit["criteria"]}
    assert len(shapes) == 1
    assert len(criterion_shapes) == 1


class TestErrors:
    async def test_invalid_body_returns_uniform_422(self, client: httpx.AsyncClient) -> None:
        response = await client.post("/v1/audits", json={"conversacion": {"id": "X"}})

        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "entrada_invalida"
        locations = {d["location"] for d in error["details"]}
        assert "body.conversacion.fecha_llamada" in locations

    async def test_file_that_is_not_json_returns_422(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/v1/audits/dataset/file", files={"file": ("x.json", b"not json", "application/json")}
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "archivo_invalido"

    async def test_oversized_file_returns_413(self, client: httpx.AsyncClient) -> None:
        content = b" " * (MAX_UPLOAD_BYTES + 1)

        response = await client.post(
            "/v1/audits/dataset/file", files={"file": ("x.json", content, "application/json")}
        )

        assert response.status_code == 413
        assert response.json()["error"]["code"] == "demasiado_grande"

    async def test_too_many_conversations_returns_413(
        self, client: httpx.AsyncClient, dataset: Dataset
    ) -> None:
        payload = _dataset_json(dataset)
        payload["conversaciones"] = payload["conversaciones"] * (
            MAX_CONVERSATIONS_PER_RUN // 20 + 1
        )

        response = await client.post("/v1/audits/dataset", json=payload)

        assert response.status_code == 413

    async def test_unknown_route_uses_the_same_shape(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/v1/nothing")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "no_encontrado"

    async def test_unexpected_errors_do_not_leak_internals(self, app: FastAPI) -> None:
        class ExplodingService:
            model_name = "x"

            async def audit_conversation(self, *_: object) -> None:
                raise RuntimeError("secret internal detail")

        app.state.audit_service = ExplodingService()
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/audits", json={"conversacion": SYNTHETIC_CONVERSATION}
            )

        assert response.status_code == 500
        assert response.json()["error"]["code"] == "error_interno"
        assert "secret" not in response.text


async def test_swagger_examples_are_valid_requests() -> None:
    app = create_app(settings=Settings(_env_file=None, llm_provider="none"))
    schema = app.openapi()
    examples = schema["paths"]["/v1/audits"]["post"]["requestBody"]["content"]["application/json"][
        "examples"
    ]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for example in examples.values():
            response = await client.post("/v1/audits", json=example["value"])
            assert response.status_code == 200, response.text


class TestReadEndpoints:
    async def test_a_posted_audit_can_be_read_back(
        self, client: httpx.AsyncClient, conversations: dict[str, Conversation]
    ) -> None:
        payload = {"conversacion": conversations["C20"].model_dump(mode="json", by_alias=True)}
        created = (await client.post("/v1/audits", json=payload)).json()

        response = await client.get(f"/v1/audits/{created['audit_id']}")

        assert response.status_code == 200
        assert response.json() == {**created, "persisted": True}

    async def test_a_dataset_run_can_be_read_back(
        self, client: httpx.AsyncClient, dataset: Dataset
    ) -> None:
        created = (await client.post("/v1/audits/dataset", json=_dataset_json(dataset))).json()
        assert created["persisted"] is True

        response = await client.get(f"/v1/reports/{created['run_id']}")

        assert response.status_code == 200
        assert response.json()["report"] == created["report"]
        assert [a["audit_id"] for a in response.json()["audits"]] == [
            a["audit_id"] for a in created["audits"]
        ]

    async def test_unknown_ids_return_404(self, client: httpx.AsyncClient) -> None:
        unknown = "00000000-0000-0000-0000-000000000000"
        for path in (f"/v1/audits/{unknown}", f"/v1/reports/{unknown}"):
            response = await client.get(path)
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "no_encontrado"

    async def test_malformed_id_returns_422(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/v1/audits/not-a-uuid")
        assert response.status_code == 422

    async def test_without_database_reads_return_503(self) -> None:
        app = create_app(settings=Settings(_env_file=None, llm_provider="none"))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            health = (await client.get("/health")).json()
            response = await client.get("/v1/audits/00000000-0000-0000-0000-000000000000")

        assert health["persistence"] == "deshabilitada"
        assert health["database"] == "no_configurada"
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "persistencia_no_disponible"

    async def test_database_down_still_audits_and_health_reports_it(
        self, conversations: dict[str, Conversation], golden_facts: dict[str, ConversationFacts]
    ) -> None:
        llm = GoldenLanguageModel(conversations, golden_facts)
        app = create_app(AuditService(FactExtractor(llm), BrokenAuditRepository()))
        transport = httpx.ASGITransport(app=app)
        payload = {"conversacion": conversations["C01"].model_dump(mode="json", by_alias=True)}
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            health = (await client.get("/health")).json()
            audit = await client.post("/v1/audits", json=payload)
            read = await client.get(f"/v1/audits/{audit.json()['audit_id']}")

        assert health["database"] == "error"
        assert audit.status_code == 200
        assert audit.json()["persisted"] is False
        assert read.status_code == 503
