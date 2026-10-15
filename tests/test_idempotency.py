from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import CertificateJob
from app.services import jobs as jobs_service

RECIPIENTS = [{"name": "Asha Rao", "email": "asha@example.com"}]


def count_jobs() -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(CertificateJob))


def post_job(client, certificate_info, key, recipients=RECIPIENTS):
    return client.post(
        "/api/v1/certificate-jobs",
        json={"certificate": certificate_info, "recipients": recipients},
        headers={"Idempotency-Key": key},
    )


def test_same_key_returns_the_original_job(client, certificate_info):
    first = post_job(client, certificate_info, "order-42")
    second = post_job(client, certificate_info, "order-42")

    assert first.status_code == second.status_code == 202
    assert second.json()["id"] == first.json()["id"]
    assert second.headers["Idempotent-Replayed"] == "true"
    assert "Idempotent-Replayed" not in first.headers
    assert count_jobs() == 1


def test_same_key_with_a_different_body_is_rejected(client, certificate_info):
    post_job(client, certificate_info, "order-42")

    response = post_job(
        client, certificate_info, "order-42", [{"name": "Ravi", "email": "ravi@example.com"}]
    )

    assert response.status_code == 422
    assert count_jobs() == 1


def test_requests_without_a_key_always_create_new_jobs(submit):
    submit(RECIPIENTS)
    submit(RECIPIENTS)

    assert count_jobs() == 2


def test_concurrent_duplicate_is_resolved_by_the_unique_constraint(
    client, certificate_info, monkeypatch
):
    first = post_job(client, certificate_info, "order-42")

    # simulate the race: the second request checks before the first one is visible
    real_find = jobs_service.find_job_by_key
    calls = []

    def find_after_race(db, key):
        calls.append(key)
        return None if len(calls) == 1 else real_find(db, key)

    monkeypatch.setattr(jobs_service, "find_job_by_key", find_after_race)
    second = post_job(client, certificate_info, "order-42")

    assert second.status_code == 202
    assert second.json()["id"] == first.json()["id"]
    assert count_jobs() == 1
