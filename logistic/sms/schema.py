from uuid import UUID

from pydantic import BaseModel, Field


class Search(BaseModel):
    smsFor: str | None = None
    isReceived: bool = False
    isSMSSend: bool | None = False  # None = zote (historia): zinazosubiri na zilizotumwa
    channel: str | None = None   # SMS / WHATSAPP
    days: int | None = None      # siku za karibuni tu (mf. 30)
    limit: int | None = None     # idadi ya juu (mpya kwanza)
    deliveryStatus: str | None = None  # SENT / DELIVERED / FAILED (ripoti za kufika)


class SendFrom(BaseModel):
    id: UUID
    text: str | None = Field(None, description="Ukiacha tupu, maandishi yaliyohifadhiwa yanatumwa")


class Resend(BaseModel):
    """Kutuma tena ujumbe uliokwisha tumwa: nakala mpya inatumwa, ya zamani inabaki kwenye historia."""
    id: UUID
    text: str | None = Field(None, description="Tupu = maandishi yale yale")
    msisdn: str | None = Field(None, description="Tupu = namba ile ile (au weka namba sahihi)")


class StoreDetails(BaseModel):
    """Taarifa za SMS ya 'mzigo umefika stoo'."""
    name: str
    quantity: float
    amount: float
    kg: float
    usd: float
    invoiceNumber: str | None = None
    items: str = ""  # bidhaa moja moja (sms.service.items_block)
    totals: str = ""  # jumla (sms.service.totals_line)
    hasCodes: bool = False  # bidhaa zina code ya ofisi (iko kwenye items)
