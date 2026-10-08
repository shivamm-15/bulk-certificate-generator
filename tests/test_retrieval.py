"""Listing and downloading certificates."""
import io
import zipfile

from tests.conftest import make_payload


def _job(client, n=3, **kw):
    return client.post("/api/jobs/", json=make_payload(n, **kw)).json()["id"]


def test_list_certificates(client):
    job_id = _job(client, 3)
    body = client.get(f"/api/jobs/{job_id}/certificates/").json()
    assert body["total"] == 3
    assert [i["index"] for i in body["items"]] == [0, 1, 2]
    assert body["items"][0]["download_url"].startswith("/api/certificates/")


def test_filter_and_pagination(client):
    p = make_payload(0, recipients=[{"name": "A", "email": "a@x.co"}, {"name": "B"}, {"name": "C", "email": "c@x.co"}])
    job_id = client.post("/api/jobs/", json=p).json()["id"]
    failed = client.get(f"/api/jobs/{job_id}/certificates/?status=FAILED").json()
    assert failed["total"] == 1 and failed["items"][0]["index"] == 1
    page = client.get(f"/api/jobs/{job_id}/certificates/?limit=1&offset=1").json()
    assert page["total"] == 3 and len(page["items"]) == 1 and page["items"][0]["index"] == 1
    assert client.get(f"/api/jobs/{job_id}/certificates/?status=BOGUS").status_code == 422


def test_download_single_certificate_pdf(client):
    job_id = _job(client, 1)
    url = client.get(f"/api/jobs/{job_id}/certificates/").json()["items"][0]["download_url"]
    r = client.get(url)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert "Person_0.pdf" in r.headers["content-disposition"]


def test_download_failed_certificate_returns_409(client):
    p = make_payload(0, recipients=[{"name": "A"}])
    job_id = client.post("/api/jobs/", json=p).json()["id"]
    cert_id = client.get(f"/api/jobs/{job_id}/certificates/").json()["items"][0]["id"]
    assert client.get(f"/api/certificates/{cert_id}/download/").status_code == 409


def test_download_unknown_certificate_404(client):
    assert client.get("/api/certificates/nope/download/").status_code == 404


def test_zip_download_contains_only_successful(client):
    p = make_payload(0, recipients=[
        {"name": "Ann Lee", "email": "ann@x.co"}, {"name": "Bad"}, {"name": "Bob Ray", "email": "bob@x.co"}])
    job_id = client.post("/api/jobs/", json=p).json()["id"]
    r = client.get(f"/api/jobs/{job_id}/download/")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert names == ["0000_Ann_Lee.pdf", "0002_Bob_Ray.pdf"]


def test_zip_with_no_certificates_409(client):
    job_id = client.post("/api/jobs/", json=make_payload(0, recipients=[{"name": "x"}])).json()["id"]
    assert client.get(f"/api/jobs/{job_id}/download/").status_code == 409
