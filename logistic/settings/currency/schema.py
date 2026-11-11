from pydantic import BaseModel, Field


class Create(BaseModel):
    name: str = Field(..., min_length=1)
    buy: float = Field(..., gt=0)


class Filter(BaseModel):
    id: str | None = None
    name: str | None = None
    isBlocked: bool | None = None


class Update(BaseModel):
    """Kurekebisha kiwango cha sasa (kosa la kuandika) bila kuanzisha historia mpya."""
    id: str
    buy: float = Field(..., gt=0)
