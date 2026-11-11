from sqlalchemy import Boolean, Column, Index, Integer, String

from ..core.base_model import EntityBase


class PopupRule(EntityBase):
    """
    Taarifa zinazojitokeza (pop-up) kwenye app: admin anaweka kila aina
      - afterDays:    jambo likae siku ngapi kabla halijaanza kuonyeshwa (mf. deni la zaidi ya siku 3)
      - everyMinutes: likishaanza, lijitokeze tena kila baada ya dakika ngapi (kwa kila mtumiaji)
    """
    __tablename__ = "popup_rules"

    kind = Column(String, nullable=False)  # ya kipekee ndani ya kampuni
    enabled = Column(Boolean, nullable=False, default=True)
    afterDays = Column(Integer, nullable=False, default=3)
    everyMinutes = Column(Integer, nullable=False, default=120)

    __table_args__ = (Index("ux_popup_rules_company_kind", "company_id", "kind", unique=True),)
