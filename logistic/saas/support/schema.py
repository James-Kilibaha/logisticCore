from pydantic import BaseModel, Field


class NewTicket(BaseModel):
    subject: str = Field(..., min_length=3, max_length=150)
    category: str = "TECH"
    priority: str = "NORMAL"
    text: str = Field(..., min_length=3, max_length=5000)


class Reply(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)


class Status(BaseModel):
    status: str
