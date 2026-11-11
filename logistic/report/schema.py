from pydantic import BaseModel


class Range(BaseModel):
    startDate: str | None = None   # 'YYYY-MM-DD' (au ISO)
    endDate: str | None = None
    status: str | None = None      # hali ya deni (EPaymentStatus)
    office: str | None = None      # office id (matumizi)
