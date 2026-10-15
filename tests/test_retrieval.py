import uuid

import pytest


@pytest.fixture
def processed_job(submit, run_worker):
    job_id = submit(
        [
            {"name": "Asha Rao", "email": "asha@example.com"},
            {"name": "Ravi Kumar", "email": "ravi@example.com"},
            {"name": "", "email": "broken"},
        ]
    ).json()["id"]
    run_worker()
    return job_id


def test_list_filters_by_status(client, processed_job):
    page = client.get(
        f"/api/v1/certificate-jobs/{processed_job}/certificates", params={"status": "SUCCEEDED"}
    ).json()

    assert page["total"] == 2
    assert {item["status"] for item in page["items"]} == {"SUCCEEDED"}


def test_list_paginates_in_row_order(client, processed_job):
    page = client.get(
        f"/api/v1/certificate-jobs/{processed_job}/certificates", params={"limit": 2, "offset": 1}
    ).json()

    assert page["total"] == 3
    assert [item["row_index"] for item in page["items"]] == [1, 2]


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"status": "NOPE"}]
)
def test_list_rejects_bad_query_params(client, processed_job, params):
    response = client.get(f"/api/v1/certificate-jobs/{processed_job}/certificates", params=params)

    assert response.status_code == 422


def test_certificate_detail_hides_internal_fields(client, processed_job):
    item = client.get(f"/api/v1/certificate-jobs/{processed_job}/certificates").json()["items"][0]
    detail = client.get(f"/api/v1/certificates/{item['id']}").json()

    assert detail["recipient_name"] == "Asha Rao"
    assert detail["certificate_number"].startswith("CERT-")
    for internal in ("attempts", "locked_at", "file_path"):
        assert internal not in detail


def test_download_pdf(client, processed_job):
    item = client.get(
        f"/api/v1/certificate-jobs/{processed_job}/certificates", params={"status": "SUCCEEDED"}
    ).json()["items"][0]

    response = client.get(f"/api/v1/certificates/{item['id']}/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert (
        f'filename="certificate-{item["certificate_number"]}.pdf"'
        in response.headers["content-disposition"]
    )
    assert response.content.startswith(b"%PDF-")


def test_pdf_of_pending_certificate_returns_409(client, submit):
    job_id = submit([{"name": "Asha Rao", "email": "asha@example.com"}]).json()["id"]
    item = client.get(f"/api/v1/certificate-jobs/{job_id}/certificates").json()["items"][0]

    response = client.get(f"/api/v1/certificates/{item['id']}/pdf")

    assert response.status_code == 409
    assert "PENDING" in response.json()["detail"]


def test_pdf_of_failed_certificate_returns_409(client, processed_job):
    item = client.get(
        f"/api/v1/certificate-jobs/{processed_job}/certificates", params={"status": "FAILED"}
    ).json()["items"][0]

    assert client.get(f"/api/v1/certificates/{item['id']}/pdf").status_code == 409


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/certificate-jobs/{id}",
        "/api/v1/certificate-jobs/{id}/certificates",
        "/api/v1/certificates/{id}",
        "/api/v1/certificates/{id}/pdf",
    ],
)
def test_unknown_ids_return_404(client, path):
    assert client.get(path.format(id=uuid.uuid4())).status_code == 404


def test_malformed_id_returns_422(client):
    assert client.get("/api/v1/certificates/not-a-uuid").status_code == 422
