from datetime import datetime, timedelta, timezone

from app import models


def test_create_incident_201(client, sample_service):
    resp = client.post(
        "/incidents",
        json={
            "service_id": sample_service.id,
            "title": "Checkout 500s on card payments",
            "severity": "sev1",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "open"
    assert body["resolved_at"] is None
    assert body["service_id"] == sample_service.id


def test_create_incident_missing_service_404(client):
    resp = client.post(
        "/incidents",
        json={"service_id": 999999, "title": "orphan", "severity": "sev1"},
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Service 999999 not found"}


def test_create_incident_invalid_severity_422(client, sample_service):
    resp = client.post(
        "/incidents",
        json={
            "service_id": sample_service.id,
            "title": "Bad severity",
            "severity": "sev9",
        },
    )
    assert resp.status_code == 422
    body = resp.json()
    assert list(body.keys()) == ["detail"]
    assert isinstance(body["detail"], str)
    assert "severity" in body["detail"].lower()


def test_transition_unknown_incident(client):
    resp = client.patch("/incidents/999999/status", json={"status": "acknowledged"})
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Incident 999999 not found"}


def test_list_incidents_filter_and_paginate(client, db_session, sample_service):
    other_service = models.Service(name="auth-service", owner_team="identity")
    db_session.add(other_service)
    db_session.commit()
    db_session.refresh(other_service)

    # 3 open incidents on sample_service.
    for i in range(3):
        resp = client.post(
            "/incidents",
            json={
                "service_id": sample_service.id,
                "title": f"open incident {i}",
                "severity": "sev1",
            },
        )
        assert resp.status_code == 201

    # 1 non-open incident on a different service, to prove the filter excludes it.
    created = client.post(
        "/incidents",
        json={
            "service_id": other_service.id,
            "title": "will be acknowledged",
            "severity": "sev2",
        },
    ).json()
    ack_resp = client.patch(
        f"/incidents/{created['id']}/status", json={"status": "acknowledged"}
    )
    assert ack_resp.status_code == 200

    resp = client.get("/incidents", params={"status": "open", "limit": 2, "offset": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert len(body["items"]) == 2
    assert all(item["status"] == "open" for item in body["items"])


def test_list_incidents_invalid_limit_422(client):
    assert client.get("/incidents", params={"limit": 0}).status_code == 422
    assert client.get("/incidents", params={"limit": 101}).status_code == 422


def test_status_transition_happy_path(client, sample_service):
    created = client.post(
        "/incidents",
        json={
            "service_id": sample_service.id,
            "title": "lifecycle",
            "severity": "sev1",
        },
    ).json()
    incident_id = created["id"]

    r1 = client.patch(f"/incidents/{incident_id}/status", json={"status": "acknowledged"})
    assert r1.status_code == 200
    assert r1.json()["status"] == "acknowledged"

    r2 = client.patch(f"/incidents/{incident_id}/status", json={"status": "resolved"})
    assert r2.status_code == 200
    body = r2.json()
    assert body["status"] == "resolved"
    assert body["resolved_at"] is not None


def test_illegal_transition_409(client, sample_service):
    created = client.post(
        "/incidents",
        json={
            "service_id": sample_service.id,
            "title": "illegal jump",
            "severity": "sev2",
        },
    ).json()
    incident_id = created["id"]

    # open -> resolved directly is illegal.
    resp = client.patch(f"/incidents/{incident_id}/status", json={"status": "resolved"})
    assert resp.status_code == 409
    assert isinstance(resp.json()["detail"], str)

    # Row is unchanged after the failed call.
    listing = client.get("/incidents", params={"service_id": sample_service.id}).json()
    row = next(i for i in listing["items"] if i["id"] == incident_id)
    assert row["status"] == "open"

    # Drive it to resolved legally, then prove resolved -> open is also illegal.
    client.patch(f"/incidents/{incident_id}/status", json={"status": "acknowledged"})
    client.patch(f"/incidents/{incident_id}/status", json={"status": "resolved"})
    resp2 = client.patch(f"/incidents/{incident_id}/status", json={"status": "open"})
    assert resp2.status_code == 409


def test_service_stats_aggregation(client, db_session, sample_service):
    now = datetime.now(timezone.utc)

    open_incident = models.Incident(
        service_id=sample_service.id,
        title="open one",
        severity=models.SeverityEnum.sev1,
        status=models.StatusEnum.open,
        opened_at=now,
    )
    resolved_50min = models.Incident(
        service_id=sample_service.id,
        title="resolved in 50 min",
        severity=models.SeverityEnum.sev2,
        status=models.StatusEnum.resolved,
        opened_at=now - timedelta(minutes=100),
        resolved_at=now - timedelta(minutes=50),
    )
    resolved_100min = models.Incident(
        service_id=sample_service.id,
        title="resolved in 100 min",
        severity=models.SeverityEnum.sev3,
        status=models.StatusEnum.resolved,
        opened_at=now - timedelta(minutes=200),
        resolved_at=now - timedelta(minutes=100),
    )
    db_session.add_all([open_incident, resolved_50min, resolved_100min])
    db_session.commit()

    resp = client.get("/stats/services")
    assert resp.status_code == 200
    body = resp.json()
    entry = next(x for x in body if x["service_id"] == sample_service.id)
    assert entry["open_count"] == 1
    assert entry["mean_time_to_resolve_minutes"] == 75.0


def test_stats_service_with_no_incidents(client, db_session):
    empty_service = models.Service(name="idle-service", owner_team="platform")
    db_session.add(empty_service)
    db_session.commit()
    db_session.refresh(empty_service)

    resp = client.get("/stats/services")
    body = resp.json()
    entry = next(x for x in body if x["service_id"] == empty_service.id)
    assert entry["open_count"] == 0
    assert entry["mean_time_to_resolve_minutes"] is None
