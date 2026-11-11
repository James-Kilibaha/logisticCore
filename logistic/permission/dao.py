from ..core.dao import BaseDao, to_uuid
from .model import Permission

_ACTION_COLUMN = {
    "insert": Permission.data_insert,
    "update": Permission.data_update,
    "select": Permission.data_select,
    "delete": Permission.data_delete,
    "block": Permission.data_block,
}


class PermissionDao(BaseDao[Permission]):
    model = Permission

    def has(self, user_id, module: str, action: str) -> bool:
        column = _ACTION_COLUMN.get(action)
        if column is None:
            return False
        return self.exists(Permission.user_id == to_uuid(user_id), Permission.name == module, column.is_(True))

    def for_user(self, user_id):
        return self.find_all(Permission.user_id == to_uuid(user_id), order_by=Permission.name)

    def by_name(self, user_id, name: str) -> Permission | None:
        return self.find_one(Permission.user_id == to_uuid(user_id), Permission.name == name)

    def by_id(self, user_id, permission_id) -> Permission | None:
        return self.find_one(Permission.user_id == to_uuid(user_id), Permission.id == to_uuid(permission_id))

    def names_for_user(self, user_id) -> set[str]:
        rows = self.db.query(Permission.name).filter(Permission.user_id == to_uuid(user_id)).all()
        return {r[0] for r in rows}
