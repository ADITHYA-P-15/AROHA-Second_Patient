import os
os.environ["DATABASE_URL"] = "sqlite:///./test_phase1.db"
os.environ["SEED_DEMO"] = "false"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
