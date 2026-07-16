def test_create_service_201(client):
    resp = client.post(
        "/services", json={"name": "checkout-api", "owner_team": "payments"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert isinstance(body["id"], int)
    assert body["name"] == "checkout-api"
    assert body["owner_team"] == "payments"
    assert "created_at" in body and body["created_at"]


def test_create_service_duplicate_name_409(client):
    client.post("/services", json={"name": "checkout-api", "owner_team": "payments"})
    resp = client.post(
        "/services", json={"name": "checkout-api", "owner_team": "payments"}
    )
    assert resp.status_code == 409
    assert list(resp.json().keys()) == ["detail"]


def test_list_services_empty_returns_200(client):
    resp = client.get("/services")
    assert resp.status_code == 200
    assert resp.json() == []
