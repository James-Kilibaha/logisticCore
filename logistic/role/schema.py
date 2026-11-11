from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Flags(BaseModel):
    data_insert: bool = False
    data_update: bool = False
    data_select: bool = False
    data_delete: bool = False
    data_block: bool = False


class ModuleFlags(Flags):
    model_config = ConfigDict(from_attributes=True)

    module: str


class Save(BaseModel):
    name: str = Field(..., min_length=2)
    description: str | None = None
    permissions: list[ModuleFlags] = []
    applyToUsers: bool = True   # kusasisha ruhusa za watumiaji wenye role hii


class Display(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None = None
    isSystem: bool = False
    users: int = 0
    permissions: list[ModuleFlags] = []


class Assign(BaseModel):
    user_id: UUID
    role_id: UUID | None = None   # None = kuondoa role (ruhusa zinabaki kama zilivyo)
