import os, json, base64
os.environ.update(CB_FAIL_MAX="3", MAX_ATTEMPTS="4", DEBUG_MODE="false", LOG_ENQUEUE="False", TASKS='{"t.fail":"task://nomod/f"}')
from celery_cloud.settings import settings
print("1 env types:", type(settings.CB_FAIL_MAX).__name__, type(settings.MAX_ATTEMPTS).__name__, "DEBUG_MODE=", repr(settings.DEBUG_MODE), "truthy:", bool(settings.DEBUG_MODE))
import pybreaker
b = pybreaker.CircuitBreaker(fail_max=settings.CB_FAIL_MAX, reset_timeout=1)
try:
    b.call(lambda: 1/0)
except Exception as e: print("   breaker with str fail_max ->", type(e).__name__, e)

# 2 handler on task failure
from unittest.mock import patch
from celery_cloud.runners import aws_lambda as al
def rec(i):
    inner = base64.b64encode(json.dumps([[1],{},{}]).encode()).decode()
    env = {"body": inner, "content-encoding":"utf-8","content-type":"application/json",
      "headers":{"lang":"py","task":"t.fail","id":f"id{i}","retries":0,"timelimit":[None,None],"root_id":f"id{i}","argsrepr":"(1,)","kwargsrepr":"{}","origin":"o","ignore_result":False,"replaced_task_nesting":0,"stamps":{}},
      "properties":{"correlation_id":"c","reply_to":"r","delivery_mode":2,"delivery_info":{"exchange":"","routing_key":"q"},"priority":0,"body_encoding":"base64","delivery_tag":"d"}}
    return {"messageId":f"m{i}","receiptHandle":"h","body":base64.b64encode(json.dumps(env).encode()).decode(),
      "attributes":{"ApproximateReceiveCount":"1","SentTimestamp":"1","ApproximateFirstReceiveTimestamp":"1"},"eventSource":"aws:sqs","eventSourceARN":"arn"}
calls=[]
with patch.object(al.TaskModel,"insert_task",side_effect=lambda task_uuid: calls.append(("insert",task_uuid))), \
     patch.object(al.TaskModel,"update_task",side_effect=lambda *a,**k: calls.append(("update",a,k))):
    r = al.lambda_handler({"Records":[rec(1),rec(2),rec(3)]}, None)
print("2 handler return on failing task:", r, "| backend calls:", calls)

# 3 get_task vs insert encoding
from celery_cloud.models.task_model import TaskModel
from unittest.mock import MagicMock
stored = json.dumps({"status":"SUCCESS"}).encode()   # what insert/update store
with patch.object(TaskModel,"get",return_value=MagicMock(result=stored,timestamp=1.0)):
    try: print("3", TaskModel.get_task("x"))
    except Exception as e: print("3 get_task on data written by update_task ->", type(e).__name__, e)

# 4 argsrepr truncation
from celery_cloud.entities.sqs_entities import SQSMessage
m = SQSMessage(**{k:v for k,v in json.loads(base64.b64decode(rec(1)["body"])).items() if k!="content-encoding" and k!="content-type"}, content_encoding="utf-8", content_type="application/json")
m.headers.argsrepr = "('" + "x"*1020 + "...)"
try: m.get_task()
except Exception as e: print("4 truncated argsrepr ->", type(e).__name__)
import datetime
m.headers.argsrepr = "(datetime.datetime(2025, 1, 1, 0, 0),)"
try: m.get_task()
except Exception as e: print("   non-literal repr ->", type(e).__name__)
print("5 exception str with no detail:", str(al.TaskExecutionException("boom")))
