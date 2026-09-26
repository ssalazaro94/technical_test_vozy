"""Input model: the agent specification and the calls to audit.

Python attributes are in English; aliases keep the Spanish keys of the
client's dataset, so the file is accepted exactly as it is delivered.
"""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class _InputModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, frozen=True, extra="ignore")


class Speaker(StrEnum):
    AGENT = "agente"
    CLIENT = "cliente"
    # Telephony events such as "[Llamada transferida a asesor humano]".
    SYSTEM = "sistema"


class Turn(_InputModel):
    speaker: Speaker = Field(alias="hablante")
    text: str = Field(alias="texto", min_length=1)


class CustomerRecord(_InputModel):
    name: str = Field(alias="nombre", min_length=1)
    document_last4: str = Field(alias="ultimos4_documento", pattern=r"^\d{4}$")
    product: str = Field(alias="producto", min_length=1)
    overdue_amount_cop: int = Field(alias="monto_vencido_cop", gt=0)
    due_date: date = Field(alias="fecha_vencimiento")


class Conversation(_InputModel):
    id: str = Field(min_length=1)
    call_date: date = Field(alias="fecha_llamada")
    customer: CustomerRecord = Field(alias="datos_cliente")
    transcript: tuple[Turn, ...] = Field(alias="transcripcion", min_length=1)

    def turns_by(self, speaker: Speaker) -> list[int]:
        return [index for index, turn in enumerate(self.transcript) if turn.speaker is speaker]

    def next_turn_by(self, speaker: Speaker, after: int) -> int | None:
        return next(
            (index for index in self.turns_by(speaker) if index > after),
            None,
        )


class AgentSpec(_InputModel):
    agent_name: str = Field(alias="nombre_agente")
    company: str = Field(alias="empresa")
    channel: str = Field(alias="canal")
    goal: str = Field(alias="objetivo")
    rules: tuple[str, ...] = Field(alias="reglas", min_length=1)


class Dataset(_InputModel):
    description: str | None = Field(default=None, alias="descripcion")
    agent_spec: AgentSpec = Field(alias="especificacion_agente")
    conversations: tuple[Conversation, ...] = Field(alias="conversaciones", min_length=1)
