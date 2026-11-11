from sqlalchemy import Boolean, Column, Date, DateTime, Float, Index, String

from ..core.base_model import AuditedEntity


class Package(AuditedEntity):
    """
    Box/kifurushi cha kusafirisha. `productList` na `invoiceList` ni id
    zilizotenganishwa kwa koma (kama ilivyo kwenye database iliyopo).
    """
    __tablename__ = "packages"

    boxId = Column(String, nullable=False)
    packageType = Column(String, nullable=False)
    weight = Column(Float, nullable=False)
    trackNumber = Column(String, nullable=False)
    productList = Column(String, nullable=False)
    invoiceList = Column(String, nullable=False)
    isCollect = Column(Boolean, nullable=False)   # limepokelewa stoo (Tanzania)
    isBoxClose = Column(Boolean, nullable=False)  # limefungwa na kusafirishwa
    shippedAt = Column(DateTime, nullable=True)   # lilipofungwa na kusafirishwa
    eta = Column(Date, nullable=True)             # tarehe ya kutarajia kufika Tanzania
    arrivedAt = Column(DateTime, nullable=True)   # lilipopokelewa stoo

    __table_args__ = (Index("ux_packages_boxid", "company_id", "boxId", unique=True),)
