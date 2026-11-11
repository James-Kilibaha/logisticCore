from uuid import UUID

from pydantic import BaseModel, Field


class Settings(BaseModel):
    """Akaunti ya AzamPay ya kampuni ("••••••" = siri iliyohifadhiwa haibadilishwi)."""
    env: str = "sandbox"
    appName: str = Field(..., min_length=1, max_length=120)
    clientId: str = Field(..., min_length=4, max_length=200)
    clientSecret: str = Field(..., min_length=1, max_length=2000)
    apiKey: str | None = Field(None, max_length=2000)
    instituteId: UUID | None = None
    enabled: bool = True


class PayInvoice(BaseModel):
    debtId: UUID
    phone: str | None = None        # tupu = simu ya mteja wa ankara
    provider: str | None = None     # Mpesa, Tigo, Airtel, Halopesa, Azampesa (tupu = kukisia kwa namba)
    amount: float | None = Field(None, gt=0)  # tupu = deni lote


class PaySubscription(BaseModel):
    plan_id: UUID
    periods: int = Field(1, ge=1, le=36)
    phone: str = Field(..., min_length=9)
    provider: str
    couponCode: str | None = Field(None, max_length=30)
    startMode: str | None = Field(None, max_length=10)   # QUEUE | NOW (mpango mdogo kuliko uliolipiwa)
