"""A failure generating one certificate must not stop the rest."""
from app import services
from tests.conftest import make_payload


def test_single_generation_failure_is_isolated(client, monkeypatch):
    real = services.generate_certificate

    def flaky(data, path):
        if data.recipient_name == "Person 1":
            raise RuntimeError("disk exploded")
        real(data, path)

    monkeypatch.setattr(services, "generate_certificate", flaky)

    r = client.post("/api/jobs/", json=make_payload(4))
    job = client.get(f"/api/jobs/{r.json()['id']}/").json()

    assert job["status"] == "COMPLETED_WITH_ERRORS"
    assert (job["succeeded"], job["failed"]) == (3, 1)

    items = client.get(f"/api/jobs/{job['id']}/certificates/").json()["items"]
    failed = [i for i in items if i["status"] == "FAILED"]
    assert len(failed) == 1
    assert failed[0]["recipient_name"] == "Person 1"
    assert "disk exploded" in failed[0]["error"]
    assert failed[0]["download_url"] is None
    assert all(i["download_url"] for i in items if i["status"] == "COMPLETED")


def test_every_generation_failing_marks_job_failed(client, monkeypatch):
    def boom(data, path):
        raise RuntimeError("nope")

    monkeypatch.setattr(services, "generate_certificate", boom)
    job = client.get(f"/api/jobs/{client.post('/api/jobs/', json=make_payload(2)).json()['id']}/").json()
    assert job["status"] == "FAILED" and job["failed"] == 2


def test_job_does_not_stay_stuck_if_worker_crashes(client, db, monkeypatch):
    from app.schemas import JobCreate
    job = services.create_job(db, JobCreate(**make_payload(2)))

    def crash(*a, **k):
        raise RuntimeError("db went away")

    # Crash inside the worker's loop machinery (outside per-certificate try/except)
    monkeypatch.setattr(services, "select", crash)
    services.process_job(job.id)
    monkeypatch.undo()
    body = client.get(f"/api/jobs/{job.id}/").json()
    assert body["status"] != "PROCESSING"
