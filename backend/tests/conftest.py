import os
os.environ["DATABASE_URL"] = "sqlite:///./test_phase1.db"
# Start every run from a fresh schema: create_all never alters a table left over from an older model.
from pathlib import Path
Path("test_phase1.db").unlink(missing_ok=True)
os.environ["SEED_DEMO"] = "false"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
