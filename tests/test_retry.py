from app.services import processing


def test_retry_regenerates_failed_certificates(client, submit, run_worker, monkeypatch):
    real_render = processing.render_certificate_pdf
    broken = {"Boom"}

    def flaky_render(context, template_id="default_v1"):
        if context["recipient_name"] in broken:
            raise RuntimeError("renderer exploded")
        return real_render(context, template_id)

    monkeypatch.setattr(processing, "render_certificate_pdf", flaky_render)
    job_id = submit(
        [
            {"name": "Asha Rao", "email": "asha@example.com"},
            {"name": "Boom", "email": "boom@example.com"},
            {"name": "", "email": "broken"},
        ]
    ).json()["id"]
    run_worker()
    assert client.get(f"/api/v1/certificate-jobs/{job_id}").json()["status"] == "PARTIALLY_FAILED"

    broken.clear()
    response = client.post(f"/api/v1/certificate-jobs/{job_id}/retry")

    assert response.status_code == 202
    assert response.json()["requeued_count"] == 1
    assert response.json()["status"] == "PROCESSING"

    run_worker()
    job = client.get(f"/api/v1/certificate-jobs/{job_id}").json()
    assert job["status"] == "PARTIALLY_FAILED"
    assert job["progress"]["succeeded"] == 2
    assert job["progress"]["failed"] == 1  # the invalid row is not retryable


def test_retry_without_generation_errors_returns_409(client, submit, run_worker):
    job_id = submit([{"name": "", "email": "broken"}, {"name": "A", "email": "a@x.com"}]).json()[
        "id"
    ]
    run_worker()

    response = client.post(f"/api/v1/certificate-jobs/{job_id}/retry")

    assert response.status_code == 409


def test_retry_of_unfinished_job_returns_409(client, submit):
    job_id = submit([{"name": "Asha Rao", "email": "asha@example.com"}]).json()["id"]

    response = client.post(f"/api/v1/certificate-jobs/{job_id}/retry")

    assert response.status_code == 409
