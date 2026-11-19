import base64
import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from celery_cloud import serialization
from celery_cloud.entities.task import Task
from celery_cloud.exceptions import (
    EventDecodeException,
    MessageDecodeException,
    TaskDecodeException,
)


def _no_time_limit() -> list[float | None]:
    """Default value for the soft/hard time limits headers."""
    return [None, None]


class DeliveryInfo(BaseModel):
    """Delivery information for the SQS message."""

    exchange: str = Field(
        ...,
        json_schema_extra={"description": "Exchange used for message delivery."},
    )
    routing_key: str = Field(
        ..., json_schema_extra={"description": "Routing key used in SQS."}
    )


class Properties(BaseModel):
    """Properties of the SQS message."""

    correlation_id: str | None = Field(
        None, json_schema_extra={"description": "Correlation ID for the task."}
    )
    reply_to: str | None = Field(
        None, json_schema_extra={"description": "Reply queue identifier."}
    )
    delivery_mode: int | None = Field(
        None,
        json_schema_extra={"description": "Delivery mode (2 for persistent messages)."},
    )
    delivery_info: DeliveryInfo | None = Field(
        None, json_schema_extra={"description": "Message delivery details."}
    )
    priority: int | None = Field(
        None,
        json_schema_extra={"description": "Priority level of the message."},
    )
    body_encoding: str = Field(
        "base64",
        json_schema_extra={
            "description": "Encoding format of the message body (base64)."
        },
    )
    delivery_tag: str | None = Field(
        None,
        json_schema_extra={"description": "Unique delivery tag for the message."},
    )


class Headers(BaseModel):
    """Metadata headers for the Celery task."""

    lang: str = Field(
        ...,
        json_schema_extra={"description": "Programming language used (e.g., 'py')."},
    )
    task: str = Field(..., json_schema_extra={"description": "Celery task path."})
    id: str = Field(..., json_schema_extra={"description": "Unique task ID."})
    shadow: str | None = Field(
        None, json_schema_extra={"description": "Task shadow, if applicable."}
    )
    eta: str | None = Field(
        None, json_schema_extra={"description": "Estimated time of execution."}
    )
    expires: str | None = Field(
        None, json_schema_extra={"description": "Expiration date of the task."}
    )
    group: str | None = Field(
        None,
        json_schema_extra={"description": "Celery task group identifier."},
    )
    group_index: int | None = Field(
        None, json_schema_extra={"description": "Group index if applicable."}
    )
    compression: str | None = Field(
        None,
        json_schema_extra={
            "description": "Compression of the body (kombu content type, e.g. gzip)."
        },
    )
    retries: int = Field(
        0, json_schema_extra={"description": "Number of retries attempted."}
    )
    timelimit: list[float | None] = Field(
        default_factory=_no_time_limit,
        json_schema_extra={"description": "Execution time limits."},
    )
    root_id: str | None = Field(
        None, json_schema_extra={"description": "Root task ID."}
    )
    parent_id: str | None = Field(
        None, json_schema_extra={"description": "Parent task ID, if any."}
    )
    argsrepr: str | None = Field(
        None,
        json_schema_extra={
            "description": (
                "Truncated string representation of the positional arguments "
                "(for logs only, the real arguments travel in the body)."
            )
        },
    )
    kwargsrepr: str | None = Field(
        None,
        json_schema_extra={
            "description": (
                "Truncated string representation of the keyword arguments "
                "(for logs only, the real arguments travel in the body)."
            )
        },
    )
    origin: str | None = Field(
        None, json_schema_extra={"description": "Task origin (hostname)."}
    )
    ignore_result: bool = Field(
        False,
        json_schema_extra={
            "description": "Indicates whether the result should be ignored."
        },
    )
    replaced_task_nesting: int = Field(
        0,
        json_schema_extra={"description": "Nesting level of replaced tasks."},
    )
    stamped_headers: Any | None = Field(
        None,
        json_schema_extra={"description": "Stamped headers if available."},
    )
    stamps: dict[str, Any] = Field(
        default_factory=dict,
        json_schema_extra={"description": "Additional metadata about the task."},
    )


class SQSMessage(BaseModel):
    """Model representing an SQS message containing a Celery task."""

    body: str = Field(
        ..., json_schema_extra={"description": "Base64-encoded message body."}
    )
    content_encoding: str = Field(
        ...,
        json_schema_extra={"description": "Content encoding type (utf-8)."},
    )
    content_type: str = Field(
        ...,
        json_schema_extra={
            "description": "MIME type of the content (application/json)."
        },
    )
    headers: Headers = Field(
        ..., json_schema_extra={"description": "Celery task metadata headers."}
    )
    properties: Properties = Field(
        ..., json_schema_extra={"description": "Message properties from SQS."}
    )

    @classmethod
    def from_record(cls, record: "SQSRecord") -> "SQSMessage":
        """Build the message carried by an SQS record.

        Raises:
            MessageDecodeException: If the record body is not a valid Celery
                message envelope.
        """
        envelope = record.get_message()

        try:
            return cls(
                body=envelope["body"],
                content_encoding=envelope["content-encoding"],
                content_type=envelope["content-type"],
                headers=envelope["headers"],
                properties=envelope["properties"],
            )
        except KeyError as e:
            raise MessageDecodeException(
                message="Missing field in message", detail=str(e)
            ) from e
        except (TypeError, ValidationError) as e:
            raise MessageDecodeException(
                message="Invalid message format", detail=str(e)
            ) from e

    def decode_body(self) -> Any:
        """Decodes the message body into a Python object.

        For Celery protocol 2 with the JSON serializer this is
        ``[args, kwargs, embed]``.
        """
        if self.properties.body_encoding == "base64":
            raw = base64.b64decode(self.body)
        else:
            raw = self.body.encode("utf-8")
        raw = serialization.decompress(raw, self.headers.compression)
        return serialization.loads(raw, self.content_type)

    def get_task(self) -> Task:
        """Get the Celery Task carried by this message.

        The arguments are read from the message body, never from the
        ``argsrepr``/``kwargsrepr`` headers: those are truncated, log-oriented
        representations that cannot be trusted to rebuild the arguments.

        Raises:
            TaskDecodeException: If the body or headers are not a valid task.
        """

        if self.content_type.split(";")[0].strip() not in serialization.CONTENT_TYPES:
            raise TaskDecodeException(
                message="Unsupported content type", detail=self.content_type
            )

        try:
            body = self.decode_body()

            if not isinstance(body, list) or len(body) < 2:
                raise TaskDecodeException(
                    message="Invalid task body",
                    detail="expected a list [args, kwargs, embed]",
                )

            args, kwargs = body[0], body[1]
            embed = body[2] if len(body) > 2 and isinstance(body[2], dict) else {}

            # Celery protocol 2: timelimit = (time_limit, soft_time_limit)
            limits = [*self.headers.timelimit, None, None]
            hard_limit, soft_limit = limits[0], limits[1]

            return Task(
                id=self.headers.id,
                task=self.headers.task,
                args=args if args is not None else [],
                kwargs=kwargs if kwargs is not None else {},
                retries=self.headers.retries,
                eta=self.headers.eta,
                expires=self.headers.expires,
                ignore_result=self.headers.ignore_result,
                time_limit=hard_limit,
                soft_time_limit=soft_limit,
                queue=self.properties.delivery_info.routing_key
                if self.properties.delivery_info
                else None,
                parent_id=self.headers.parent_id,
                root_id=self.headers.root_id,
                group=self.headers.group,
                group_index=self.headers.group_index,
                callbacks=embed.get("callbacks") or None,
                errbacks=embed.get("errbacks") or None,
                chain=embed.get("chain") or None,
                chord=embed.get("chord") or None,
            )

        except TaskDecodeException:
            raise

        # ValidationError subclasses ValueError, so it must be caught first
        except ValidationError as e:
            raise TaskDecodeException(
                message="ValidationError getting task", detail=str(e)
            ) from e

        except serialization.SerializationError as e:
            raise TaskDecodeException(
                message="Error decoding task body", detail=str(e)
            ) from e

        except ValueError as e:
            # json.JSONDecodeError, invalid base64 and invalid utf-8 payloads
            raise TaskDecodeException(
                message="Error decoding task body", detail=str(e)
            ) from e

        except Exception as e:
            raise TaskDecodeException(
                message="Exception getting task", detail=str(e)
            ) from e


class SQSAttributes(BaseModel):
    """Metadata attributes of the SQS message."""

    ApproximateReceiveCount: str = Field(
        ...,
        json_schema_extra={
            "description": (
                "Number of times the message has been received but not deleted."
            )
        },
    )
    SentTimestamp: str = Field(
        ...,
        json_schema_extra={
            "description": (
                "Timestamp when the message was sent (milliseconds since epoch)."
            )
        },
    )
    ApproximateFirstReceiveTimestamp: str = Field(
        ...,
        json_schema_extra={
            "description": (
                "Timestamp when the message was first received "
                "(milliseconds since epoch)."
            )
        },
    )


class SQSRecord(BaseModel):
    """Model representing a single SQS message."""

    messageId: str = Field(
        ...,
        json_schema_extra={"description": "Unique identifier for the message."},
    )
    receiptHandle: str = Field(
        ...,
        json_schema_extra={
            "description": (
                "Receipt handle used for deleting or modifying the message."
            )
        },
    )
    body: str = Field(
        ...,
        json_schema_extra={
            "description": "Base64-encoded message body containing task data."
        },
    )
    attributes: SQSAttributes = Field(
        ...,
        json_schema_extra={"description": "Metadata attributes of the SQS message."},
    )
    eventSource: str = Field(
        ...,
        json_schema_extra={"description": "Source of the event (e.g., 'aws:sqs')."},
    )
    eventSourceARN: str = Field(
        ..., json_schema_extra={"description": "ARN of the SQS queue."}
    )

    def get_message(self) -> dict[str, Any]:
        """Decodes the base64-encoded body into a JSON dictionary.

        Raises:
            MessageDecodeException: If the body is not base64 encoded JSON object.
        """
        try:
            message = json.loads(base64.b64decode(self.body).decode("utf-8"))
        except ValueError as e:
            # json.JSONDecodeError, binascii.Error and UnicodeDecodeError
            raise MessageDecodeException(
                message="Error decoding message body", detail=str(e)
            ) from e

        if not isinstance(message, dict):
            raise MessageDecodeException(
                message="Error decoding message body",
                detail="the message is not a JSON object",
            )
        return message


class SQSEvent(BaseModel):
    """Representation of an AWS SQS event.

    Args:
        BaseModel (_type_): Pydantic base model.
    """

    Records: list[SQSRecord] = Field(
        ...,
        json_schema_extra={
            "description": "List of messages received in the SQS event.",
        },
    )

    @classmethod
    def from_lambda(cls, event: dict[str, Any]) -> "SQSEvent":
        """Get a SQSEvent from a lambda event

        Args:
            event (dict[str, Any]): Lambda event

        Returns:
            SQSEVent: Decoded event
        """

        try:
            # Validate the event with Pydantic
            sqs_event: SQSEvent = SQSEvent.model_validate(event)
            return sqs_event
        except ValidationError as e:
            raise EventDecodeException(
                message="Invalid SQS event format", detail=e.json()
            ) from e
        except Exception as e:
            raise EventDecodeException(
                message="Error decoding event", detail=str(e)
            ) from e
