"""A local task that works with structured data.

Celery serialises the arguments as JSON, so a pydantic model travels as a dict:
the client sends ``model_dump()`` and the task validates it with
``model_validate()``. The result is returned the same way.
"""

from pydantic import BaseModel, Field


class SummaryRequest(BaseModel):
    """What the client sends."""

    id: str = Field(max_length=150)
    text: str


class SummaryResponse(BaseModel):
    """What the task returns."""

    id: str
    words: int
    first_words: str


def summarize(args: list, kwargs: dict) -> dict:
    """Count the words of a text and return its first five."""
    request = SummaryRequest.model_validate(args[0])
    words = request.text.split()
    response = SummaryResponse(
        id=request.id,
        words=len(words),
        first_words=" ".join(words[:5]),
    )
    return response.model_dump()
