import pytest
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Certificate, CertificateJob


def count_rows(model) -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(model))


def test_create_job_returns_202_with_location_and_counts(submit):
    response = submit(
        [
            {"name": "Asha Rao", "email": "asha@example.com"},
            {"name": "Ravi Kumar", "email": "ravi@example.com"},
        ]
    )

    assert response.status_code == 202
    body = response.json()
    assert response.headers["location"] == f"/api/v1/certificate-jobs/{body['id']}"
    assert body["status"] == "PENDING"
    assert body["total_count"] == 2
    assert body["accepted_count"] == 2
    assert body["rejected_count"] == 0
    assert count_rows(Certificate) == 2


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            {"certificate": {"course_name": "X", "issued_on": "2026-10-01"}, "recipients": []},
            id="empty-recipients",
        ),
        pytest.param(
            {"recipients": [{"name": "A", "email": "a@example.com"}]}, id="missing-certificate"
        ),
        pytest.param(
            {
                "certificate": {"course_name": "", "issued_on": "2026-10-01"},
                "recipients": [{"name": "A", "email": "a@example.com"}],
            },
            id="blank-course",
        ),
        pytest.param(
            {
                "certificate": {"course_name": "X", "issued_on": "not-a-date"},
                "recipients": [{"name": "A", "email": "a@example.com"}],
            },
            id="bad-date",
        ),
        pytest.param(
            {
                "certificate": {"course_name": "X", "issued_on": "2026-10-01"},
                "recipients": "not-a-list",
            },
            id="recipients-not-list",
        ),
    ],
)
def test_structural_errors_reject_whole_request(client, body):
    response = client.post("/api/v1/certificate-jobs", json=body)

    assert response.status_code == 422
    assert count_rows(CertificateJob) == 0


def test_too_many_recipients_is_rejected(submit):
    recipients = [{"name": f"P{i}", "email": f"p{i}@example.com"} for i in range(1001)]

    assert submit(recipients).status_code == 422
    assert count_rows(CertificateJob) == 0


def test_invalid_rows_are_stored_as_failed_without_blocking_valid_rows(client, submit):
    response = submit(
        [
            {"name": "  Asha Rao ", "email": "Asha@Example.com"},
            {"name": "Asha Again", "email": "asha@example.COM"},
            {"name": "Bad Email", "email": "not-an-email"},
            {"name": 123, "email": "num@example.com"},
            "not-an-object",
        ]
    )
    body = response.json()
    assert body["accepted_count"] == 1
    assert body["rejected_count"] == 4

    items = client.get(f"/api/v1/certificate-jobs/{body['id']}/certificates").json()["items"]
    by_row = {item["row_index"]: item for item in items}

    assert by_row[0]["status"] == "PENDING"
    assert by_row[0]["recipient_name"] == "Asha Rao"
    assert by_row[0]["recipient_email"] == "asha@example.com"
    assert by_row[1]["error_code"] == "DUPLICATE_IN_JOB"
    assert "row 0" in by_row[1]["error_message"]
    assert by_row[2]["error_code"] == "VALIDATION_ERROR"
    assert by_row[2]["error_message"].startswith("email:")
    assert by_row[3]["error_code"] == "VALIDATION_ERROR"
    assert by_row[3]["recipient_name"] == "123"
    assert by_row[4]["error_code"] == "VALIDATION_ERROR"
    assert by_row[4]["recipient_name"] is None


def test_job_with_only_invalid_rows_fails_immediately(client, submit):
    body = submit([{"name": "", "email": "broken"}]).json()

    assert body["status"] == "FAILED"
    job = client.get(f"/api/v1/certificate-jobs/{body['id']}").json()
    assert job["status"] == "FAILED"
    assert job["completed_at"] is not None
