import pytest

from logistic.core import ratelimit


def _platform_headers(client):
    r = client.post("/api/platform/login", json={"username": "superadmin", "password": "Admin12345"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _signup(client, slug, username="admin", phone="0712000001", approve=True):
    r = client.post("/api/public/signup", json={
        "companyName": f"{slug.upper()} Logistics", "slug": slug, "phone": phone,
        "admin": {"firstName": "Asha", "lastName": "Juma", "username": username, "password": "Siri12345",
                  "phoneNumber": phone}})
    assert r.status_code == 201, r.text
    if approve:  # kampuni iliyojisajili inasubiri super admin aithibitishe
        cid = r.json()["company"]["id"]
        ok = client.put(f"/api/platform/companies/{cid}/approve", json={}, headers=_platform_headers(client))
        assert ok.status_code == 200, ok.text
    return r.json()


def _login(client, slug, username="admin", password="Siri12345"):
    r = client.post("/api/login", json={"username": username, "password": password}, headers={"X-Company": slug})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}", "X-Company": slug}


@pytest.fixture(scope="module")
def tenants(client):
    ratelimit.reset()
    _signup(client, "alpha", phone="0712000001")
    _signup(client, "beta", phone="0712000002")  # jina lile lile la mtumiaji "admin"
    return {"alpha": _login(client, "alpha"), "beta": _login(client, "beta")}


def test_branding_by_header_host_and_query(client, tenants):
    assert client.get("/api/public/branding", headers={"X-Company": "alpha"}).json()["slug"] == "alpha"
    assert client.get("/api/public/branding", headers={"Host": "beta.logistic.test"}).json()["slug"] == "beta"
    assert client.get("/api/public/branding?company=alpha").json()["name"] == "ALPHA Logistics"
    assert client.get("/api/public/branding").json()["resolved"] is False


def test_login_needs_company(client, tenants):
    r = client.post("/api/login", json={"username": "admin", "password": "Siri12345"})
    assert r.status_code == 400


def test_data_isolation(client, tenants):
    a, b = tenants["alpha"], tenants["beta"]
    r = client.post("/api/customer", json={"name": "Mteja Alpha", "phoneNumber": "0755111222"}, headers=a)
    assert r.status_code == 201, r.text
    # namba ile ile ya simu inaruhusiwa kampuni nyingine
    r = client.post("/api/customer", json={"name": "Mteja Beta", "phoneNumber": "0755111222"}, headers=b)
    assert r.status_code == 201, r.text
    names_a = [c["name"] for c in client.get("/api/customer", headers=a).json()]
    names_b = [c["name"] for c in client.get("/api/customer", headers=b).json()]
    assert names_a == ["Mteja Alpha"] and names_b == ["Mteja Beta"]
    # ndani ya kampuni moja bado ni ya kipekee
    r = client.post("/api/customer", json={"name": "Nakala", "phoneNumber": "0755111222"}, headers=a)
    assert r.status_code == 400


def test_token_cannot_cross_company(client, tenants):
    a = tenants["alpha"]
    r = client.get("/api/customer", headers={"Authorization": a["Authorization"], "X-Company": "beta"})
    # token inashinda header: bado ni alpha
    assert r.status_code == 200 and [c["name"] for c in r.json()] == ["Mteja Alpha"]
    r = client.get("/api/customer", headers={"Authorization": a["Authorization"], "Host": "beta.logistic.test"})
    assert [c["name"] for c in r.json()] == ["Mteja Alpha"]


def test_platform_token_not_valid_for_tenant(client, platform, tenants):
    r = client.get("/api/customer", headers={**platform, "X-Company": "alpha"})
    assert r.status_code == 401
    r = client.get("/api/platform/dashboard", headers={"Authorization": tenants["alpha"]["Authorization"]})
    assert r.status_code == 401


def test_company_profile_and_settings(client, tenants):
    a = tenants["alpha"]
    r = client.put("/api/company/settings", json={"values": {"DAYS_TO_CHARGE": "10", "SMS_SOURCE_NAME": "ALPHA"}},
                   headers=a)
    assert r.status_code == 200, r.text
    profile = client.get("/api/company", headers=a).json()
    assert profile["settings"]["values"]["DAYS_TO_CHARGE"] == 10
    assert profile["subscription"]["status"] == "TRIAL"
    r = client.put("/api/company/profile", json={"name": "Alpha Cargo", "primaryColor": "#0A7A3E"}, headers=a)
    assert r.status_code == 200
    assert client.get("/api/public/branding", headers={"X-Company": "alpha"}).json()["name"] == "Alpha Cargo"

    from logistic import config
    from logistic.core import tenant
    from logistic.saas.company.dao import CompanyDao
    from logistic.db import SessionLocal

    db = SessionLocal()
    alpha = CompanyDao(db).by_slug("alpha")
    beta = CompanyDao(db).by_slug("beta")
    db.close()
    with tenant.use_company(alpha.id):
        assert config.DAYS_TO_CHARGE == 10 and config.COMPANY_NAME == "Alpha Cargo"
        assert config.PUBLIC_TRACK_URL == "https://alpha.logistic.test/#/track"
    with tenant.use_company(beta.id):
        assert config.DAYS_TO_CHARGE == config.default("DAYS_TO_CHARGE")


def test_logo_upload_and_public(client, tenants):
    png = (b"\x89PNG\r\n\x1a\n" + b"0" * 100)
    r = client.post("/api/company/logo", files={"file": ("logo.png", png, "image/png")}, headers=tenants["alpha"])
    assert r.status_code == 200, r.text
    url = client.get("/api/public/branding", headers={"X-Company": "alpha"}).json()["logoUrl"]
    assert client.get(url).status_code == 200


def test_plan_module_gating(client, platform, tenants):
    # Starter haina QUOTE: alpha (trial ya Starter) inakataliwa 402
    r = client.post("/api/quotation/search", json={}, headers=tenants["alpha"])
    assert r.status_code == 402, r.text


def test_user_limit(client, tenants):
    a = tenants["alpha"]
    for i in range(2):  # Starter: watumiaji 3 (admin + 2)
        r = client.post("/api/user", json={"firstName": "U", "lastName": str(i), "username": f"user{i}",
                                           "password": "Siri12345"}, headers=a)
        assert r.status_code in (200, 201), r.text
    r = client.post("/api/user", json={"firstName": "U", "lastName": "x", "username": "user9",
                                       "password": "Siri12345"}, headers=a)
    assert r.status_code == 402


def test_expired_subscription_is_read_only(client, platform, tenants):
    from datetime import timedelta

    from logistic.core.base_model import utc_now
    from logistic.db import SessionLocal
    from logistic.saas.company.dao import CompanyDao
    from logistic.saas.subscription import service as subs
    from logistic.saas.subscription.model import Subscription

    db = SessionLocal()
    beta = CompanyDao(db).by_slug("beta")
    for s in db.query(Subscription).filter(Subscription.company_id == beta.id):
        s.startsAt = utc_now() - timedelta(days=40)
        s.endsAt = utc_now() - timedelta(days=20)
    db.commit()
    db.close()
    subs.invalidate()
    b = tenants["beta"]
    assert client.get("/api/customer", headers=b).status_code == 200            # kusoma kunaruhusiwa
    r = client.post("/api/customer", json={"name": "Mpya"}, headers=b)
    assert r.status_code == 402 and r.json()["code"] == "SUBSCRIPTION_EXPIRED"
    assert client.post("/api/customer/search", json={}, headers=b).status_code == 200

    # kampuni inatuma malipo -> wewe unathibitisha -> inafunguka
    plans = client.get("/api/public/plans").json()
    business = next(p for p in plans if p["code"] == "business")
    r = client.post("/api/company/subscription/payment", headers=b,
                    json={"plan_id": business["id"], "amount": 120000, "method": "M-PESA", "reference": "QWE123RTY"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    pending = client.get("/api/platform/subscriptions/payments?status=PENDING", headers=platform).json()
    assert any(p["id"] == pid and p["companySlug"] == "beta" for p in pending)
    r = client.put(f"/api/platform/subscriptions/payments/{pid}/confirm", json={}, headers=platform)
    assert r.status_code == 200 and r.json()["status"] == "CONFIRMED"
    assert client.post("/api/customer", json={"name": "Mpya"}, headers=b).status_code == 201
    st = client.get("/api/company/me", headers=b).json()["subscription"]
    assert st["status"] == "ACTIVE" and st["plan"]["code"] == "business"
    # Business ina QUOTE
    assert client.post("/api/quotation/search", json={}, headers=b).status_code == 200


def test_suspend_company(client, platform, tenants):
    company = client.get("/api/platform/companies?q=alpha", headers=platform).json()["items"][0]
    r = client.put("/api/platform/companies/status", json={"id": company["id"], "status": "SUSPENDED"}, headers=platform)
    assert r.status_code == 200
    assert client.get("/api/customer", headers=tenants["alpha"]).status_code == 403
    assert client.get("/api/public/branding", headers={"X-Company": "alpha"}).status_code == 200
    client.put("/api/platform/companies/status", json={"id": company["id"], "status": "ACTIVE"}, headers=platform)
    assert client.get("/api/customer", headers=tenants["alpha"]).status_code == 200


def test_platform_create_company_and_dashboard(client, platform):
    plans = client.get("/api/platform/plans", headers=platform).json()
    r = client.post("/api/platform/companies", headers=platform, json={
        "name": "YMG Logistics", "slug": "ymg", "domain": "https://ymg.co.tz/", "phone": "0670762229",
        "plan_id": next(p["id"] for p in plans if p["code"] == "enterprise"), "trialDays": 30,
        "admin": {"firstName": "James", "lastName": "K", "username": "james", "password": "Siri12345"}})
    assert r.status_code == 201, r.text
    assert r.json()["domain"] == "ymg.co.tz"
    assert client.get("/api/public/branding", headers={"Host": "ymg.co.tz"}).json()["slug"] == "ymg"
    h = _login(client, "ymg", "james")
    assert client.get("/api/customer", headers=h).json() == []
    detail = client.get(f"/api/platform/companies/{r.json()['id']}", headers=platform).json()
    assert detail["subscription"]["status"] == "TRIAL" and detail["users"][0]["username"] == "james"
    dash = client.get("/api/platform/dashboard", headers=platform).json()
    assert dash["companies"]["total"] >= 3
    # slug ikichukuliwa
    assert client.get("/api/public/company-check/ymg").json()["available"] is False


def test_unknown_company_sees_nothing(client):
    r = client.get("/api/public/track/ABCDEF")
    assert r.status_code == 404


def test_platform_swagger_token(client):
    r = client.post("/api/platform/token", data={"username": "superadmin", "password": "Admin12345"})
    assert r.status_code == 200 and r.json()["token_type"] == "bearer"
    me = client.get("/api/platform/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert me.json()["username"] == "superadmin"


def test_super_admin_sees_company_activity_and_views_read_only(client, platform, tenants):
    a = tenants["alpha"]
    client.post("/api/customer", json={"name": "Mteja wa Kufuatilia", "phoneNumber": "0755999000"}, headers=a)
    company = client.get("/api/platform/companies?q=alpha", headers=platform).json()["items"][0]

    ov = client.get(f"/api/platform/companies/{company['id']}/overview", headers=platform)
    assert ov.status_code == 200, ov.text
    assert ov.json()["counts"]["customers"] >= 2 and ov.json()["lastLogin"] is not None

    feed = client.get("/api/platform/activity?limit=200", headers=platform).json()
    assert any(r["companySlug"] == "alpha" for r in feed["items"])
    assert any(r["companySlug"] == "beta" for r in feed["items"])     # kampuni zote kwenye mlisho mmoja
    one = client.get(f"/api/platform/activity?company_id={company['id']}", headers=platform).json()
    assert all(r["companySlug"] == "alpha" for r in one["items"])
    assert client.get("/api/platform/activity/live", headers=platform).status_code == 200

    # kuangalia kama kampuni: anaona data yao yote ...
    r = client.post(f"/api/platform/companies/{company['id']}/impersonate", json={}, headers=platform)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["readOnly"] is True and body["refresh_token"] == ""
    view = {"Authorization": f"Bearer {body['access_token']}"}
    names = [c["name"] for c in client.get("/api/customer", headers=view).json()]
    assert "mteja wa kufuatilia" in [n.lower() for n in names]
    assert client.post("/api/customer/search", json={}, headers=view).status_code == 200   # kutafuta = kusoma
    # ... lakini hawezi kubadilisha chochote
    r = client.post("/api/customer", json={"name": "Hapana"}, headers=view)
    assert r.status_code == 403 and r.json()["code"] == "READ_ONLY_VIEW"
    # kampuni inaona kwenye audit log yao kwamba super admin aliangalia
    logs = client.post("/api/audit/search", json={"action": "VIEW_AS"}, headers=a)
    if logs.status_code == 200:  # (AUDIT inategemea mpango)
        assert logs.json()["total"] >= 1
    # token ya kuangalia haifanyi kazi kampuni nyingine wala platform
    assert client.get("/api/platform/dashboard", headers=view).status_code == 401


def test_super_admin_extra_users_beyond_plan(client, platform):
    ratelimit.reset()
    _signup(client, "delta", phone="0712000044")
    h = _login(client, "delta")
    for i in range(2):  # Starter: watumiaji 3 (admin + 2)
        assert client.post("/api/user", json={"firstName": "U", "lastName": str(i), "username": f"d{i}",
                                              "password": "Siri12345"}, headers=h).status_code in (200, 201)
    extra = {"firstName": "U", "lastName": "x", "username": "dx", "password": "Siri12345"}
    assert client.post("/api/user", json=extra, headers=h).status_code == 402        # kikomo cha mpango
    company = client.get("/api/platform/companies?q=delta", headers=platform).json()["items"][0]
    r = client.put(f"/api/platform/companies/{company['id']}/limits", json={"extraUsers": 2}, headers=platform)
    assert r.status_code == 200 and r.json()["extraUsers"] == 2
    st = client.get("/api/company/me", headers=h).json()["subscription"]
    assert st["plan"]["maxUsers"] == 5 and st["plan"]["planLimits"]["maxUsers"] == 3
    assert client.post("/api/user", json=extra, headers=h).status_code in (200, 201)   # sasa inaruhusiwa
    # kurudisha 0: kikomo cha mpango kinarudi
    client.put(f"/api/platform/companies/{company['id']}/limits", json={"extraUsers": 0}, headers=platform)
    extra["username"] = "dy"
    assert client.post("/api/user", json=extra, headers=h).status_code == 402


def test_page_views_and_full_view_as(client, platform):
    h = _login(client, "delta")
    assert client.post("/api/activity/view", json={"page": "invoices", "title": "Ankara"}, headers=h).json()["recorded"]
    assert not client.post("/api/activity/view", json={"page": "invoices"}, headers=h).json()["recorded"]  # papo hapo
    company = client.get("/api/platform/companies?q=delta", headers=platform).json()["items"][0]
    views = client.get(f"/api/platform/activity?company_id={company['id']}&kind=views", headers=platform).json()
    assert views["items"][0]["summary"] == "Amefungua: Ankara" and views["items"][0]["action"] == "VIEW"
    actions = client.get(f"/api/platform/activity?company_id={company['id']}&kind=actions", headers=platform).json()
    assert all(r["action"] != "VIEW" for r in actions["items"])

    # view-as kama mtumiaji asiye na ruhusa yoyote: bado anaona kila ukurasa (kusoma), hata moduli nje ya mpango
    users = client.get(f"/api/platform/companies/{company['id']}", headers=platform).json()["users"]
    plain = next(u for u in users if u["username"] == "d0")
    r = client.post(f"/api/platform/companies/{company['id']}/impersonate", json={"user_id": plain["id"]},
                    headers=platform)
    view = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/customer", headers=view).status_code == 200
    assert client.post("/api/quotation/search", json={}, headers=view).status_code == 200   # QUOTE haipo Starter
    assert client.post("/api/customer", json={"name": "X"}, headers=view).status_code == 403
    # kurasa anazofungua super admin hazihesabiwi kama za mtumiaji
    assert not client.post("/api/activity/view", json={"page": "reports"}, headers=view).json()["recorded"]



def test_signup_waits_for_super_admin_approval(client, platform):
    ratelimit.reset()
    res = _signup(client, "epsilon", phone="0712000055", approve=False)
    assert res["pending"] is True and res["company"]["status"] == "PENDING"
    r = client.post("/api/login", json={"username": "admin", "password": "Siri12345"}, headers={"X-Company": "epsilon"})
    assert r.status_code == 403 and r.json()["code"] == "COMPANY_PENDING"
    assert client.get("/api/public/branding", headers={"X-Company": "epsilon"}).json()["status"] == "PENDING"

    dash = client.get("/api/platform/dashboard", headers=platform).json()
    assert dash["companies"]["pending"] >= 1 and any(c["slug"] == "epsilon" for c in dash["awaitingApproval"])
    cid = res["company"]["id"]
    detail = client.get(f"/api/platform/companies/{cid}", headers=platform).json()
    assert detail["subscription"]["status"] == "NONE"            # majaribio hayajaanza bado

    r = client.put(f"/api/platform/companies/{cid}/approve", json={"trialDays": 30}, headers=platform)
    assert r.status_code == 200 and r.json()["status"] == "ACTIVE" and r.json()["approvedBy"] == "superadmin"
    h = _login(client, "epsilon")
    st = client.get("/api/company/me", headers=h).json()["subscription"]
    assert st["status"] == "TRIAL" and st["daysLeft"] >= 29
    assert client.put(f"/api/platform/companies/{cid}/approve", json={}, headers=platform).status_code == 400


def test_reject_signup_and_admin_created_is_active(client, platform):
    ratelimit.reset()
    res = _signup(client, "zeta", phone="0712000066", approve=False)
    cid = res["company"]["id"]
    r = client.put(f"/api/platform/companies/{cid}/reject", json={"reason": "Taarifa si sahihi"}, headers=platform)
    assert r.status_code == 200 and r.json()["status"] == "REJECTED"
    r = client.post("/api/login", json={"username": "admin", "password": "Siri12345"}, headers={"X-Company": "zeta"})
    assert r.status_code == 403 and r.json()["code"] == "COMPANY_REJECTED"
    # kampuni aliyoisajili super admin inafanya kazi papo hapo
    r = client.post("/api/platform/companies", headers=platform, json={
        "name": "Eta Cargo", "slug": "eta", "trialDays": 7,
        "admin": {"firstName": "E", "lastName": "T", "username": "boss", "password": "Siri12345"}})
    assert r.status_code == 201 and r.json()["status"] == "ACTIVE"
    assert client.post("/api/login", json={"username": "boss", "password": "Siri12345"},
                       headers={"X-Company": "eta"}).status_code == 200


def test_company_whatsapp_connection(client, platform, monkeypatch):
    import hashlib
    import hmac

    from logistic.saas.whatsapp import service as wa

    calls = []

    def fake_graph(path, token, params=None):
        calls.append((path, token))
        if token != "GOOD-TOKEN-123":
            from logistic.core.exceptions import BadRequest
            raise BadRequest("Meta imekataa: Invalid OAuth access token")
        if path.endswith("/message_templates"):
            return {"data": [{"name": "taarifa", "status": "APPROVED", "language": "sw", "category": "UTILITY",
                              "components": [{"type": "BODY"}]}]}
        return {"display_phone_number": "+255 712 000 077", "verified_name": "Theta Cargo", "quality_rating": "GREEN"}

    monkeypatch.setattr(wa, "_graph", fake_graph)
    ratelimit.reset()
    _signup(client, "theta", phone="0712000077")
    h = _login(client, "theta")
    company = client.get("/api/platform/companies?q=theta", headers=platform).json()["items"][0]
    # WHATSAPP haipo Starter: inaonekana lakini haiwezi kuunganishwa bila kupandisha mpango
    v = client.get("/api/company/whatsapp", headers=h).json()
    assert v["inPlan"] is False and v["connected"] is False and v["webhookUrl"].endswith("/webhook/theta")
    body = {"phoneNumberId": "1234567890", "accessToken": "GOOD-TOKEN-123", "businessAccountId": "999",
            "appSecret": "s3cret", "template": "taarifa"}
    assert client.put("/api/company/whatsapp", json=body, headers=h).status_code == 402
    plans = client.get("/api/platform/plans", headers=platform).json()
    client.put("/api/platform/subscriptions/change-plan", headers=platform,
               json={"company_id": company["id"], "plan_id": next(p["id"] for p in plans if p["code"] == "business")})

    bad = client.put("/api/company/whatsapp", json={**body, "accessToken": "WRONG-TOKEN-1"}, headers=h)
    assert bad.status_code == 400 and "Meta" in bad.json()["detail"]
    ok = client.put("/api/company/whatsapp", json=body, headers=h)
    assert ok.status_code == 200, ok.text
    v = ok.json()
    assert v["connected"] and v["status"]["verifiedName"] == "Theta Cargo" and v["accessToken"] == "••••••"
    # siri hazibadiliki zikitumwa kama "••••"
    again = client.put("/api/company/whatsapp", json={**body, "accessToken": "••••••", "appSecret": "••••••"}, headers=h)
    assert again.status_code == 200 and calls[-1][1] == "GOOD-TOKEN-123"
    assert client.get("/api/company/whatsapp/templates", headers=h).json()[0]["name"] == "taarifa"

    # webhook ya kampuni: verify token yake, sahihi ya app secret yake
    token = v["verifyToken"]
    r = client.get(f"/api/public/whatsapp/webhook/theta?hub.mode=subscribe&hub.verify_token={token}&hub.challenge=42")
    assert r.status_code == 200 and r.text == "42"
    assert client.get("/api/public/whatsapp/webhook/theta?hub.verify_token=nope&hub.challenge=1").status_code == 404
    raw = b'{"entry": []}'
    sig = "sha256=" + hmac.new(b"s3cret", raw, hashlib.sha256).hexdigest()
    assert client.post("/api/public/whatsapp/webhook/theta", content=raw,
                       headers={"x-hub-signature-256": sig, "content-type": "application/json"}).status_code == 200
    assert client.post("/api/public/whatsapp/webhook/theta", content=raw,
                       headers={"x-hub-signature-256": "sha256=bad"}).status_code == 404
    # super admin anaona hali ya WhatsApp ya kampuni
    detail = client.get(f"/api/platform/companies/{company['id']}", headers=platform).json()
    assert detail["whatsapp"]["ok"] is True and detail["whatsapp"]["displayPhone"] == "+255 712 000 077"
    # kuondoa muunganisho
    assert client.delete("/api/company/whatsapp", headers=h).json()["connected"] is False


def _company_by_slug(client, platform, slug):
    return client.get(f"/api/platform/companies?q={slug}", headers=platform).json()["items"][0]


def test_subscription_receipts_and_reminders(client, platform, monkeypatch):
    from logistic import config
    from logistic.core import mail, tenant
    from logistic.db import SessionLocal
    from logistic.saas.company.model import Company

    ratelimit.reset()
    _signup(client, "kappa", phone="0712000088")
    _signup(client, "lambda", phone="0712000089")
    h = _login(client, "kappa")
    other = _login(client, "lambda")
    company = _company_by_slug(client, platform, "kappa")
    plans = client.get("/api/platform/plans", headers=platform).json()
    plan_id = plans[0]["id"]

    sent = []
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(config, "SMTP_FROM", "billing@test.co.tz")
    monkeypatch.setattr(mail, "send", lambda to, subject, body, attachments=None, reply_to=None:
                        sent.append((to, subject, attachments)) or True)
    monkeypatch.setattr(mail, "send_later", lambda to, subject, body, attachments=None:
                        mail.send(to, subject, body, attachments))
    with tenant.system():
        db = SessionLocal()
        db.query(Company).filter(Company.slug == "kappa").update({Company.email: "ops@kappa.co.tz"})
        db.commit()
        db.close()

    # malipo yaliyorekodiwa na super admin: risiti (PDF) + email yenye risiti
    pay = client.post("/api/platform/subscriptions/payments", headers=platform, json={
        "company_id": company["id"], "plan_id": plan_id, "amount": 50000, "method": "M-PESA", "reference": "QWE123"})
    assert pay.status_code == 201, pay.text
    pid = pay.json()["id"]
    r = client.get(f"/api/platform/subscriptions/payments/{pid}/receipt", headers=platform)
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and r.headers["content-type"] == "application/pdf"
    assert client.get(f"/api/company/subscription/payments/{pid}/receipt", headers=h).content.startswith(b"%PDF")
    assert client.get(f"/api/company/subscription/payments/{pid}/receipt", headers=other).status_code == 404
    assert sent and sent[-1][0] == "ops@kappa.co.tz" and sent[-1][2][0][0].startswith("SUB-")

    # malipo yanayosubiri: hakuna risiti bado
    pending = client.post("/api/company/subscription/payment", headers=h, json={
        "plan_id": plan_id, "amount": 50000, "method": "M-PESA", "reference": "PENDING1"}).json()
    assert client.get(f"/api/company/subscription/payments/{pending['id']}/receipt", headers=h).status_code == 400

    # vikumbusho: vinatumwa mara moja tu kwa kila hatua (hata kazi ikiendeshwa tena)
    days = client.get("/api/company/subscription", headers=h).json()["state"]["daysLeft"]
    monkeypatch.setattr(config, "SUBSCRIPTION_REMIND_DAYS", [days])
    sent.clear()
    first = client.post("/api/platform/subscriptions/remind-now", headers=platform).json()
    assert "kappa" in [c["slug"] for c in first["companies"]]
    assert any(to == "ops@kappa.co.tz" for to, _, _ in sent)
    second = client.post("/api/platform/subscriptions/remind-now", headers=platform).json()
    assert "kappa" not in [c["slug"] for c in second["companies"]]


def test_platform_admin_forgot_password(client, platform, monkeypatch):
    from logistic.saas.admin import service as admin_service

    ratelimit.reset()
    created = client.post("/api/platform/admins", headers=platform, json={
        "username": "msaidizi", "password": "Msaidizi123", "fullName": "Msaidizi Wangu",
        "phone": "0712000099", "email": "msaidizi@test.co.tz"})
    assert created.status_code == 201, created.text
    codes = []
    monkeypatch.setattr(admin_service, "deliver_code",
                        lambda phone, email, text: codes.append(text) or [f"SMS {phone}", f"email {email}"])
    assert client.post("/api/platform/forgot", json={"username": "hayupo"}).status_code == 400
    r = client.post("/api/platform/forgot", json={"username": "+255712000099"})  # kwa namba ya simu
    assert r.status_code == 200, r.text
    token = r.json()["resetToken"]
    code = codes[-1].split("ni ")[1][:6]
    wrong = client.post("/api/platform/forgot/reset", json={"resetToken": token, "code": "000000" if code != "000000"
                                                            else "111111", "newPassword": "Mpya12345"})
    assert wrong.status_code == 400
    ok = client.post("/api/platform/forgot/reset", json={"resetToken": token, "code": code, "newPassword": "Mpya12345"})
    assert ok.status_code == 200 and ok.json()["username"] == "msaidizi"
    assert client.post("/api/platform/login", json={"username": "msaidizi", "password": "Mpya12345"}).status_code == 200
    # code moja haitumiki mara mbili
    assert client.post("/api/platform/forgot/reset",
                       json={"resetToken": token, "code": code, "newPassword": "Nyingine123"}).status_code == 400


def test_whatsapp_inbox_receives_and_replies(client, platform, monkeypatch):
    import hashlib
    import hmac
    import json
    import time

    from logistic.core import whatsapp as core_wa
    from logistic.saas.whatsapp import service as wa

    monkeypatch.setattr(wa, "_graph", lambda path, token, params=None: {"display_phone_number": "+255 712 000 066",
                                                                        "verified_name": "Iota", "quality_rating": "GREEN"})
    ratelimit.reset()
    _signup(client, "iota", phone="0712000066")
    h = _login(client, "iota")
    company = _company_by_slug(client, platform, "iota")
    plans = client.get("/api/platform/plans", headers=platform).json()
    client.put("/api/platform/subscriptions/change-plan", headers=platform,
               json={"company_id": company["id"], "plan_id": next(p["id"] for p in plans if p["code"] == "business")})
    assert client.put("/api/company/whatsapp", headers=h, json={
        "phoneNumberId": "1234567890", "accessToken": "GOOD-TOKEN-123", "appSecret": "iota-secret"}).status_code == 200

    def hook(payload):
        raw = json.dumps(payload).encode()
        sig = "sha256=" + hmac.new(b"iota-secret", raw, hashlib.sha256).hexdigest()
        return client.post("/api/public/whatsapp/webhook/iota", content=raw,
                           headers={"x-hub-signature-256": sig, "content-type": "application/json"})

    incoming = {"entry": [{"changes": [{"value": {
        "contacts": [{"wa_id": "255754111222", "profile": {"name": "Mteja Juma"}}],
        "messages": [{"from": "255754111222", "id": "wamid.IN1", "timestamp": str(int(time.time())), "type": "text",
                      "text": {"body": "Mzigo wangu umefika?"}}]}}]}]}
    assert hook(incoming).json()["received"] == 1
    assert hook(incoming).json()["received"] == 0  # Meta ikirudia - haurudiwi

    convs = client.get("/api/whatsapp/inbox", headers=h).json()
    assert convs[0]["phone"] == "+255754111222" and convs[0]["unread"] == 1 and convs[0]["windowOpen"] is True
    assert client.get("/api/whatsapp/inbox/unread", headers=h).json() == {"messages": 1, "conversations": 1}
    thread = client.get("/api/whatsapp/inbox/thread", params={"phone": "+255754111222"}, headers=h).json()
    assert thread["name"] == "Mteja Juma" and thread["messages"][0]["text"] == "Mzigo wangu umefika?"
    assert client.get("/api/whatsapp/inbox/unread", headers=h).json()["messages"] == 0

    sent = []
    monkeypatch.setattr(core_wa, "send_free_text", lambda phone, text: sent.append((phone, text)) or "wamid.OUT1")
    r = client.post("/api/whatsapp/inbox/reply", headers=h, json={"phone": "+255754111222", "text": "Ndiyo, umefika."})
    assert r.status_code == 200, r.text
    assert sent == [("+255754111222", "Ndiyo, umefika.")]
    hook({"entry": [{"changes": [{"value": {"statuses": [{"id": "wamid.OUT1", "status": "read"}]}}]}]})
    thread = client.get("/api/whatsapp/inbox/thread", params={"phone": "+255754111222"}, headers=h).json()
    assert [m["status"] for m in thread["messages"]] == ["RECEIVED", "READ"]

    # nje ya saa 24 bila template: inakataliwa kwa maelezo
    old = {"entry": [{"changes": [{"value": {"messages": [{"from": "255754999888", "id": "wamid.OLD",
                                                            "timestamp": str(int(time.time()) - 90000), "type": "text",
                                                            "text": {"body": "zamani"}}]}}]}]}
    hook(old)
    late = client.post("/api/whatsapp/inbox/reply", headers=h, json={"phone": "+255754999888", "text": "Habari"})
    assert late.status_code == 400 and "24" in late.json()["detail"]

    # kampuni nyingine haioni inbox hii
    ratelimit.reset()
    _signup(client, "omicron", phone="0712000067")
    o = _login(client, "omicron")
    client.put("/api/platform/subscriptions/change-plan", headers=platform,
               json={"company_id": _company_by_slug(client, platform, "omicron")["id"],
                     "plan_id": next(p["id"] for p in plans if p["code"] == "business")})
    assert client.get("/api/whatsapp/inbox", headers=o).json() == []


def test_popup_and_auto_sms_rules_are_per_company(client, tenants):
    a, b = tenants["alpha"], tenants["beta"]
    rules_a = client.get("/api/popup/rules", headers=a).json()
    assert {r["kind"] for r in rules_a} >= {"DEBTORS", "BOX_OPEN", "SMS_FAILED"}
    r = client.put("/api/popup/rules", headers=a, json=[{"kind": "DEBTORS", "afterDays": 9, "everyMinutes": 30}])
    assert r.status_code == 200, r.text
    debt_a = next(x for x in client.get("/api/popup/rules", headers=a).json() if x["kind"] == "DEBTORS")
    debt_b = next(x for x in client.get("/api/popup/rules", headers=b).json() if x["kind"] == "DEBTORS")
    assert (debt_a["afterDays"], debt_a["everyMinutes"]) == (9, 30) and debt_b["afterDays"] == 3
    assert client.get("/api/popup/due", headers=a).status_code == 200

    sms_a = client.get("/api/sms/auto-rules", headers=a).json()
    assert {r["kind"] for r in sms_a} == {"DEBT", "CREDIT", "STORAGE_WARN", "STORAGE_OVERDUE"}
    client.put("/api/sms/auto-rules", headers=a, json=[{"kind": "STORAGE_OVERDUE", "enabled": True, "hour": 14}])
    over_a = next(x for x in client.get("/api/sms/auto-rules", headers=a).json() if x["kind"] == "STORAGE_OVERDUE")
    over_b = next(x for x in client.get("/api/sms/auto-rules", headers=b).json() if x["kind"] == "STORAGE_OVERDUE")
    assert over_a["enabled"] is True and over_a["hour"] == 14 and over_b["enabled"] is False


def test_device_in_audit_and_my_activity(client, platform, tenants):
    ratelimit.reset()
    r = client.post("/api/login", json={"username": "admin", "password": "Siri12345"},
                    headers={"X-Company": "alpha", "X-Client": "android", "X-Device": "Samsung SM-A515F | Android 13"})
    assert r.status_code == 200
    h = {"Authorization": f"Bearer {r.json()['access_token']}", "X-Company": "alpha"}
    summary = client.get("/api/activity/summary", headers=h).json()
    assert summary["self"] is True and summary["logins"] >= 1
    assert any("SM-A515F" in (d["device"] or "") for d in summary["devices"])
    # super admin anaona kifaa kwenye shughuli za kampuni
    cid = _company_by_slug(client, platform, "alpha")["id"]
    rows = client.get(f"/api/platform/activity?company_id={cid}", headers=platform).json()["items"]
    assert any((row.get("device") or "").find("SM-A515F") >= 0 for row in rows)
    # njia ya zamani ya /api/activity/view bado inafanya kazi
    assert client.post("/api/activity/view", headers=h, json={"page": "invoices"}).status_code == 200


def test_platform_sms_balance_hidden_from_companies(client, platform, tenants):
    from logistic.core import tenant
    from logistic.sms import credit

    with tenant.system():
        credit.remember_gateway_balance(236250.0)  # jibu la FastHub kwa akaunti yako
    dash = client.get("/api/platform/dashboard", headers=platform).json()
    assert dash["platformSmsBalance"]["balance"] == 236250.0
    bal = client.get("/api/sms/balance", headers=tenants["alpha"]).json()
    assert bal["gateway"] is None and bal["balance"] != 236250.0


def test_staged_photo_is_per_company(client, tenants, monkeypatch, tmp_path):
    from logistic import config

    monkeypatch.setattr(config, "FILES_DIR", tmp_path)
    a, b = tenants["alpha"], tenants["beta"]
    jpg = b"\xff\xd8\xff\xe0" + b"0" * 200
    r = client.post("/api/product/photo/DAR-0001", headers=a, files={"file": ("p.jpg", jpg, "image/jpeg")})
    assert r.status_code == 200, r.text
    assert r.json()["staged"] is True
    assert client.get("/api/product/photo/DAR-0001/status", headers=a).json()["staged"] is True
    # kampuni nyingine yenye code ile ile haioni picha hii
    assert client.get("/api/product/photo/DAR-0001/status", headers=b).json()["staged"] is False
    assert client.get("/api/product/photo/DAR-0001/staged", headers=b).status_code == 404


def test_scheduler_jobs_run_for_every_company(client, tenants):
    from logistic.core import scheduler, tenant
    from logistic.sms import reminders

    for cid, slug in tenant.active_company_ids():  # moja kwa moja (bila kumeza makosa)
        with tenant.use_company(cid, slug):
            reminders.scheduled()
            scheduler.remove_old_images()


def test_track_number_uses_company_code(client, tenants):
    from logistic.core.utils import local_now

    day = f"{local_now():%y%m%d}"
    for slug in ("alpha", "beta"):
        h = tenants[slug]
        box = client.post("/api/package", headers=h, json={"packageType": "AIR"})
        assert box.status_code == 201, box.text
        bid = box.json()["id"]
        track = client.get(f"/api/package/{bid}/next-track", headers=h).json()
        assert track["generated"] is True and track["trackNumber"] == f"{slug.upper()}-A{day}-001"
        arr = client.get(f"/api/package/{bid}/arrivals", headers=h).json()
        assert arr["invoices"] == [] and arr["pending"] == 0
        assert client.get(f"/api/package/{bid}/arrivals.xlsx", headers=h).content[:2] == b"PK"
        # box ambalo halijapokelewa stoo: SMS za "mzigo umefika" hazitumwi
        assert client.post(f"/api/package/{bid}/notify-store", headers=h, json={}).status_code == 400
        # kampuni nyingine haioni box hili
        other = tenants["beta" if slug == "alpha" else "alpha"]
        assert client.get(f"/api/package/{bid}/arrivals", headers=other).status_code == 404


def test_sms_resend_and_gateway_response_hides_platform_balance(client, tenants, monkeypatch):
    import uuid

    from logistic import config
    from logistic.core import tenant
    from logistic.db import SessionLocal
    from logistic.sms import service as sms_service
    from logistic.sms.model import Sms

    class Fake:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = '{"status": true, "balance": 236250.5, "message": "Successfully submitted"}'

        def json(self):
            return {"status": True, "balance": 236250.5, "message": "Successfully submitted"}

    monkeypatch.setattr(config, "SMS_CLIENT_ID", "id")
    monkeypatch.setattr(config, "SMS_CLIENT_SECRET", "secret")
    monkeypatch.setattr(sms_service.requests, "post", lambda *a, **k: Fake())

    cid = None
    db = SessionLocal()
    with tenant.system():
        from logistic.saas.company.model import Company

        cid = db.query(Company.id).filter(Company.slug == "alpha").scalar()
    with tenant.use_company(cid, "alpha"):
        from logistic.user.model import User

        uid = db.query(User.id).first()[0]
        sms = Sms(id=uuid.uuid4(), logsId=uid, text="Mzigo umefika", msisdn="+255712000111", source="TEST",
                  reference="REF-0000000000000000001", coding="GSM7", smsFor="CUSTOM", isReceived=False,
                  isSMSSend=True, channel="SMS")
        db.add(sms)
        db.commit()
        sid = str(sms.id)
    db.close()

    r = client.post("/api/sms/resend", headers=tenants["alpha"], json={"id": sid, "msisdn": "0712000222"})
    assert r.status_code == 200, r.text
    copy = r.json()
    assert copy["msisdn"] == "+255712000222" and copy["text"] == "Mzigo umefika" and copy["isSMSSend"] is True
    # kampuni inayotumia akaunti yako: jibu la FastHub linahifadhiwa bila salio lako
    assert "Successfully submitted" in copy["gatewayResponse"] and "236250" not in copy["gatewayResponse"]
    assert copy.get("balanceAfter") is None
    # ujumbe wa awali unabaki
    assert client.post("/api/sms/resend", headers=tenants["beta"], json={"id": sid}).status_code == 404


def test_gateway_rejects_health_check_and_forces_https():
    from logistic.sms import service as sms_service

    class Health:
        status_code = 200
        text = '{"status": "ok", "message": "Health check successful. Use POST"}'

        def json(self):
            return {"status": "ok", "message": "Health check successful. Use POST"}

    assert sms_service._rejected(Health()) is True
    assert sms_service.gateway_url("http://bulksms.fasthub.co.tz/api/sms/send").startswith("https://")


def test_platform_two_factor_and_audit(client, platform, tenants):
    from logistic.core import totp

    ratelimit.reset()
    client.post("/api/platform/admins", headers=platform, json={
        "username": "mlinzi", "password": "Mlinzi12345", "fullName": "Mlinzi Wa Mfumo"})
    tok = client.post("/api/platform/login", json={"username": "mlinzi", "password": "Mlinzi12345"}).json()
    h = {"Authorization": f"Bearer {tok['access_token']}"}
    assert client.get("/api/platform/me/2fa", headers=h).json() == {"enabled": False, "recoveryLeft": 0}

    setup = client.post("/api/platform/me/2fa/setup", headers=h).json()
    assert setup["uri"].startswith("otpauth://totp/") and setup["secret"] in setup["uri"]
    assert client.post("/api/platform/me/2fa/enable", headers=h, json={"code": "000000"}).status_code == 400
    enabled = client.post("/api/platform/me/2fa/enable", headers=h,
                          json={"code": totp.now(setup["secret"])}).json()
    assert enabled["enabled"] is True and len(enabled["recoveryCodes"]) == 10

    # kuingia sasa kunahitaji hatua ya pili
    step1 = client.post("/api/platform/login", json={"username": "mlinzi", "password": "Mlinzi12345"}).json()
    assert step1["twoFactorRequired"] is True and step1["access_token"] == ""
    bad = client.post("/api/platform/login/2fa", json={"challenge": step1["challenge"], "code": "123456"})
    assert bad.status_code == 400
    # code ya app iliyotumika tayari wakati wa kuwasha haitumiki tena; code ya dharura inafanya kazi mara moja
    rc = enabled["recoveryCodes"][0]
    ok = client.post("/api/platform/login/2fa", json={"challenge": step1["challenge"], "code": rc})
    assert ok.status_code == 200 and ok.json()["access_token"]
    step1 = client.post("/api/platform/login", json={"username": "mlinzi", "password": "Mlinzi12345"}).json()
    assert client.post("/api/platform/login/2fa", json={"challenge": step1["challenge"], "code": rc}).status_code == 400
    assert client.get("/api/platform/me/2fa", headers=h).json()["recoveryLeft"] == 9

    # Swagger (/token) haipitishi akaunti yenye 2FA
    assert client.post("/api/platform/token", data={"username": "mlinzi", "password": "Mlinzi12345"}).status_code == 400

    # msimamizi mwingine anaweza kuondoa 2FA (simu imepotea)
    me = client.get("/api/platform/admins", headers=platform).json()
    mid = next(a["id"] for a in me if a["username"] == "mlinzi")
    assert client.post(f"/api/platform/admins/{mid}/reset-2fa", headers=platform).json() == {"ok": True}
    again = client.post("/api/platform/login", json={"username": "mlinzi", "password": "Mlinzi12345"}).json()
    assert again["access_token"] and again["twoFactorRequired"] is False

    # kumbukumbu: kuingia, 2FA, kuongeza msimamizi, kuondoa 2FA, na kitendo kwenye kampuni
    cid = _company_by_slug(client, platform, "alpha")["id"]
    client.put(f"/api/platform/companies/{cid}/limits", headers=platform, json={"extraUsers": 2})
    log = client.get("/api/platform/audit?size=200", headers=platform).json()["items"]
    actions = {x["action"] for x in log}
    assert {"LOGIN", "2FA_ENABLED", "LOGIN_2FA_FAILED", "ADMIN_CREATE", "2FA_RESET", "COMPANY_LIMITS"} <= actions
    limits = next(x for x in log if x["action"] == "COMPANY_LIMITS")
    assert limits["companyId"] == cid and limits["companySlug"] == "alpha" and '"extraUsers": 2' in limits["detail"]
    created = next(x for x in log if x["action"] == "ADMIN_CREATE")
    assert "Mlinzi12345" not in (created["detail"] or "") and '"password": "***"' in created["detail"]
    only = client.get(f"/api/platform/audit?company_id={cid}", headers=platform).json()["items"]
    assert only and all(x["companyId"] == cid for x in only)


def test_scheduler_runs_on_one_worker_only(client, monkeypatch):
    from logistic.core import scheduler as sch

    class FakeScheduler:
        started = 0

        def start(self):
            FakeScheduler.started += 1

        def shutdown(self, wait=False):
            pass

        def get_jobs(self):
            return []

    monkeypatch.setattr(sch, "_build", lambda: FakeScheduler())
    first = sch._Handle()
    first.begin()
    assert sch._LEADER["role"] == "leader" and FakeScheduler.started == 1
    lock_conn = sch._LEADER["conn"]
    # worker wa pili (connection nyingine ya database): hapati lock, haendeshi kazi
    sch._LEADER.update(conn=None, role="none")
    second = sch._Handle()
    second.begin()
    assert sch._LEADER["role"] == "follower" and FakeScheduler.started == 1
    # wa kwanza akizima, wa pili anachukua nafasi
    lock_conn.close()
    assert sch._try_lead() is True
    second._run()
    assert FakeScheduler.started == 2
    first._stop.set()
    second.shutdown()


def test_company_data_export(client, platform, tenants, monkeypatch, tmp_path):
    import io
    import json
    import zipfile

    from logistic import config

    monkeypatch.setattr(config, "FILES_DIR", tmp_path)
    a = tenants["alpha"]
    jpg = b"\xff\xd8\xff\xe0" + b"0" * 200
    client.post("/api/product/photo/EXP-0001", headers=a, files={"file": ("p.jpg", jpg, "image/jpeg")})
    client.post("/api/package", headers=a, json={"packageType": "AIR"})

    r = client.get("/api/company/export", headers=a)
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert "SOMA.txt" in names and "company.json" in names and "data/users.json" in names
    assert "data/users.csv" in names and "data/packages.json" in names
    assert any(n.startswith("files/") and n.endswith(".jpg") for n in names)
    users = json.loads(z.read("data/users.json"))
    assert users and all("password" not in u for u in users)
    # data ya kampuni nyingine haimo
    alpha_id = _company_by_slug(client, platform, "alpha")["id"]
    for name in names:
        if name.startswith("data/") and name.endswith(".json"):
            assert all(row.get("company_id") == alpha_id for row in json.loads(z.read(name)))
    company = json.loads(z.read("company.json"))
    assert company["slug"] == "alpha"

    # super admin anaweza kupakua (na inarekodiwa)
    r = client.get(f"/api/platform/companies/{alpha_id}/export", headers=platform)
    assert r.status_code == 200 and zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    log = client.get(f"/api/platform/audit?company_id={alpha_id}&action=COMPANY_EXPORT", headers=platform).json()
    assert log["total"] >= 1


class _FakeAzam:
    """AzamPay bandia: token + checkout; inarekodi maombi."""

    def __init__(self):
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None, **_):
        self.calls.append((url, json, headers))

        class R:
            status_code = 200
            text = ""

            def __init__(self, body):
                self._body = body

            def json(self):
                return self._body

        if url.endswith("/AppRegistration/GenerateToken"):
            if json.get("clientSecret") == "bad":
                r = R({"success": False, "message": "Invalid detail"})
                r.status_code = 423
                return r
            return R({"data": {"accessToken": "tok-123", "expire": "x"}, "success": True})
        return R({"success": True, "transactionId": "AZ-TX-1", "message": "Request in progress"})


def _invoice_with_debt(slug, amount=50000.0):
    import uuid

    from logistic.core import tenant
    from logistic.customer.model import Customer
    from logistic.db import SessionLocal
    from logistic.invoice.model import Invoice
    from logistic.payment.model import Debt
    from logistic.saas.company.model import Company
    from logistic.user.model import User

    db = SessionLocal()
    with tenant.system():
        cid = db.query(Company.id).filter(Company.slug == slug).scalar()
    with tenant.use_company(cid, slug):
        uid = db.query(User.id).first()[0]
        customer = Customer(id=uuid.uuid4(), name="Juma Mteja", phoneNumber=f"+2557540{uuid.uuid4().int % 100000:05d}",
                            active=1, logsId=uid)
        db.add(customer)
        db.flush()
        invoice = Invoice(id=uuid.uuid4(), invoiceNumber=f"INV-{uuid.uuid4().hex[:6]}", status="STORE",
                          history="-", customer_id=customer.id, logsId=uid)
        db.add(invoice)
        db.flush()
        debt = Debt(id=uuid.uuid4(), amount=amount, debt=amount, paid=0, status="OPEN", invoice_id=invoice.id,
                    logsId=uid)
        db.add(debt)
        db.commit()
        out = (str(debt.id), str(invoice.id), customer.phoneNumber)
    db.close()
    return out


def test_online_payment_invoice_azampay(client, platform, tenants, monkeypatch):
    from logistic.onlinepay import azampay, service as op

    fake = _FakeAzam()
    monkeypatch.setattr(azampay.requests, "post", fake.post)
    azampay._TOKENS.clear()
    a, b = tenants["alpha"], tenants["beta"]

    # bila akaunti ya AzamPay: hakuna malipo ya simu
    debt_id, invoice_id, phone = _invoice_with_debt("alpha")
    assert client.post("/api/online-pay/invoice", headers=a, json={"debtId": debt_id}).status_code == 400

    bad = client.put("/api/online-pay/settings", headers=a, json={
        "appName": "Alpha", "clientId": "alpha-client", "clientSecret": "bad"})
    assert bad.status_code == 400 and "AzamPay" in bad.json()["detail"]
    view = client.put("/api/online-pay/settings", headers=a, json={
        "appName": "Alpha", "clientId": "alpha-client", "clientSecret": "s3cret", "apiKey": "api-key-1"}).json()
    assert view["connected"] is True and view["clientSecret"] == op.MASK and "/api/public/payments/azampay/alpha/" in view["callbackUrl"]
    # siri iliyofichwa ikitumwa tena haibadiliki
    client.put("/api/online-pay/settings", headers=a, json={
        "appName": "Alpha", "clientId": "alpha-client", "clientSecret": op.MASK, "apiKey": op.MASK})
    assert fake.calls[-1][1]["clientSecret"] == "s3cret"

    started = client.post("/api/online-pay/invoice", headers=a, json={"debtId": debt_id, "provider": "M-Pesa",
                                                                       "amount": 20000})
    assert started.status_code == 200, started.text
    pay = started.json()
    assert pay["status"] == "PENDING" and pay["provider"] == "Mpesa" and pay["msisdn"] == phone
    url, body, headers = fake.calls[-1]
    assert url.endswith("/azampay/mno/checkout") and body["amount"] == "20000" and body["externalId"] == pay["externalId"]
    assert headers["Authorization"] == "Bearer tok-123" and headers["X-API-Key"] == "api-key-1"
    assert body["accountNumber"] == phone.lstrip("+")

    # callback: token isiyo sahihi -> 404; kampuni nyingine haioni malipo haya
    callback_path = view["callbackUrl"][view["callbackUrl"].index("/api/public"):]
    assert client.post("/api/public/payments/azampay/alpha/wrong", json={}).status_code == 404
    assert client.get(f"/api/online-pay/{pay['id']}", headers=b).status_code == 404
    ok = client.post(callback_path, json={"utilityref": pay["externalId"], "transactionstatus": "success",
                                          "amount": "20000", "reference": "MPESA123", "msisdn": phone,
                                          "operator": "Mpesa", "message": "ok"})
    assert ok.json()["status"] == "SUCCESS"
    again = client.post(callback_path, json={"utilityref": pay["externalId"], "transactionstatus": "success"})
    assert again.json().get("duplicate") is True
    done = client.get(f"/api/online-pay/{pay['id']}", headers=a).json()
    assert done["status"] == "SUCCESS" and done["operatorRef"] == "MPESA123"
    # deni limepungua kwa malipo moja tu (callback ya pili haikurudia)
    payments = client.post("/api/payment/search-payment", headers=a, json={"invoiceId": invoice_id}).json()
    text = str(payments)
    assert "MPESA123" in text and text.count("MPESA123") == 1

    # malipo yaliyokataliwa
    second = client.post("/api/online-pay/invoice", headers=a, json={"debtId": debt_id, "provider": "Tigo"}).json()
    assert second["amount"] == 30000  # deni lililobaki
    client.post(callback_path, json={"utilityref": second["externalId"], "transactionstatus": "failure",
                                     "message": "Insufficient balance"})
    failed = client.get(f"/api/online-pay/{second['id']}", headers=a).json()
    assert failed["status"] == "FAILED" and "Insufficient" in failed["message"]


def test_online_payment_subscription_azampay(client, platform, tenants, monkeypatch):
    from logistic import config
    from logistic.onlinepay import azampay

    fake = _FakeAzam()
    monkeypatch.setattr(azampay.requests, "post", fake.post)
    azampay._TOKENS.clear()
    a = tenants["alpha"]
    plans = client.get("/api/platform/plans", headers=platform).json()
    plan = next(p for p in plans if (p["currency"] or "TZS") == "TZS" and p["price"] > 0)

    assert client.get("/api/company/subscription/pay-online", headers=a).json()["enabled"] is False
    monkeypatch.setattr(config, "AZAMPAY_APP_NAME", "Platform")
    monkeypatch.setattr(config, "AZAMPAY_CLIENT_ID", "platform-client")
    monkeypatch.setattr(config, "AZAMPAY_CLIENT_SECRET", "platform-secret")
    cfg = client.get("/api/platform/online-payments/config", headers=platform).json()
    assert cfg["enabled"] is True and "/api/public/payments/azampay/" in cfg["callbackUrl"]

    before = client.get("/api/company/subscription", headers=a).json()["state"]["endsAt"]
    pay = client.post("/api/company/subscription/pay-online", headers=a, json={
        "plan_id": plan["id"], "periods": 2, "phone": "0754111222", "provider": "Airtel"}).json()
    assert pay["status"] == "PENDING" and pay["amount"] == plan["price"] * 2 and pay["provider"] == "Airtel"
    path = cfg["callbackUrl"][cfg["callbackUrl"].index("/api/public"):]
    # kiasi pungufu kinakataliwa
    low = client.post(path, json={"utilityref": pay["externalId"], "transactionstatus": "success", "amount": "100"})
    assert low.json()["status"] == "FAILED"
    pay = client.post("/api/company/subscription/pay-online", headers=a, json={
        "plan_id": plan["id"], "periods": 2, "phone": "0754111222", "provider": "Airtel"}).json()
    # callback ya kampuni haiwezi kukamilisha malipo ya subscription
    company_cb = client.get("/api/online-pay/settings", headers=a).json()["callbackUrl"]
    r = client.post(company_cb[company_cb.index("/api/public"):], json={"utilityref": pay["externalId"],
                                                                        "transactionstatus": "success"})
    assert r.json().get("ok") is False
    ok = client.post(path, json={"utilityref": pay["externalId"], "transactionstatus": "success",
                                 "amount": str(pay["amount"]), "reference": "AIRTEL9"})
    assert ok.json()["status"] == "SUCCESS"
    after = client.get("/api/company/subscription", headers=a).json()["state"]["endsAt"]
    assert after > before
    listed = client.get("/api/platform/online-payments?purpose=SUBSCRIPTION", headers=platform).json()
    assert any(x["id"] == pay["id"] and x["status"] == "SUCCESS" and x["companySlug"] == "alpha" for x in listed)


def test_platform_admin_roles(client, platform, tenants):
    ratelimit.reset()
    for name, role in (("fedha", "FINANCE"), ("msaada", "SUPPORT"), ("mtazamaji", "VIEWER")):
        r = client.post("/api/platform/admins", headers=platform, json={
            "username": name, "password": "Siri12345678", "fullName": f"Admin {name}", "role": role})
        assert r.status_code == 201 and r.json()["role"] == role, r.text
    assert client.post("/api/platform/admins", headers=platform, json={
        "username": "mbaya", "password": "Siri12345678", "fullName": "Mbaya Sana", "role": "BOSS"}).status_code == 400

    def login(u):
        tok = client.post("/api/platform/login", json={"username": u, "password": "Siri12345678"}).json()
        return {"Authorization": f"Bearer {tok['access_token']}"}

    fin, sup, view = login("fedha"), login("msaada"), login("mtazamaji")
    cid = _company_by_slug(client, platform, "alpha")["id"]
    plans = client.get("/api/platform/plans", headers=platform).json()

    # wote wanaweza kusoma
    for h in (fin, sup, view):
        assert client.get("/api/platform/companies", headers=h).status_code == 200
    # orodha ya wasimamizi na export ya data: OWNER tu
    assert client.get("/api/platform/admins", headers=fin).status_code == 403
    assert client.get(f"/api/platform/companies/{cid}/export", headers=sup).status_code == 403
    # FINANCE: malipo / nafasi za ziada ndiyo; kuongeza msimamizi hapana
    assert client.put(f"/api/platform/companies/{cid}/limits", headers=fin, json={"extraUsers": 1}).status_code == 200
    denied = client.post("/api/platform/admins", headers=fin, json={
        "username": "zaidi", "password": "Siri12345678", "fullName": "Zaidi"})
    assert denied.status_code == 403 and denied.json()["code"] == "ROLE_FORBIDDEN"
    # SUPPORT: kuingia kama kampuni ndiyo; malipo hapana
    assert client.post(f"/api/platform/companies/{cid}/impersonate", headers=sup, json={}).status_code == 200
    assert client.post("/api/platform/subscriptions/payments", headers=sup, json={
        "company_id": cid, "plan_id": plans[0]["id"], "amount": 1000}).status_code == 403
    # VIEWER: hakuna kubadilisha chochote, ila nywila yake
    assert client.put(f"/api/platform/companies/{cid}/limits", headers=view, json={"extraUsers": 3}).status_code == 403
    assert client.put("/api/platform/password", headers=view,
                      json={"oldPassword": "Siri12345678", "newPassword": "Mpya12345678"}).status_code == 200

    # lazima abaki OWNER mmoja aliye hai
    admins = client.get("/api/platform/admins", headers=platform).json()
    owners = [a for a in admins if a["role"] == "OWNER" and a["active"]]
    if len(owners) == 1:
        o = owners[0]
        r = client.put("/api/platform/admins", headers=platform, json={
            "id": o["id"], "fullName": o["fullName"], "active": True, "role": "VIEWER"})
        assert r.status_code == 400


def test_revenue_report(client, platform, tenants):
    r = client.get("/api/platform/reports/revenue?months=6", headers=platform)
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["months"]) == 6 and {"revenueTzs", "paying", "newCompanies", "churned"} <= set(data["months"][-1])
    assert data["totals"]["newCompanies"] >= 2 and isinstance(data["atRisk"], list)
    # kampuni mpya bila ankara siku 14 = hatarini (INACTIVE)
    inactive = [x for x in data["atRisk"] if "INACTIVE" in x["reasons"]]
    assert inactive and all(x["invoices14d"] == 0 for x in inactive)


def test_subscription_coupons(client, platform, tenants, monkeypatch):
    from logistic import config
    from logistic.onlinepay import azampay

    a, b = tenants["alpha"], tenants["beta"]
    plans = client.get("/api/platform/plans", headers=platform).json()
    plan = next(p for p in plans if (p["currency"] or "TZS") == "TZS" and p["price"] > 0)
    other = next(p for p in plans if p["id"] != plan["id"])
    alpha_id = _company_by_slug(client, platform, "alpha")["id"]

    c = client.post("/api/platform/coupons", headers=platform, json={
        "code": "karibu 20", "kind": "PERCENT", "value": 20, "planIds": [plan["id"]], "maxUses": 5})
    assert c.status_code == 200 and c.json()["code"] == "KARIBU20", c.text
    client.post("/api/platform/coupons", headers=platform, json={
        "code": "ALPHAONLY", "kind": "AMOUNT", "value": 5000, "company_id": alpha_id})
    assert client.post("/api/platform/coupons", headers=platform, json={
        "code": "KARIBU20", "kind": "PERCENT", "value": 10}).status_code == 400  # ipo tayari

    ok = client.post("/api/company/subscription/coupon", headers=a,
                     json={"code": "karibu20", "plan_id": plan["id"], "periods": 2}).json()
    assert ok["gross"] == plan["price"] * 2 and ok["discount"] == round(plan["price"] * 2 * 0.2, 2)
    assert client.post("/api/company/subscription/coupon", headers=a, json={
        "code": "KARIBU20", "plan_id": other["id"], "periods": 1}).status_code == 400   # mpango mwingine
    assert client.post("/api/company/subscription/coupon", headers=b, json={
        "code": "ALPHAONLY", "plan_id": plan["id"], "periods": 1}).status_code == 400   # si ya kampuni hii
    assert client.post("/api/company/subscription/coupon", headers=a, json={
        "code": "HAIPO", "plan_id": plan["id"], "periods": 1}).status_code == 400

    # malipo ya simu yanatumia bei baada ya punguzo; coupon inahesabiwa malipo yakikamilika
    fake = _FakeAzam()
    monkeypatch.setattr(azampay.requests, "post", fake.post)
    azampay._TOKENS.clear()
    monkeypatch.setattr(config, "AZAMPAY_APP_NAME", "Platform")
    monkeypatch.setattr(config, "AZAMPAY_CLIENT_ID", "platform-client")
    monkeypatch.setattr(config, "AZAMPAY_CLIENT_SECRET", "platform-secret")
    pay = client.post("/api/company/subscription/pay-online", headers=a, json={
        "plan_id": plan["id"], "periods": 2, "phone": "0754111333", "provider": "Mpesa", "couponCode": "KARIBU20"}).json()
    assert pay["amount"] == ok["amount"] and pay["couponCode"] == "KARIBU20"
    cfg = client.get("/api/platform/online-payments/config", headers=platform).json()
    path = cfg["callbackUrl"][cfg["callbackUrl"].index("/api/public"):]
    client.post(path, json={"utilityref": pay["externalId"], "transactionstatus": "success", "amount": str(pay["amount"])})
    used = next(x for x in client.get("/api/platform/coupons", headers=platform).json() if x["code"] == "KARIBU20")
    assert used["used"] == 1
    # kampuni hiyo hiyo haiwezi kuitumia tena (maxPerCompany = 1)
    assert client.post("/api/company/subscription/coupon", headers=a, json={
        "code": "KARIBU20", "plan_id": plan["id"], "periods": 1}).status_code == 400
    # taarifa ya malipo yenye coupon: inahifadhiwa, na inahesabiwa ikithibitishwa
    sent = client.post("/api/company/subscription/payment", headers=b, json={
        "plan_id": plan["id"], "amount": plan["price"] * 0.8, "method": "M-PESA", "reference": "CPN001",
        "couponCode": "KARIBU20"}).json()
    assert sent["couponCode"] == "KARIBU20" and sent["discount"] == round(plan["price"] * 0.2, 2)
    client.put(f"/api/platform/subscriptions/payments/{sent['id']}/confirm", headers=platform, json={})
    used = next(x for x in client.get("/api/platform/coupons", headers=platform).json() if x["code"] == "KARIBU20")
    assert used["used"] == 2


def test_support_tickets(client, platform, tenants):
    a, b = tenants["alpha"], tenants["beta"]
    t = client.post("/api/support", headers=a, json={"subject": "SMS hazitoki", "category": "TECH",
                                                     "text": "Tangu jana SMS za risiti hazifiki kwa wateja"})
    assert t.status_code == 200, t.text
    tid = t.json()["id"]
    assert t.json()["number"].startswith("T-") and t.json()["status"] == "OPEN"
    assert client.get(f"/api/support/{tid}", headers=b).status_code == 404  # kampuni nyingine haioni
    counts = client.get("/api/platform/tickets/counts", headers=platform).json()
    assert counts["open"] >= 1 and counts["unread"] >= 1
    assert client.get("/api/platform/dashboard", headers=platform).json()["tickets"]["open"] >= 1

    detail = client.get(f"/api/platform/tickets/{tid}", headers=platform).json()
    assert detail["companySlug"] == "alpha" and detail["messages"][0]["author"] == "COMPANY"
    client.post(f"/api/platform/tickets/{tid}/reply", headers=platform, json={"text": "Tumerekebisha, jaribuni tena"})
    assert client.get("/api/support/unread", headers=a).json()["unread"] == 1
    mine = client.get(f"/api/support/{tid}", headers=a).json()
    assert mine["status"] == "ANSWERED" and [m["author"] for m in mine["messages"]] == ["COMPANY", "ADMIN"]
    assert client.get("/api/support/unread", headers=a).json()["unread"] == 0
    notes = client.get("/api/notification", headers=a).json()
    assert "SUPPORT_REPLY" in str(notes)
    # kampuni ikijibu, inarudi OPEN; ikifunga -> CLOSED
    assert client.post(f"/api/support/{tid}/reply", headers=a, json={"text": "Bado"}).json()["status"] == "OPEN"
    assert client.put(f"/api/support/{tid}/close", headers=a).json()["status"] == "CLOSED"
    assert client.put(f"/api/platform/tickets/{tid}/status", headers=platform,
                      json={"status": "WRONG"}).status_code == 400


def test_onboarding_sessions_and_logout(client, platform, tenants):
    ratelimit.reset()
    a = tenants["alpha"]
    ob = client.get("/api/company/onboarding", headers=a).json()
    keys = {s["key"] for s in ob["steps"]}
    assert {"LOGO", "OFFICE", "PRICE", "USERS", "INVOICE"} <= keys and ob["total"] >= 7
    assert client.put("/api/company/onboarding/hide?hidden=true", headers=a).json()["hidden"] is True

    r = client.post("/api/login", json={"username": "admin", "password": "Siri12345"},
                    headers={"X-Company": "alpha", "X-Client": "web", "X-Device": "Chrome 130 | Windows 10/11"})
    old = {"Authorization": f"Bearer {r.json()['access_token']}", "X-Company": "alpha"}
    sessions = client.get("/api/user/me/sessions", headers=old).json()
    assert sessions and any("Chrome" in (s["device"] or "") for s in sessions)
    fresh = client.post("/api/user/me/logout-others", headers=old).json()
    new = {"Authorization": f"Bearer {fresh['access_token']}", "X-Company": "alpha"}
    assert client.get("/api/user/me/sessions", headers=old).status_code == 401   # vifaa vingine vimetolewa
    assert client.get("/api/user/me/sessions", headers=new).status_code == 200   # hiki kinabaki

    cid = _company_by_slug(client, platform, "alpha")["id"]
    assert client.post(f"/api/platform/companies/{cid}/logout-all", headers=platform).json()["users"] >= 1
    assert client.get("/api/user/me/sessions", headers=new).status_code == 401
    # kurudisha token za fixture (tests nyingine zinazitumia)
    tok = client.post("/api/login", json={"username": "admin", "password": "Siri12345"}, headers={"X-Company": "alpha"})
    a["Authorization"] = f"Bearer {tok.json()['access_token']}"


def test_database_schema_matches_models(client):
    from logistic import db_check
    from logistic.db import engine

    serious = [p for p in db_check.check(engine) if p["kind"] in ("TYPE", "NOT_NULL", "NULLABLE", "MISSING_TABLE",
                                                                  "MISSING_COLUMN")]
    assert serious == []


def test_company_logo_and_name_on_pdfs(client, tenants):
    """Logo na jina la kampuni vinaonekana kwenye PDF (lebo, ripoti); bila logo PDF bado inatengenezwa."""
    from io import BytesIO

    from PIL import Image
    from reportlab.lib import colors

    from logistic.core import brand, pdf, report_pdf, tenant
    from logistic.db import SessionLocal
    from logistic.saas.company.dao import CompanyDao

    buf = BytesIO()
    Image.new("RGB", (120, 60), (10, 122, 62)).save(buf, "PNG")
    a = tenants["alpha"]
    client.put("/api/company/profile", json={"name": "Alpha Cargo", "primaryColor": "#0A7A3E"}, headers=a)
    r = client.post("/api/company/logo", files={"file": ("logo.png", buf.getvalue(), "image/png")}, headers=a)
    assert r.status_code == 200, r.text

    db = SessionLocal()
    alpha, beta = CompanyDao(db).by_slug("alpha"), CompanyDao(db).by_slug("beta")
    db.close()
    with tenant.use_company(alpha.id):
        assert brand.logo() is not None
        assert brand.color() == colors.HexColor("#0A7A3E")
        out = pdf.labels([{"qr": "T1", "title": "Mzigo", "lines": ["a"]}])
        assert out.startswith(b"%PDF") and b"/Subtype /Image" in out and b"Alpha Cargo" in out
        rep = report_pdf.ReportPdf("Ripoti", period="Nov 2026")
        rep.note("Majaribio")
        out = rep.build()
        assert out.startswith(b"%PDF") and b"/Subtype /Image" in out
    with tenant.use_company(beta.id):
        assert brand.logo() is None and brand.color() == brand.DEFAULT
        out = pdf.labels([{"qr": "T2", "title": "Mzigo", "lines": []}])
        assert out.startswith(b"%PDF") and b"/Subtype /Image" not in out


def test_platform_notifications_and_pending(client, platform, tenants):
    """Super admin: taarifa (🔔) za malipo/tiketi/usajili, popup ya mambo yanayosubiri, na majukumu."""
    ratelimit.reset()
    a = tenants["alpha"]
    plan_id = client.get("/api/platform/plans", headers=platform).json()[0]["id"]
    before = client.get("/api/platform/notices", headers=platform).json()

    r = client.post("/api/company/subscription/payment", headers=a, json={
        "plan_id": plan_id, "periods": 1, "amount": 50000, "currency": "TZS", "method": "M-PESA",
        "reference": "NTF12345"})
    assert r.status_code in (200, 201), r.text
    t = client.post("/api/support", headers=a, json={"subject": "Haraka sana", "category": "TECH",
                                                     "priority": "HIGH", "text": "Mfumo hauonyeshi ankara"})
    assert t.status_code == 200, t.text

    d = client.get("/api/platform/notices", headers=platform).json()
    kinds = [n["kind"] for n in d["items"]]
    assert "PAYMENT_SUBMITTED" in kinds and "TICKET" in kinds
    assert d["unread"] >= before["unread"] + 2 and d["urgentUnread"] >= 2
    pay = next(n for n in d["items"] if n["kind"] == "PAYMENT_SUBMITTED")
    assert pay["priority"] == "URGENT" and pay["link"].startswith("payment:") and "NTF12345" in pay["body"]
    keys = {p["key"]: p for p in d["pending"]}
    assert keys["payments"]["count"] >= 1 and keys["payments"]["target"] == "payments"
    assert keys["tickets"]["count"] >= 1 and d["pendingTotal"] >= 2

    # kusoma moja, kisha zote
    r = client.post("/api/platform/notices/read", headers=platform, json={"ids": [pay["id"]]})
    assert r.status_code == 200 and r.json()["updated"] == 1
    d2 = client.get("/api/platform/notices", headers=platform).json()
    assert d2["unread"] == d["unread"] - 1
    assert next(n for n in d2["items"] if n["id"] == pay["id"])["isRead"] is True
    client.post("/api/platform/notices/read", headers=platform, json={"all": True})
    assert client.get("/api/platform/notices", headers=platform).json()["unread"] == 0

    # FINANCE: anaona malipo, si tiketi wala matatizo ya server; kusoma kwake hakugusi wengine
    client.post("/api/platform/admins", headers=platform, json={
        "username": "fedha2", "password": "Siri12345678", "fullName": "Fedha Mbili", "role": "FINANCE"})
    tok = client.post("/api/platform/login", json={"username": "fedha2", "password": "Siri12345678"}).json()
    fin = {"Authorization": f"Bearer {tok['access_token']}"}
    f = client.get("/api/platform/notices", headers=fin).json()
    assert all(n["area"] in ("PAYMENTS", "COMPANIES") for n in f["items"])
    assert any(n["kind"] == "PAYMENT_SUBMITTED" and not n["isRead"] for n in f["items"])
    assert all(p["area"] in ("PAYMENTS", "COMPANIES") for p in f["pending"])
    assert client.post("/api/platform/notices/read", headers=fin, json={"all": True}).status_code == 200

    # dedupe ya matatizo ya server
    from logistic.saas.notice.service import notify

    assert notify("SYSTEM", "SYSTEM", "Diski imejaa", dedupe="system:disk-test", urgent=True) is True
    assert notify("SYSTEM", "SYSTEM", "Diski imejaa", dedupe="system:disk-test", urgent=True) is False
    owner = client.get("/api/platform/notices", headers=platform).json()
    assert any(p["key"] == "system" for p in owner["pending"])
    assert not any(n["kind"] == "SYSTEM" for n in client.get("/api/platform/notices", headers=fin).json()["items"])


def test_plan_upgrade_carries_days_and_downgrade_waits_or_restarts(client, platform):
    """Upgrade: inaanza sasa + siku zilizobaki; downgrade: inasubiri (QUEUE) au inaanza sasa na siku kufutwa (NOW)."""
    from datetime import datetime, timezone

    ratelimit.reset()
    _signup(client, "upgrd", phone="0712000077")
    h = _login(client, "upgrd")
    cid = _company_by_slug(client, platform, "upgrd")["id"]
    plans = {}
    for code, price in (("SMALLX", 20000), ("BIGX", 80000)):
        r = client.post("/api/platform/plans", headers=platform,
                        json={"code": code, "name": code.title(), "price": price, "months": 1})
        assert r.status_code in (200, 201), r.text
        plans[code] = r.json()["id"]

    def days(iso_a, iso_b):
        a, b = (datetime.fromisoformat(x.replace("Z", "")) for x in (iso_a, iso_b))
        return round((b - a).total_seconds() / 86400)

    def pay(plan, mode=None, ref="R"):
        body = {"company_id": cid, "plan_id": plans[plan], "periods": 1, "amount": 1, "method": "CASH", "reference": ref}
        if mode:
            body["startMode"] = mode
        r = client.post("/api/platform/subscriptions/payments", headers=platform, json=body)
        assert r.status_code == 201, r.text

    def state():
        return client.get("/api/company/subscription", headers=h).json()["state"]

    # malipo ya kwanza: mpango mdogo (majaribio yanaisha) -> ~mwezi 1
    pay("SMALLX", ref="A1")
    st = state()
    assert st["plan"]["code"] == "smallx" and 27 <= st["daysLeft"] <= 31
    small_left = st["daysLeft"]

    # UPGRADE: maelezo kabla ya kulipa, kisha unaanza sasa na siku za SMALLX zinaongezwa
    pv = client.get(f"/api/company/subscription/plan-change?plan_id={plans['BIGX']}", headers=h).json()
    assert pv["kind"] == "UPGRADE" and abs(pv["carriedDays"] - small_left) <= 1
    pay("BIGX", ref="A2")
    st = state()
    assert st["plan"]["code"] == "bigx" and st["upcoming"] is None
    assert abs(st["daysLeft"] - (small_left + 30)) <= 2           # mwezi mpya + siku zilizobaki

    # DOWNGRADE (QUEUE, chaguo-msingi): BIGX inaendelea; SMALLX inapangwa kuanza BIGX ikiisha
    pv = client.get(f"/api/company/subscription/plan-change?plan_id={plans['SMALLX']}", headers=h).json()
    assert pv["kind"] == "DOWNGRADE" and pv["remainingDays"] >= 55 and pv["now"]["forfeitDays"] == pv["remainingDays"]
    assert days(pv["queue"]["startsAt"], pv["currentEndsAt"]) == 0
    big_left = state()["daysLeft"]
    pay("SMALLX", ref="A3")
    st = state()
    assert st["plan"]["code"] == "bigx"                             # vigezo havibadiliki bado
    assert st["upcoming"]["planName"] == "Smallx" and abs(st["daysLeft"] - (big_left + 30)) <= 2
    up = datetime.fromisoformat(st["upcoming"]["startsAt"].replace("Z", "")).replace(tzinfo=timezone.utc)
    assert (up - datetime.now(timezone.utc)).days >= big_left - 2

    # DOWNGRADE (NOW): mteja amekubali kufuta siku -> SMALLX inaanza sasa, siku za zamani na zilizopangwa zinafutwa
    pay("SMALLX", mode="NOW", ref="A4")
    st = state()
    assert st["plan"]["code"] == "smallx" and st["upcoming"] is None and 27 <= st["daysLeft"] <= 31

    # kampuni inatuma malipo yenye startMode; si sahihi -> kosa
    r = client.post("/api/company/subscription/payment", headers=h, json={
        "plan_id": plans["SMALLX"], "amount": 20000, "method": "M-PESA", "reference": "UPG999", "startMode": "LATER"})
    assert r.status_code == 400
    r = client.post("/api/company/subscription/payment", headers=h, json={
        "plan_id": plans["SMALLX"], "amount": 20000, "method": "M-PESA", "reference": "UPG998", "startMode": "NOW"})
    assert r.status_code == 201 and r.json()["startMode"] == "NOW"
