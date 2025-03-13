import json

def lambda_handler(event, context):
    print("Evento recibido:", json.dumps(event, indent=2))
    return {
        "statusCode": 200,
        "body": json.dumps({"message": "Lambda ejecutada localmente"})
    }

