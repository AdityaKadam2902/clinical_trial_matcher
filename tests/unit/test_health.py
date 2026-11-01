from fastapi.testclient import TestClient

from clinical_trial_matcher.main import create_app


def test_liveness_and_health():
    with TestClient(create_app()) as client:
        live = client.get("/api/v1/health/live")
        assert live.status_code == 200
        assert live.json()["status"] == "alive"

        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json()["environment"] == "test"


def test_request_id_is_generated_and_echoed():
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health/live")
        request_id = response.headers["x-request-id"]
        assert request_id
        assert len(request_id) == 32


def test_caller_supplied_request_id_is_preserved():
    with TestClient(create_app()) as client:
        response = client.get(
            "/api/v1/health/live",
            headers={"X-Request-ID": "client-request-123"},
        )
        assert response.headers["x-request-id"] == "client-request-123"


def test_security_headers_present():
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health/live")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"


def test_metrics_endpoint():
    with TestClient(create_app()) as client:
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]
