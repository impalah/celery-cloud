from typing import Any, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class CeleryTaskResult(BaseModel):
    """Model for the result of a Celery task

    Args:
        BaseModel (_type_): _description_
    """

    status: str = Field(
        ...,
        json_schema_extra={"description": "Task Status", "example": "SUCCESS"},
    )

    result: Optional[Any] = Field(
        None,
        json_schema_extra={"description": "Task result", "example": 5},
    )

    traceback: Optional[str] = Field(
        None,
        json_schema_extra={
            "description": "Error traceback if the task failed",
            "example": None,
        },
    )

    children: List[Any] = Field(
        default_factory=list,
        json_schema_extra={"description": "List of children tasks", "example": []},
    )

    date_done: Optional[datetime] = Field(
        None,
        json_schema_extra={
            "description": "Finish data format ISO 8601",
            "example": "2025-03-11T09:56:48.043888+00:00",
        },
    )

    task_id: str = Field(
        ...,
        json_schema_extra={
            "description": "Unique task ID",
            "example": "84e50a89-92f9-4b97-95b5-eb4bad279205",
        },
    )
