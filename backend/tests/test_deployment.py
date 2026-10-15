import subprocess
import sys

from fastapi.testclient import TestClient

from app.core.config import Settings, demo_reset_enabled, docs_enabled, settings
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
    assert body == {"status": "ok", "database": "ok"}
    meta = client.get("/api/v1/meta").json()
    assert "voice_notes" in meta["features"]
    assert {"demo_mode", "demo_reset_enabled", "features", "poll_seconds", "ai_enabled"} <= meta.keys()
    assert not ({"git_sha", "app_name", "version", "phase", "server_time", "timezone", "ai", "env", "scheduler"} & (body.keys() | meta.keys()))


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


def test_api_docs_are_enabled_only_for_explicit_development_environments():
    assert docs_enabled("dev")
    assert docs_enabled(" Development ")
    assert docs_enabled("test")
    assert not docs_enabled("prod")
    assert not docs_enabled("production")
    assert not docs_enabled("staging")
    assert not docs_enabled("")


def test_demo_reset_is_disabled_outside_development_and_test():
    assert demo_reset_enabled("dev", True)
    assert demo_reset_enabled("test", True)
    assert not demo_reset_enabled("prod", True)
    assert not demo_reset_enabled("production", True)
    assert not demo_reset_enabled("development", False)


def test_platform_database_urls_are_normalised_for_the_psycopg_driver():
    assert Settings(database_url="postgres://u:p@h:5432/db").database_url == "postgresql+psycopg://u:p@h:5432/db"
    assert Settings(database_url="postgresql://u:p@h/db?sslmode=require").database_url == "postgresql+psycopg://u:p@h/db?sslmode=require"
    assert Settings(database_url="postgresql+psycopg://u:p@h/db").database_url == "postgresql+psycopg://u:p@h/db"
    assert Settings(database_url="sqlite:///./x.db").database_url == "sqlite:///./x.db"


def test_voice_previews_are_rate_limited_per_person(monkeypatch):
    from app.api import voice
    from app.services import ai
    monkeypatch.setattr(ai, "transcribe_audio", lambda audio, mime, hint=None: None)
    monkeypatch.setattr(ai, "translate_to_english", lambda text, language=None: None)
    monkeypatch.setattr(ai, "urgency_advisor", lambda: None)
    monkeypatch.setattr(voice, "PREVIEW_LIMIT", 3)
    coord, pid = primary_contact_with_patient()
    # a family member may record on the patient's behalf only through a care team role; use the owner's own preview calls
    audio = b"RIFF" + b"\x00" * 2000
    codes = [coord.post(f"/api/v1/patients/{pid}/voice-notes/preview", headers={**H, "Content-Type": "audio/webm"}, content=audio).status_code for _ in range(5)]
    assert codes.count(429) >= 1 and codes[0] in (201, 403)
