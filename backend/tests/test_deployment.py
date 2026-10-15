import subprocess
import sys

from fastapi.testclient import TestClient

from app.core.config import Settings, settings
from app.main import app
from app.services.leader import scheduler_lease
from tests.helpers import H, account, primary_contact_with_patient

client = TestClient(app)


def test_feature_flags_parse_and_default_to_the_shipped_features():
    assert Settings(features="voice_notes, Insights").feature("insights") and not Settings(features="voice_notes").feature("insights")
    assert Settings(features="*").feature("anything_new") and not Settings(features="").feature("voice_notes")
    assert Settings().feature("voice_notes") and Settings().feature("insights") and Settings().feature("reminders")
    assert Settings(features="b,a").feature_list == ["a", "b"]


def test_a_feature_that_is_switched_off_disappears_and_comes_back(monkeypatch):
    coord, pid = primary_contact_with_patient()
    pro, _, _ = account("PROFESSIONAL")
    assert pro.get("/api/v1/insights/professional").status_code == 200
    assert coord.post(f"/api/v1/patients/{pid}/voice-notes/preview", headers={**H, "Content-Type": "audio/webm"}, content=b"x" * 2000).status_code != 404
    monkeypatch.setattr(settings, "features", "reminders")
    assert pro.get("/api/v1/insights/professional").status_code == 404
    assert coord.post(f"/api/v1/patients/{pid}/voice-notes/preview", headers={**H, "Content-Type": "audio/webm"}, content=b"x" * 2000).status_code == 404
    assert "insights" not in client.get("/api/v1/meta").json()["features"]
    monkeypatch.setattr(settings, "features", "voice_notes,insights,reminders")
    assert pro.get("/api/v1/insights/professional").status_code == 200


def test_health_reports_what_a_deployment_check_needs():
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["database"] == "ok" and "git_sha" in body and body["env"] and "scheduler" in body
    assert "voice_notes" in client.get("/api/v1/meta").json()["features"]


def test_only_one_holder_of_the_scheduler_lease_at_a_time_on_sqlite_it_is_always_granted():
    with scheduler_lease() as first:
        assert first is True
        with scheduler_lease() as second:
            assert second is True  # SQLite runs a single process, so there is nothing to contend with


def test_production_does_not_publish_the_api_docs():
    code = "from app.main import app; print(app.docs_url, app.openapi_url)"
    env = {"APP_ENV": "prod", "DATABASE_URL": "sqlite:///./test_prod_probe.db", "SEED_DEMO": "false", "SECRET_KEY": "x" * 40, "PATH": "/usr/bin:/bin", "PYTHONPATH": "."}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]), timeout=120)
    assert out.stdout.strip().endswith("None None"), out.stderr[-400:]
    dev = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**env, "APP_ENV": "dev"}, cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]), timeout=120)
    assert dev.stdout.strip() == "/docs /api/openapi.json", dev.stderr[-400:]
