from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field

class SQSMessageAttributes(BaseModel):
    """Attributes of an AWS SQS message.

    Args:
        BaseModel (_type_): Pydantic base model.
    """

    ApproximateReceiveCount: str = Field(
        ...,
        json_schema_extra={
            "description": "Number of times the message has been received from the queue but not deleted.",
            "example": "1",
        },
    )

    SentTimestamp: str = Field(
        ...,
        json_schema_extra={
            "description": "Timestamp (in milliseconds) when the message was sent to the queue.",
            "example": "1523232000000",
        },
    )

    ApproximateFirstReceiveTimestamp: Optional[str] = Field(
        default=None,
        json_schema_extra={
            "description": "Timestamp (in milliseconds) when the message was first received from the queue.",
            "example": "1523232000001",
        },
    )


class SQSMessage(BaseModel):
    """Representation of an AWS SQS message.

    Args:
        BaseModel (_type_): Pydantic base model.
    """

    messageId: str = Field(
        ...,
        json_schema_extra={
            "description": "Unique identifier for the SQS message.",
            "example": "19dd0b57-b21e-4ac1-bd88-01bbb068cb78",
        },
    )

    receiptHandle: str = Field(
        ...,
        json_schema_extra={
            "description": "Token used to delete the message from the queue after processing.",
            "example": "MessageReceiptHandle",
        },
    )

    body: str = Field(
        ...,
        json_schema_extra={
            "description": "Message body containing the Celery task JSON.",
            "example": "{\"task\": \"tasks.sumar\", \"id\": \"4b8f27d1-cd8b-4b79-a1d5-937c5d3579d7\", \"args\": [10, 5], \"kwargs\": {}, \"retries\": 0, \"eta\": null}",
        },
    )

    attributes: SQSMessageAttributes = Field(
        ...,
        json_schema_extra={
            "description": "Metadata about the message provided by SQS.",
        },
    )

    eventSource: str = Field(
        ...,
        json_schema_extra={
            "description": "The AWS service from which the event originated.",
            "example": "aws:sqs",
        },
    )

    eventSourceARN: str = Field(
        ...,
        json_schema_extra={
            "description": "ARN of the SQS queue where the message was received.",
            "example": "arn:aws:sqs:us-east-1:123456789012:MyQueue",
        },
    )


class SQSEvent(BaseModel):
    """Representation of an AWS SQS event.

    Args:
        BaseModel (_type_): Pydantic base model.
    """

    Records: List[SQSMessage] = Field(
        ...,
        json_schema_extra={
            "description": "List of messages received in the SQS event.",
        },
    )
