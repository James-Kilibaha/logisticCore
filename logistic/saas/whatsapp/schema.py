from pydantic import BaseModel, Field


class Connect(BaseModel):
    """Taarifa za WhatsApp Business (Meta Cloud API) za kampuni. Siri zikiachwa "••••" hazibadiliki."""
    phoneNumberId: str = Field(..., min_length=5, max_length=40)
    accessToken: str = Field(..., min_length=1)  # "••••••" = haijabadilishwa
    businessAccountId: str | None = Field(None, max_length=40)
    appSecret: str | None = None
    template: str | None = None
    documentTemplate: str | None = None
    imageTemplate: str | None = None
    language: str | None = Field(None, max_length=10)
    enabled: bool = True


class TestMessage(BaseModel):
    phone: str = Field(..., min_length=9)
    text: str | None = Field(None, max_length=500)
