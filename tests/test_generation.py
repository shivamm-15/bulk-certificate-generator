"""The PDF generator itself."""
from datetime import date

from app.generator import CertificateData, generate_certificate


def _data(name="Jane Doe", course="Intro to Testing"):
    return CertificateData("abc123", name, course, "Acme", date(2026, 10, 1))


def test_generates_valid_pdf(tmp_path):
    out = tmp_path / "sub" / "c.pdf"
    generate_certificate(_data(), out)
    content = out.read_bytes()
    assert content.startswith(b"%PDF") and len(content) > 1000
    assert not list(out.parent.glob("*.tmp"))  # temp file cleaned up


def test_contains_recipient_info_in_pdf(tmp_path):
    out = tmp_path / "c.pdf"
    generate_certificate(_data(name="Zaphod Beeblebrox"), out)
    # reportlab compresses streams by default; check the document title metadata (uncompressed).
    assert b"Zaphod Beeblebrox" in out.read_bytes()


def test_very_long_name_does_not_crash(tmp_path):
    out = tmp_path / "long.pdf"
    generate_certificate(_data(name="W" * 100, course="C" * 200), out)
    assert out.exists()


def test_job_generates_one_file_per_certificate(client):
    import os
    job_id = client.post("/api/jobs/", json={"course_title": "T", "recipients": [
        {"name": "A", "email": "a@x.co"}, {"name": "B", "email": "b@x.co"}]}).json()["id"]
    items = client.get(f"/api/jobs/{job_id}/certificates/").json()["items"]
    from app.database import SessionLocal
    from app.models import Certificate
    with SessionLocal() as s:
        paths = [s.get(Certificate, i["id"]).file_path for i in items]
    assert len(set(paths)) == 2 and all(os.path.exists(p) for p in paths)
