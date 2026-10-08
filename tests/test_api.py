def test_login_required(client):
    assert client.get("/parties").status_code == 401


def test_first_user_becomes_owner(client):
    response = client.post("/auth/register", json={"username": "first", "password": "first-pass", "role": "staff"})
    assert response.json()["role"] == "owner"


def test_wrong_password_is_rejected(client, owner):
    response = client.post("/auth/token", data={"username": "owner1", "password": "wrong-pass"})
    assert response.status_code == 401


def test_staff_cannot_cancel_or_see_dues(client, staff, shop):
    invoice = client.post("/invoices", headers=staff, json={
        "party_id": shop["party_id"], "lines": [{"product_id": shop["car_battery"], "quantity": 1}],
    }).json()
    assert client.post(f"/invoices/{invoice['id']}/cancel", headers=staff).status_code == 403
    assert client.get("/outstanding", headers=staff).status_code == 403


def test_invoice_totals_match_real_bill(client, owner, shop):
    response = client.post("/invoices", headers=owner, json={
        "party_id": shop["party_id"],
        "lines": [{"product_id": shop["bike_battery"], "quantity": 8, "serials": [f"B{i}" for i in range(8)]}],
    })
    assert response.status_code == 201
    invoice = response.json()
    assert invoice["number"] == "LK-00001"
    assert invoice["net_payable"] == 1254300
    assert invoice["payment_status"] == "unpaid"


def test_same_battery_cannot_be_sold_twice(client, owner, shop):
    body = {"party_id": shop["party_id"], "lines": [{"product_id": shop["car_battery"], "quantity": 1, "serials": ["S1"]}]}
    assert client.post("/invoices", headers=owner, json=body).status_code == 201
    second = client.post("/invoices", headers=owner, json=body)
    assert second.status_code == 409
    assert "S1" in second.json()["detail"]


def test_cancelled_invoice_frees_its_serials(client, owner, shop):
    body = {"party_id": shop["party_id"], "lines": [{"product_id": shop["car_battery"], "quantity": 1, "serials": ["S1"]}]}
    first = client.post("/invoices", headers=owner, json=body).json()
    client.post(f"/invoices/{first['id']}/cancel", headers=owner)
    assert client.post("/invoices", headers=owner, json=body).status_code == 201


def test_part_payment_updates_balance(client, staff, shop):
    invoice = client.post("/invoices", headers=staff, json={
        "party_id": shop["party_id"], "lines": [{"product_id": shop["car_battery"], "quantity": 1}],
    }).json()
    paid = client.post(f"/invoices/{invoice['id']}/payments", headers=staff, json={"amount": 200000, "mode": "upi"}).json()
    assert paid["balance_due"] == 722500 - 200000
    assert paid["payment_status"] == "partly_paid"


def test_cannot_pay_more_than_due(client, owner, shop):
    invoice = client.post("/invoices", headers=owner, json={
        "party_id": shop["party_id"], "lines": [{"product_id": shop["car_battery"], "quantity": 1}],
    }).json()
    response = client.post(f"/invoices/{invoice['id']}/payments", headers=owner, json={"amount": 722501, "mode": "cash"})
    assert response.status_code == 422


def test_invoice_with_payments_cannot_be_cancelled(client, owner, shop):
    invoice = client.post("/invoices", headers=owner, json={
        "party_id": shop["party_id"], "pay_now": "cash",
        "lines": [{"product_id": shop["car_battery"], "quantity": 1}],
    }).json()
    assert invoice["payment_status"] == "paid"
    assert client.post(f"/invoices/{invoice['id']}/cancel", headers=owner).status_code == 409


def test_failed_invoice_saves_nothing(client, owner, shop):
    # The second line has a bad product, so the whole invoice must be rejected.
    response = client.post("/invoices", headers=owner, json={
        "party_id": shop["party_id"],
        "lines": [
            {"product_id": shop["car_battery"], "quantity": 1, "serials": ["S1"]},
            {"product_id": 999, "quantity": 1},
        ],
    })
    assert response.status_code == 404
    assert client.get("/invoices", headers=owner).json() == []