"""Inspection helpers that support FastAPI's nested included-router structure."""


def iter_registered_routes(application_or_router):
    """Yield registered leaf routes across old and current FastAPI versions.

    These tests invoke legacy endpoints directly. HTTP/schema assertions should
    use TestClient/OpenAPI instead, so they also verify include-level metadata.
    """
    for route in application_or_router.routes:
        included_router = getattr(route, "original_router", None)
        if included_router is None:
            yield route
        else:
            yield from iter_registered_routes(included_router)
