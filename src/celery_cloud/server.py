from fastapi import FastAPI
import json
import debugpy

app = FastAPI()

debugpy.listen(("0.0.0.0", 5890))
print("Esperando conexión del depurador...")
debugpy.wait_for_client()


@app.post("/lambda")
async def run_lambda(event: dict):
    from celery_cloud.lambda_handler import lambda_handler  # Importa la función real

    response = lambda_handler(event, None)
    return response
