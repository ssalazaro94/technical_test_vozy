"""Ports: what the application needs from the outside world.

Adapters implement these protocols structurally (no inheritance), so the
domain and the use cases never import a vendor SDK.
"""

from typing import Protocol

from pydantic import BaseModel


class LanguageModelError(Exception):
    """The language model could not produce an answer: network, quota, timeout, disabled."""


class InvalidResponseError(LanguageModelError):
    """The language model answered, but not with a valid instance of the schema.

    Unlike transport errors, it is worth asking again with feedback.
    """


class StructuredLanguageModel(Protocol):
    """A language model that answers with an instance of a given Pydantic schema."""

    @property
    def model_name(self) -> str: ...

    async def generate[T: BaseModel](
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: type[T],
    ) -> T:
        """Return a validated `schema` instance or raise `LanguageModelError`."""
        ...
