"""Send and receive structured data (pydantic models travel as dicts)."""

import uuid

from celery_app import summarize
from pydantic import BaseModel


class SummaryRequest(BaseModel):
    id: str
    text: str


request = SummaryRequest(
    id=str(uuid.uuid4()),
    text="Serverless workers scale to zero when the queue is empty",
)

# Celery serialises with JSON: send model_dump(), receive a dict
result = summarize.apply_async(args=(request.model_dump(),))
response = result.get(timeout=60)
print(response)
# {'id': '...', 'words': 10, 'first_words': 'Serverless workers scale to zero'}
