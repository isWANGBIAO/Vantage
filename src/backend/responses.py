"""HTTP representation helpers for the canonical API."""
from fastapi.responses import StreamingResponse


class NDJSONResponse(StreamingResponse):
    media_type = "application/x-ndjson"


def ndjson_openapi(item_model):
    """Describe the NDJSON wire body and its per-line type in OpenAPI 3.1."""
    return {"responses": {"200": {"content": {"application/x-ndjson": {
        "schema": None,
        "x-ndjson-item-schema": {"$ref": f"#/components/schemas/{item_model.__name__}"},
    }}}}}


async def configuration_read_error_response(_request, error):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=503, content={
        "code": "configuration_unreadable", "error": str(error), "original_preserved": True,
    })
