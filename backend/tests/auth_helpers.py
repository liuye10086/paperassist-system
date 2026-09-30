"""Real authentication support for isolated business integration tests."""
import os

SESSION_ENV = "PAPERASSIST_TEST_SESSION_COOKIE"


def login_test_client(client):
    from app.auth.service import create_user

    email = "business-test@paperassist.local"
    password = "isolated-test-password-2026"
    create_user(email, password)
    client.headers.update({"X-PaperAssist-Client": "web", "Origin": "http://testserver"})
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    assert client.cookies.get("paperassist_session")
    return client


def session_subprocess_env(client):
    """Transfer only this isolated test session without command-line credentials."""
    session = client.cookies.get("paperassist_session")
    assert session
    return {**os.environ, SESSION_ENV: session}
