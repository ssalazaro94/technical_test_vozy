"""A language model that always fails: the service runs on code-only criteria."""

from pydantic import BaseModel

from callaudit.application.ports import LanguageModelError


class DisabledLanguageModel:
    """Used when `LLM_PROVIDER=none` or no API key is configured.

    Every audit comes back with `analysis: "parcial"`: the code criteria are
    evaluated and the rest are "indeterminado". The service stays up.
    """

    def __init__(self, reason: str) -> None:
        self._reason = reason

    @property
    def model_name(self) -> str:
        return "ninguno"

    async def generate[T: BaseModel](
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: type[T],
    ) -> T:
        raise LanguageModelError(f"modelo de lenguaje deshabilitado: {self._reason}")
