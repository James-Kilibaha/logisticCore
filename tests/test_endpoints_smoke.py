"""Kila GET isiyo na {param} inaitwa na mtumiaji wa kampuni: hakuna 500."""
import pytest

from logistic.app import app
from logistic.core import ratelimit

SKIP = ("/api/platform", "/docs", "/redoc", "/openapi", "/api/public/sms-dlr", "/api/public/whatsapp")


@pytest.fixture(scope="module")
def tenant_headers(client):
    ratelimit.reset()
    r = client.post("/api/public/signup", json={
        "companyName": "Gamma", "slug": "gamma", "phone": "0712000009",
        "admin": {"firstName": "G", "lastName": "M", "username": "boss", "password": "Siri12345"}})
    p = client.post("/api/platform/login", json={"username": "superadmin", "password": "Admin12345"}).json()
    client.put(f"/api/platform/companies/{r.json()['company']['id']}/approve", json={},
               headers={"Authorization": f"Bearer {p['access_token']}"})
    r = client.post("/api/login", json={"username": "boss", "password": "Siri12345"}, headers={"X-Company": "gamma"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}", "X-Company": "gamma"}


def test_all_simple_gets(client, tenant_headers):
    failures = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if "GET" not in getattr(route, "methods", set()) or "{" in path or path.startswith(SKIP):
            continue
        r = client.get(path, headers=tenant_headers)
        if r.status_code >= 500:
            failures.append((path, r.status_code, r.text[:200]))
    assert not failures, failures


def test_business_flow(client, tenant_headers):
    h = tenant_headers
    office = client.post("/api/settings/office-create", json={"name": "Kariakoo", "location": "Dar"}, headers=h)
    assert office.status_code == 201, office.text
    cust = client.post("/api/customer", json={"name": "Juma Ali", "phoneNumber": "0713000111"}, headers=h).json()
    inv = client.post("/api/invoice", json={"customer_id": cust["id"]}, headers=h)
    assert inv.status_code in (200, 201), inv.text
    inv2 = client.post("/api/invoice", json={"customer_id": cust["id"]}, headers=h)
    assert inv.json()["invoiceNumber"] != inv2.json()["invoiceNumber"]
    r = client.post("/api/invoice/search", json={"limit": 10}, headers=h)
    assert r.status_code == 200, r.text
    assert client.get("/api/dashboard/summary", headers=h).status_code == 200
