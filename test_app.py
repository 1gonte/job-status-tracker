from fastapi.testclient import TestClient
import pytest
import app_final

client = TestClient(app_final.app)

@pytest.fixture(autouse=True)
def reset_storage():
    app_final.jobs.clear()
    app_final.next_job_id = 1

def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_create_job_success():
    payload = {
        "name": "TEST",
        "author": "PYTEST"
    }
    
    response = client.post("/jobs", json=payload)

    assert response.status_code == 201

    new_job = response.json()
    
    assert new_job["id"] == 1
    assert new_job["name"] == payload["name"]
    assert new_job["author"] == payload["author"]
    assert new_job["status"] == "pending"
    assert new_job["category"] == "other"

def test_create_job_invalid_name():
    payload = {
            "name": "   ",
            "author": "PYTEST"
        }

    response = client.post("/jobs", json=payload)

    assert response.status_code == 422
    assert len(app_final.jobs) == 0

def test_forbidden_status_transition():
    
    create_job_response = client.post(
        "/jobs", json={
        "name": "TEST",
        "author": "PYTEST"
    })
    assert create_job_response.status_code == 201

    job_id = create_job_response.json()["id"]

    change_status_response = client.patch(
    f"/jobs/{job_id}/status",
    json={"status": "completed"}
    )
    assert change_status_response.status_code == 409

    get_job_response = client.get(f"/jobs/{job_id}")
    assert get_job_response.status_code == 200
    assert get_job_response.json()["status"] == "pending"

def test_successful_status_transitions():
    create_job_response = client.post(
            "/jobs", json={
            "name": "TEST",
            "author": "PYTEST"}
            )
    assert create_job_response.status_code == 201
    
    job_id = create_job_response.json()["id"]

    running_response = client.patch(
        f"/jobs/{job_id}/status",
        json={"status": "running"}
        )
    assert running_response.status_code == 200
    assert running_response.json()["status"] == "running"

    completed_response = client.patch(
        f"/jobs/{job_id}/status",
        json={"status": "completed"}
        )
    assert completed_response.status_code == 200
    assert completed_response.json()["status"] == "completed"

    get_job_response = client.get(f"/jobs/{job_id}")
    assert get_job_response.status_code == 200
    assert get_job_response.json()["status"] == "completed"

def test_stats(monkeypatch):
    monkeypatch.setattr(app_final, "max_jobs_value", 10)

    payloads = [
        {"name": "Job A", "author": "Alex", "category": "data_processing"},
        {"name": "Job B", "author": "Alex", "category": "ml_inference"},
        {"name": "Job C", "author": "Maria", "category": "data_processing"}
    ]

    job_ids = []

    for payload in payloads:
        response = client.post("/jobs", json=payload)
        assert response.status_code == 201
        job_ids.append(response.json()["id"])

    # Job B: pending -> running
    response = client.patch(
        f"/jobs/{job_ids[1]}/status",
        json={"status": "running"}
    )
    assert response.status_code == 200

    # Job C: pending -> running -> completed
    for status in ["running", "completed"]:
        response = client.patch(
            f"/jobs/{job_ids[2]}/status",
            json={"status": status}
        )
        assert response.status_code == 200

    response = client.get("/stats")
    assert response.status_code == 200

    expected = {
        "total_jobs": 3,
        "by_status": {
            "pending": 1,
            "running": 1,
            "completed": 1,
            "failed": 0
        },
        "by_category": {
            "data_processing": 2,
            "ml_inference": 1,
            "report_generation": 0,
            "other": 0
        },
        "by_author": {
            "Alex": 2,
            "Maria": 1
        }
    }

    assert response.json() == expected


def test_max_jobs_limit(monkeypatch):
    monkeypatch.setattr(app_final, "max_jobs_value", 2)

    payload = {
        "name": "Test Job",
        "author": "PYTEST"
    }

    for _ in range(2):
        response = client.post("/jobs", json=payload)
        assert response.status_code == 201

    response = client.post("/jobs", json=payload)
    assert response.status_code == 409

    assert len(app_final.jobs) == 2

    stats_response = client.get("/stats")
    assert stats_response.status_code == 200
    assert stats_response.json()["total_jobs"] == 2

    