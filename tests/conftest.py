import os
import tempfile

# Must be set BEFORE importing the app (settings are read at import time).
_TMP = tempfile.mkdtemp(prefix="certgen_tests_")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["CERT_STORAGE_DIR"] = f"{_TMP}/certs"
os.environ["MAX_RECIPIENTS"] = "50"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    # TestClient runs FastAPI background tasks before returning the response,
    # so the job is already finished when .post() returns.
    return TestClient(app)


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def make_payload(n=3, **overrides):
    payload = {
        "course_title": "Python for Beginners",
        "issuer_name": "Acme Academy",
        "issue_date": "2026-10-01",
        "recipients": [{"name": f"Person {i}", "email": f"person{i}@example.com"} for i in range(n)],
    }
    payload.update(overrides)
    return payload
