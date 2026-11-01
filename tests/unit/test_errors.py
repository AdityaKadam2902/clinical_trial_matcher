from fastapi import FastAPI
from fastapi.testclient import TestClient

from clinical_trial_matcher.api.errors import AppError, NotFoundError, register_exception_handlers


def make_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/app-error")
    async def app_error():
        raise AppError("Expected failure", code="expected_failure", details={"reason": "test"})

    @app.get("/not-found")
    async def not_found():
        raise NotFoundError("Trial not found")

    @app.get("/unhandled")
    async def unhandled():
        raise RuntimeError("secret internal detail")

    return app


def test_app_error_contract():
    response = TestClient(make_app()).get("/app-error")
    assert response.status_code == 500
    body = response.json()["error"]
    assert body["code"] == "expected_failure"
    assert body["message"] == "Expected failure"
    assert body["details"] == {"reason": "test"}
    assert "request_id" in body


def test_not_found_contract():
    response = TestClient(make_app()).get("/not-found")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_unhandled_error_does_not_leak_details():
    response = TestClient(make_app(), raise_server_exceptions=False).get("/unhandled")
    assert response.status_code == 500
    body = response.json()["error"]
    assert body["code"] == "internal_error"
    assert "secret internal detail" not in body["message"]
