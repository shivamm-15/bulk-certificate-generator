import io
import re
import zipfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import services
from app.database import get_db
from app.models import Certificate, CertStatus, Job
from app.schemas import CertificateList, CertificateOut, JobCreate, JobOut

router = APIRouter(prefix="/api")


def _job_out(db: Session, job: Job) -> JobOut:
    c = services.job_counts(db, job.id)
    finished = c["succeeded"] + c["failed"]
    return JobOut(
        id=job.id,
        status=job.status,
        course_title=job.course_title,
        issuer_name=job.issuer_name,
        issue_date=job.issue_date,
        progress=round(finished / c["total"], 4) if c["total"] else 0.0,
        created_at=job.created_at,
        completed_at=job.completed_at,
        **c,
    )


def _cert_out(c: Certificate) -> CertificateOut:
    return CertificateOut(
        id=c.id,
        index=c.index,
        recipient_name=c.recipient_name,
        recipient_email=c.recipient_email,
        status=c.status,
        error=c.error,
        download_url=f"/api/certificates/{c.id}/download/" if c.status == CertStatus.COMPLETED else None,
    )


def _get_job_or_404(db: Session, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


def _slug(text: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text or "certificate").strip("_") or "certificate"


@router.post("/jobs/", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def create_job(payload: JobCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Submit a bulk generation request. Returns immediately; generation runs in the background."""
    job = services.create_job(db, payload)
    if job.status == "PENDING":  # at least one valid recipient to process
        background_tasks.add_task(services.process_job, job.id)
    return _job_out(db, job)


@router.get("/jobs/{job_id}/", response_model=JobOut)
def get_job(job_id: str, db: Session = Depends(get_db)):
    return _job_out(db, _get_job_or_404(db, job_id))


@router.get("/jobs/{job_id}/certificates/", response_model=CertificateList)
def list_certificates(
    job_id: str,
    status_filter: str | None = Query(None, alias="status", pattern="^(PENDING|COMPLETED|FAILED)$"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    _get_job_or_404(db, job_id)
    base = select(Certificate).where(Certificate.job_id == job_id)
    if status_filter:
        base = base.where(Certificate.status == status_filter)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.scalars(base.order_by(Certificate.index).limit(limit).offset(offset)).all()
    return CertificateList(total=total, limit=limit, offset=offset, items=[_cert_out(c) for c in rows])


@router.get("/certificates/{cert_id}/download/")
def download_certificate(cert_id: str, db: Session = Depends(get_db)):
    cert = db.get(Certificate, cert_id)
    if cert is None:
        raise HTTPException(404, "Certificate not found")
    if cert.status != CertStatus.COMPLETED or not cert.file_path or not Path(cert.file_path).exists():
        raise HTTPException(409, f"Certificate is not available (status: {cert.status})")
    return FileResponse(cert.file_path, media_type="application/pdf", filename=f"{_slug(cert.recipient_name)}.pdf")


@router.get("/jobs/{job_id}/download/")
def download_job_zip(job_id: str, db: Session = Depends(get_db)):
    """All successfully generated certificates of a job as one zip."""
    _get_job_or_404(db, job_id)
    certs = db.scalars(
        select(Certificate)
        .where(Certificate.job_id == job_id, Certificate.status == CertStatus.COMPLETED)
        .order_by(Certificate.index)
    ).all()
    if not certs:
        raise HTTPException(409, "No certificates are available for this job yet")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for c in certs:
            if c.file_path and Path(c.file_path).exists():
                zf.write(c.file_path, f"{c.index:04d}_{_slug(c.recipient_name)}.pdf")
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="job_{job_id}.zip"'},
    )
