from fastapi.testclient import TestClient

from fastapi import FastAPI
from app.main import app as main_app

# Verify static route content here; authenticated navigation is tested separately.
app = FastAPI()
app.router.routes.extend(main_app.routes)

client = TestClient(app)


def test_root_serves_chat_page():
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")

    assert "/api/chat" in resp.text
    assert "session_id" in resp.text

    assert 'href="/admin"' not in resp.text


def test_admin_pages_are_reachable():

    for path, marker in (
        ("/admin", "/api/admin/overview"),
        ("/kb", "/api/kb/overview"),
        ("/rag-eval", "/api/rag-eval/overview"),
        ("/review", "/api/review/queue"),
        ("/observability", "/api/observability/overview"),
        ("/topics", "/api/topics/distribution"),
        ("/topics/questions", "/api/topics/questions"),
        ("/acceptance", "/api/acceptance/overview"),
        ("/acceptance/eval", "/api/acceptance/eval"),
        ("/acceptance/data", "/api/acceptance/data"),
        ("/acceptance/errors", "/api/acceptance/errors"),
    ):
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert marker in resp.text, path
        assert "/static/admin.js" in resp.text, path
    for asset in ("/static/admin.js", "/static/acceptance.js", "/static/acceptance.css"):
        assert client.get(asset).status_code == 200, asset
