from datetime import timedelta

from pypdf import PdfReader
from sqlalchemy import func, select, update

from app.db import SessionLocal
from app.models import Certificate, CertificateStatus
from app.services import processing
from app.services.storage import absolute_path


def test_generates_a_pdf_for_each_valid_recipient(submit, run_worker):
    job_id = submit(
        [
            {"name": "Asha Rao", "email": "asha@example.com"},
            {"name": "Ravi Kumar", "email": "ravi@example.com"},
        ]
    ).json()["id"]

    assert run_worker() == 2

    with SessionLocal() as db:
        certs = db.scalars(select(Certificate).where(Certificate.job_id == job_id)).all()
    for cert in certs:
        assert cert.status == CertificateStatus.SUCCEEDED
        assert cert.certificate_number.startswith("CERT-")
        reader = PdfReader(absolute_path(cert.file_path))
        assert len(reader.pages) == 1
        text = reader.pages[0].extract_text()
        assert cert.recipient_name in text
        assert "Drone Mapping 101" in text
        assert cert.certificate_number in text


def test_job_progress_before_and_after_processing(client, submit, run_worker):
    job_id = submit(
        [
            {"name": "Asha Rao", "email": "asha@example.com"},
            {"name": "Ravi Kumar", "email": "ravi@example.com"},
            {"name": "", "email": "broken"},
        ]
    ).json()["id"]

    before = client.get(f"/api/v1/certificate-jobs/{job_id}").json()
    assert before["status"] == "PENDING"
    assert before["progress"] == {
        "total": 3,
        "pending": 2,
        "processing": 0,
        "succeeded": 0,
        "failed": 1,
    }

    run_worker()

    after = client.get(f"/api/v1/certificate-jobs/{job_id}").json()
    assert after["status"] == "PARTIALLY_FAILED"
    assert after["progress"] == {
        "total": 3,
        "pending": 0,
        "processing": 0,
        "succeeded": 2,
        "failed": 1,
    }
    assert after["started_at"] is not None
    assert after["completed_at"] is not None


def test_all_valid_rows_complete_the_job(client, submit, run_worker):
    job_id = submit([{"name": "Asha Rao", "email": "asha@example.com"}]).json()["id"]

    run_worker()

    assert client.get(f"/api/v1/certificate-jobs/{job_id}").json()["status"] == "COMPLETED"


def test_one_generation_failure_does_not_block_others(client, submit, run_worker, monkeypatch):
    real_render = processing.render_certificate_pdf

    def flaky_render(context, template_id="default_v1"):
        if context["recipient_name"] == "Boom":
            raise RuntimeError("renderer exploded")
        return real_render(context, template_id)

    monkeypatch.setattr(processing, "render_certificate_pdf", flaky_render)
    job_id = submit(
        [
            {"name": "Asha Rao", "email": "asha@example.com"},
            {"name": "Boom", "email": "boom@example.com"},
            {"name": "Ravi Kumar", "email": "ravi@example.com"},
        ]
    ).json()["id"]

    run_worker()

    job = client.get(f"/api/v1/certificate-jobs/{job_id}").json()
    assert job["status"] == "PARTIALLY_FAILED"
    assert job["progress"]["succeeded"] == 2
    assert job["progress"]["failed"] == 1

    failed = client.get(
        f"/api/v1/certificate-jobs/{job_id}/certificates", params={"status": "FAILED"}
    ).json()["items"]
    assert len(failed) == 1
    assert failed[0]["recipient_name"] == "Boom"
    assert failed[0]["error_code"] == "GENERATION_ERROR"
    assert "renderer exploded" in failed[0]["error_message"]


def test_job_fails_when_every_certificate_fails(client, submit, run_worker, monkeypatch):
    def broken_render(context, template_id="default_v1"):
        raise RuntimeError("renderer down")

    monkeypatch.setattr(processing, "render_certificate_pdf", broken_render)
    job_id = submit([{"name": "Asha Rao", "email": "asha@example.com"}]).json()["id"]

    run_worker()

    assert client.get(f"/api/v1/certificate-jobs/{job_id}").json()["status"] == "FAILED"


def test_concurrent_claims_never_overlap(submit):
    submit([{"name": f"P{i}", "email": f"p{i}@example.com"} for i in range(6)])

    with SessionLocal() as locker:
        locked = locker.scalars(
            select(Certificate.id).order_by(Certificate.row_index).limit(3).with_for_update()
        ).all()
        claimed = processing.claim_batch(SessionLocal, 10)

    assert len(claimed) == 3
    assert set(claimed).isdisjoint(locked)


def test_stale_leases_are_requeued_then_given_up(submit):
    submit(
        [
            {"name": "Retry Me", "email": "retry@example.com"},
            {"name": "Give Up", "email": "giveup@example.com"},
        ]
    )
    processing.claim_batch(SessionLocal, 10)

    with SessionLocal() as db:
        db.execute(update(Certificate).values(locked_at=func.now() - timedelta(minutes=10)))
        db.execute(
            update(Certificate).where(Certificate.recipient_name == "Give Up").values(attempts=3)
        )
        db.commit()

    processing.recover_stale(SessionLocal)

    with SessionLocal() as db:
        status = dict(db.execute(select(Certificate.recipient_name, Certificate.status)).all())
    assert status["Retry Me"] == CertificateStatus.PENDING
    assert status["Give Up"] == CertificateStatus.FAILED
