"""Job status / progress."""
from app import services
from app.schemas import JobCreate
from tests.conftest import make_payload


def test_status_before_processing_shows_pending_zero_progress(client, db):
    # Create the job but do NOT run the worker -> simulates "queued" state.
    job = services.create_job(db, JobCreate(**make_payload(4)))
    body = client.get(f"/api/jobs/{job.id}/").json()
    assert body["status"] == "PENDING"
    assert (body["pending"], body["succeeded"], body["failed"], body["progress"]) == (4, 0, 0, 0.0)


def test_progress_after_processing(client, db):
    job = services.create_job(db, JobCreate(**make_payload(4)))
    services.process_job(job.id)
    body = client.get(f"/api/jobs/{job.id}/").json()
    assert body["status"] == "COMPLETED" and body["progress"] == 1.0 and body["completed_at"]


def test_progress_is_partial_mid_run(client, db, monkeypatch):
    """Inspect the status from inside the worker, between certificates."""
    seen = []
    real = services.generate_certificate

    def spy(data, path):
        seen.append(client.get(f"/api/jobs/{job.id}/").json())
        real(data, path)

    monkeypatch.setattr(services, "generate_certificate", spy)
    job = services.create_job(db, JobCreate(**make_payload(3)))
    services.process_job(job.id)

    assert [s["status"] for s in seen] == ["PROCESSING"] * 3
    assert [s["succeeded"] for s in seen] == [0, 1, 2]
    assert seen[1]["progress"] == round(1 / 3, 4)


def test_unknown_job_404(client):
    assert client.get("/api/jobs/doesnotexist/").status_code == 404
    assert client.get("/api/jobs/doesnotexist/certificates/").status_code == 404
