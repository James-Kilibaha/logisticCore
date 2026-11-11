"""
Mteja wa AzamPay (MNO checkout = mteja anapokea ombi la PIN kwenye simu yake).

    client = Azampay(app_name, client_id, client_secret, api_key, env="sandbox")
    tx = client.checkout("255712345678", 5000, "Mpesa", "LG8F3A...")   # -> transactionId

Token: POST {auth}/AppRegistration/GenerateToken  {appName, clientId, clientSecret}
Checkout: POST {base}/azampay/mno/checkout  (Authorization: Bearer <token>, X-API-Key: <api key>)
          {accountNumber, amount, currency, externalId, provider}
Callback (AzamPay -> sisi): {msisdn, amount, message, utilityref (= externalId), operator, reference,
          transactionstatus ("success"/"failure"), submerchantAcc, ...}
"""
import logging
import threading
import time

import requests

from ..core.exceptions import BadRequest

logger = logging.getLogger(__name__)

URLS = {
    "sandbox": ("https://authenticator-sandbox.azampay.co.tz", "https://sandbox.azampay.co.tz"),
    "live": ("https://authenticator.azampay.co.tz", "https://checkout.azampay.co.tz"),
}
PROVIDERS = {"MPESA": "Mpesa", "TIGO": "Tigo", "AIRTEL": "Airtel", "HALOPESA": "Halopesa", "AZAMPESA": "Azampesa"}

_TOKENS: dict[str, tuple[str, float]] = {}
_LOCK = threading.Lock()


def provider_name(value: str | None) -> str:
    key = "".join(c for c in (value or "").upper() if c.isalnum()).replace("PESA", "PESA")
    for k, v in PROVIDERS.items():
        if key in (k, v.upper()) or (k == "MPESA" and key in ("VODACOM", "MPESA")) or \
                (k == "TIGO" and key in ("TIGOPESA", "YAS", "MIXXBYYAS", "MIXX")) or \
                (k == "AIRTEL" and key == "AIRTELMONEY"):
            return v
    raise BadRequest("Chagua mtandao: M-Pesa, Tigo Pesa (Mixx), Airtel Money, Halopesa au AzamPesa")


def guess_provider(msisdn: str) -> str | None:
    """Kukisia mtandao kwa kiambishi cha namba (+255 7X...). Mtumiaji anaweza kubadilisha."""
    digits = "".join(c for c in msisdn if c.isdigit())
    local = digits[3:] if digits.startswith("255") else digits.lstrip("0")
    prefix = local[:2]
    return {"74": "Mpesa", "75": "Mpesa", "76": "Mpesa", "79": "Mpesa", "71": "Tigo", "65": "Tigo", "67": "Tigo",
            "77": "Tigo", "68": "Airtel", "69": "Airtel", "78": "Airtel", "62": "Halopesa", "61": "Halopesa"}.get(prefix)


class Azampay:
    def __init__(self, app_name: str, client_id: str, client_secret: str, api_key: str, env: str = "sandbox",
                 auth_url: str | None = None, base_url: str | None = None):
        if not (app_name and client_id and client_secret):
            raise BadRequest("AzamPay haijaunganishwa (App name, Client ID, Client secret) / AzamPay not configured")
        default_auth, default_base = URLS.get((env or "sandbox").lower(), URLS["sandbox"])
        self.app_name, self.client_id, self.client_secret, self.api_key = app_name, client_id, client_secret, api_key
        self.auth_url = (auth_url or default_auth).rstrip("/")
        self.base_url = (base_url or default_base).rstrip("/")

    def _token(self, fresh: bool = False) -> str:
        key = f"{self.auth_url}|{self.client_id}"
        with _LOCK:
            cached = _TOKENS.get(key)
            if cached and not fresh and cached[1] > time.time():
                return cached[0]
        try:
            r = requests.post(f"{self.auth_url}/AppRegistration/GenerateToken", timeout=30,
                              json={"appName": self.app_name, "clientId": self.client_id,
                                    "clientSecret": self.client_secret})
        except requests.RequestException as error:
            raise BadRequest(f"AzamPay haipatikani: {error}")
        body = _json(r)
        token = ((body.get("data") or {}).get("accessToken")) if isinstance(body, dict) else None
        if r.status_code >= 300 or not token:
            raise BadRequest(f"AzamPay imekataa App name / Client ID / Secret: {_message(body, r)}")
        with _LOCK:
            _TOKENS[key] = (token, time.time() + 50 * 60)  # token ya AzamPay inadumu takriban saa 1
        return token

    def checkout(self, msisdn: str, amount: float, provider: str, external_id: str) -> str:
        account = "".join(c for c in msisdn if c.isdigit())
        if account.startswith("0"):
            account = "255" + account[1:]
        payload = {"accountNumber": account, "amount": str(int(round(amount))), "currency": "TZS",
                   "externalId": external_id, "provider": provider}
        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {self._token(fresh=attempt == 2)}", "Content-Type": "application/json"}
            if self.api_key:
                headers["X-API-Key"] = self.api_key
            try:
                r = requests.post(f"{self.base_url}/azampay/mno/checkout", json=payload, headers=headers, timeout=45)
            except requests.RequestException as error:
                raise BadRequest(f"AzamPay haipatikani: {error}")
            if r.status_code == 401 and attempt == 1:
                continue  # token imeisha - jaribu tena na mpya
            body = _json(r)
            logger.info("AzamPay checkout %s %s -> HTTP %s %s", external_id, provider, r.status_code, str(body)[:300])
            ok = isinstance(body, dict) and (body.get("success") is True or body.get("succcess") is True)
            if r.status_code >= 300 or not ok:
                raise BadRequest(f"AzamPay imekataa ombi la malipo: {_message(body, r)}")
            return str(body.get("transactionId") or "")
        raise BadRequest("AzamPay: token haikubaliki")


def _json(response):
    try:
        return response.json()
    except ValueError:
        return {}


def _message(body, response) -> str:
    if isinstance(body, dict):
        return str(body.get("message") or body.get("msg") or body.get("error") or body)[:300]
    return (getattr(response, "text", "") or f"HTTP {response.status_code}")[:300]
