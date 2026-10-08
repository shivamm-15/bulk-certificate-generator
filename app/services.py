"""Business logic: job creation, validation and the background worker."""
import logging
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.generator import CertificateData, generate_certificate
from app.models import Certificate, CertStatus, Job, JobStatus
from app.schemas import JobCreate, RecipientIn

logger = logging.getLogger(__name__)


def _format_validation_error(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or 'recipient'}: {e['msg']}" for e in exc.errors()
    )


def create_job(db: Session, payload: JobCreate) -> Job:
    """Persist the job and one Certificate row per recipient.

    Each recipient is validated individually. Invalid ones are stored as FAILED
    with a reason (so the client can see exactly which rows were rejected);
    valid ones are stored as PENDING for the worker.
    """
    job = Job(
        course_title=payload.course_title.strip(),
        issuer_name=payload.issuer_name.strip(),
        issue_date=payload.issue_date,
    )
    seen_emails: set[str] = set()

    for idx, raw in enumerate(payload.recipients):
        cert = Certificate(index=idx)
        if isinstance(raw, dict):
            # Keep whatever we can for display, even if invalid.
            n, e = raw.get("name"), raw.get("email")
            cert.recipient_name = n[:200] if isinstance(n, str) else None
            cert.recipient_email = e[:320] if isinstance(e, str) else None
        try:
            if not isinstance(raw, dict):
                raise ValueError("recipient must be an object with 'name' and 'email'")
            rec = RecipientIn.model_validate(raw)
            if rec.email in seen_emails:
                raise ValueError(f"duplicate email in this job: {rec.email}")
            seen_emails.add(rec.email)
            cert.recipient_name, cert.recipient_email = rec.name, rec.email
            cert.status = CertStatus.PENDING
        except ValidationError as exc:
            cert.status, cert.error = CertStatus.FAILED, _format_validation_error(exc)
        except ValueError as exc:
            cert.status, cert.error = CertStatus.FAILED, str(exc)
        job.certificates.append(cert)

    db.add(job)
    db.flush()
    if not any(c.status == CertStatus.PENDING for c in job.certificates):
        _finalize(job)  # nothing to generate
    db.commit()
    return job


def _finalize(job: Job) -> None:
    ok = sum(1 for c in job.certificates if c.status == CertStatus.COMPLETED)
    bad = sum(1 for c in job.certificates if c.status == CertStatus.FAILED)
    if ok == 0:
        job.status = JobStatus.FAILED
    elif bad == 0:
        job.status = JobStatus.COMPLETED
    else:
        job.status = JobStatus.COMPLETED_WITH_ERRORS
    job.completed_at = datetime.now(timezone.utc)


def process_job(job_id: str) -> None:
    """Background worker. Uses its own DB session (the request's is closed by then).

    Every certificate is generated in its own try/except and committed
    individually: one failure never affects the others, and clients polling
    the status endpoint see live progress.
    """
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            logger.error("process_job: job %s not found", job_id)
            return
        job.status = JobStatus.PROCESSING
        db.commit()

        pending = db.scalars(
            select(Certificate)
            .where(Certificate.job_id == job_id, Certificate.status == CertStatus.PENDING)
            .order_by(Certificate.index)
        ).all()

        for cert in pending:
            try:
                path = settings.storage_dir / job_id / f"{cert.id}.pdf"
                generate_certificate(
                    CertificateData(
                        certificate_id=cert.id,
                        recipient_name=cert.recipient_name,
                        course_title=job.course_title,
                        issuer_name=job.issuer_name,
                        issue_date=job.issue_date,
                    ),
                    path,
                )
                cert.file_path, cert.status, cert.error = str(path), CertStatus.COMPLETED, None
            except Exception as exc:  # noqa: BLE001 - isolate any per-certificate failure
                logger.exception("Certificate %s failed", cert.id)
                cert.status, cert.error = CertStatus.FAILED, f"generation error: {exc}"
            db.commit()

        db.refresh(job)
        _finalize(job)
        db.commit()
    except Exception:  # job-level crash: don't leave it stuck in PROCESSING
        logger.exception("Job %s crashed", job_id)
        db.rollback()
        job = db.get(Job, job_id)
        if job:
            _finalize(job)
            db.commit()
    finally:
        db.close()


def job_counts(db: Session, job_id: str) -> dict[str, int]:
    rows = db.execute(
        select(Certificate.status, func.count()).where(Certificate.job_id == job_id).group_by(Certificate.status)
    ).all()
    by_status = {status: n for status, n in rows}
    succeeded = by_status.get(CertStatus.COMPLETED, 0)
    failed = by_status.get(CertStatus.FAILED, 0)
    pending = by_status.get(CertStatus.PENDING, 0)
    return {"total": succeeded + failed + pending, "succeeded": succeeded, "failed": failed, "pending": pending}
