"""
Data kwa ofisi.

- Mtumiaji mwenye `allOffices=True` (default) au asiye na ofisi anaona data yote.
- Mtumiaji mwenye ofisi na `allOffices=False` anaona ankara za ofisi yake (na ankara zisizo na ofisi),
  na matumizi (expenses) ya ofisi yake tu. Anachounda kinaandikwa kwa ofisi yake.
"""
from uuid import UUID

from sqlalchemy.orm import Session


def office_scope(db: Session, user_id) -> UUID | None:
    """Ofisi ambayo mtumiaji amefungiwa (None = ofisi zote)."""
    from ..user.dao import UserDao

    user = UserDao(db).get(user_id)
    if user is None or user.office_id is None or getattr(user, "allOffices", True) is not False:
        return None
    return user.office_id


def user_office(db: Session, user_id) -> UUID | None:
    from ..user.dao import UserDao

    user = UserDao(db).get(user_id)
    return user.office_id if user else None
