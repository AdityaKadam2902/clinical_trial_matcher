from fastapi import FastAPI
from fastapi.testclient import TestClient

from clinical_trial_matcher.api.middleware import (
    MaxBodySizeMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)


def make_app(max_bytes: int = 16) -> FastAPI:
    app = FastAPI()

    @app.post("/echo")
    async def echo(payload: dict):
        return payload

    app.add_middleware(MaxBodySizeMiddleware, max_bytes=max_bytes)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)
    return app


def test_oversized_body_is_rejected():
    response = TestClient(make_app(max_bytes=16)).post("/echo", json={"value": "x" * 100})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"


def test_request_id_and_security_headers_on_rejection():
    response = TestClient(make_app(max_bytes=16)).post("/echo", json={"value": "x" * 100})
    assert response.headers["x-request-id"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_normal_request_passes():
    response = TestClient(make_app(max_bytes=1024)).post("/echo", json={"value": "ok"})
    assert response.status_code == 200
    assert response.json() == {"value": "ok"}
