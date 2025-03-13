# celery-cloud

Implementation of celery services using public cloud services.

- AWS: Lambda, SQS, SNS, DynamoDB.

## Launch test Project

Launch server

```powershell
$env:AWS_PROFILE="pak"; uv run celery-worker
```

Test client

```powershell
$env:AWS_PROFILE="pak"; uv run celery-worker
```

## Development notes

### Start project (uv)

```bash
uv init --no-readme
```

### Configure project as package

```ini
[project.scripts]
# Execute function "main" from package and main.py file
celery-cloud = "celery_cloud.main:main"
# Execute function "hello" from __init__.py
celery-cloud-hello = "celery_cloud:hello"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

### Launch project

```bash
uv run celery-cloud
```

### Get python local path

```bash
uv run python -c "import sys; print(sys.executable)"
```

## Step 1: Celery local worker

TODO

## Test: debug local lambda

Fastapi will be used as an interface to lambda. debugpy will be used to connect to VSCode.

Add dependencies using uv.

```bash
uv add --group dev fastapi uvicorn debugpy
```

Create launch.json to connect to the debugger

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Attach to FastAPI (uv)",
      "type": "python",
      "request": "attach",
      "connect": {
        "host": "localhost",
        "port": 5890
      },
      "pathMappings": [
        {
          "localRoot": "${workspaceFolder}",
          "remoteRoot": "${workspaceFolder}"
        }
      ]
    }
  ]
}
```

Launch uvicorn with the fastapi project

```bash
uv run uvicorn celery_cloud.server:app
```

From VSCode launch debugger "Attach to FastAPI (uv)".

Test the application.

```bash
curl -X POST "http://127.0.0.1:8000/lambda" -H "Content-Type: application/json" -d '{"key1": "value1"}'
```

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/lambda" -Method Post -Headers @{"Content-Type"="application/json"} -Body '{"key1": "value1"}'
```
