"""Creating a job + input validation."""
from tests.conftest import make_payload


def test_create_job_returns_202_and_completes(client):
    r = client.post("/api/jobs/", json=make_payload(3))
    assert r.status_code == 202
    body = r.json()
    assert body["total"] == 3 and body["id"]

    final = client.get(f"/api/jobs/{body['id']}/").json()
    assert final["status"] == "COMPLETED"
    assert final["succeeded"] == 3 and final["failed"] == 0 and final["progress"] == 1.0


def test_issue_date_and_issuer_are_optional(client):
    r = client.post("/api/jobs/", json={"course_title": "X", "recipients": [{"name": "A", "email": "a@b.co"}]})
    assert r.status_code == 202


# ---- request-level validation (whole request rejected) ----
def test_missing_course_title_rejected(client):
    p = make_payload()
    del p["course_title"]
    assert client.post("/api/jobs/", json=p).status_code == 422


def test_empty_recipient_list_rejected(client):
    assert client.post("/api/jobs/", json=make_payload(0)).status_code == 422


def test_too_many_recipients_rejected(client):
    assert client.post("/api/jobs/", json=make_payload(51)).status_code == 422  # limit is 50 in tests


def test_bad_date_rejected(client):
    assert client.post("/api/jobs/", json=make_payload(issue_date="not-a-date")).status_code == 422


# ---- recipient-level validation (only that row fails) ----
def test_invalid_recipients_fail_individually_but_valid_ones_succeed(client):
    p = make_payload(
        0,
        recipients=[
            {"name": "Good One", "email": "good@example.com"},
            {"name": "", "email": "blank@example.com"},
            {"name": "No Email"},
            {"name": "Bad Email", "email": "nope"},
            "just a string",
            {"name": "Good Two", "email": "good2@example.com"},
        ],
    )
    r = client.post("/api/jobs/", json=p)
    assert r.status_code == 202
    job = client.get(f"/api/jobs/{r.json()['id']}/").json()
    assert job["status"] == "COMPLETED_WITH_ERRORS"
    assert (job["succeeded"], job["failed"], job["total"]) == (2, 4, 6)

    items = client.get(f"/api/jobs/{job['id']}/certificates/").json()["items"]
    assert [i["status"] for i in items] == ["COMPLETED", "FAILED", "FAILED", "FAILED", "FAILED", "COMPLETED"]
    assert "name" in items[1]["error"]
    assert "email" in items[2]["error"]
    assert "invalid email" in items[3]["error"]
    assert "object" in items[4]["error"]


def test_duplicate_email_in_same_job_is_rejected_for_second(client):
    p = make_payload(0, recipients=[
        {"name": "A", "email": "same@example.com"},
        {"name": "B", "email": "SAME@example.com"},
    ])
    job_id = client.post("/api/jobs/", json=p).json()["id"]
    items = client.get(f"/api/jobs/{job_id}/certificates/").json()["items"]
    assert items[0]["status"] == "COMPLETED"
    assert items[1]["status"] == "FAILED" and "duplicate" in items[1]["error"]


def test_all_invalid_recipients_marks_job_failed(client):
    p = make_payload(0, recipients=[{"name": "x"}, {"email": "y@z.co"}])
    r = client.post("/api/jobs/", json=p)
    assert r.status_code == 202
    body = client.get(f"/api/jobs/{r.json()['id']}/").json()
    assert body["status"] == "FAILED" and body["failed"] == 2 and body["succeeded"] == 0
