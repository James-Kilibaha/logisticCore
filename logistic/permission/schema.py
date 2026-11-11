from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PermissionFlags(BaseModel):
    data_insert: bool = False
    data_update: bool = False
    data_select: bool = False
    data_delete: bool = False
    data_block: bool = False


class PermissionCreate(PermissionFlags):
    name: str
    user_id: UUID


class PermissionUpdate(PermissionFlags):
    id: UUID
    user_id: UUID


class PermissionList(PermissionFlags):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    user_id: UUID
