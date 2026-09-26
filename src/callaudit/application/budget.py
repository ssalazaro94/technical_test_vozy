"""The service's own daily cap on language model calls: a spending guard.

The API is public. With a paid model, every new conversation someone sends is
billed, so the service itself enforces a maximum number of model calls per UTC
day, independent of the provider's quota. Cached conversations never reach the
model and consume nothing.

It fails closed: if the counter cannot be read, the model is not called. A
partial audit is a better outcome than uncontrolled spending.
"""

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime

from pydantic import BaseModel

from callaudit.application.ports import QuotaExhaustedError, StructuredLanguageModel, UsageCounter

logger = logging.getLogger(__name__)


def _utc_today() -> date:
    return datetime.now(UTC).date()


class DailyCallBudget:
    """Decorator over the model port: counts each call and stops above the daily limit."""

    def __init__(
        self,
        inner: StructuredLanguageModel,
        counter: UsageCounter,
        *,
        daily_limit: int,
        today: Callable[[], date] = _utc_today,
    ) -> None:
        self._inner = inner
        self._counter = counter
        self._daily_limit = daily_limit
        self._today = today

    @property
    def model_name(self) -> str:
        return self._inner.model_name

    async def generate[T: BaseModel](
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: type[T],
    ) -> T:
        try:
            used = await self._counter.increment(self._today())
        except Exception as exc:
            logger.error("usage counter unavailable, not calling the model: %r", exc)
            raise QuotaExhaustedError(
                "no se pudo verificar el presupuesto diario de llamadas al modelo; por seguridad "
                "no se llamó al modelo"
            ) from exc
        if used > self._daily_limit:
            raise QuotaExhaustedError(
                f"presupuesto diario del servicio agotado ({self._daily_limit} llamadas al "
                "modelo); se renueva a las 00:00 UTC. Las conversaciones ya analizadas siguen "
                "disponibles desde el caché"
            )
        return await self._inner.generate(
            system_prompt=system_prompt, user_prompt=user_prompt, schema=schema
        )
