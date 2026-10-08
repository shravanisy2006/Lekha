import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from database import get_session
from main import app


@pytest.fixture
def client():
    """A test client backed by a fresh, empty in-memory database for every test."""
    engine = create_engine(
        "sqlite://",  # in memory: nothing is written to shop.db
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def get_test_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def login(client, username, password):
    response = client.post("/auth/token", data={"username": username, "password": password})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def owner(client):
    """Headers for a logged-in owner (the first user registered)."""
    client.post("/auth/register", json={"username": "owner1", "password": "owner-pass"})
    return login(client, "owner1", "owner-pass")


@pytest.fixture
def staff(client, owner):
    """Headers for a logged-in staff member."""
    client.post("/auth/register", headers=owner, json={"username": "raju", "password": "staff-pass", "role": "staff"})
    return login(client, "raju", "staff-pass")


@pytest.fixture
def shop(client, owner):
    """One customer and two products, matching the real bills."""
    client.post("/parties", headers=owner, json={"name": "Ravi Motors", "kind": "customer"})
    client.post("/products", headers=owner, json={
        "name": "Car battery 100Ah", "hsn_code": "85071000", "gst_percent": 18, "base_price": 612320,
    })
    client.post("/products", headers=owner, json={
        "name": "Bike battery 8Ah", "hsn_code": "85071000", "gst_percent": 18, "base_price": 132869,
    })
    return {"party_id": 1, "car_battery": 1, "bike_battery": 2}