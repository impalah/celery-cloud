"""A remote task: an ordinary Lambda function the runner invokes.

The runner calls it synchronously with ``{"args": [...], "kwargs": {...}}``. If
the response is a JSON object with a ``body`` key, ``body`` becomes the result of
the task *as it is* (it is not decoded, so return a number or an object, not a JSON
string); otherwise the whole response is the result.
"""


def lambda_handler(event: dict, context: object) -> dict:
    args = event.get("args", [])
    return {"statusCode": 200, "body": sum(args)}
