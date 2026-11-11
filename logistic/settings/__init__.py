"""Mipangilio: kila sehemu ina folder lake (model, schema, dao, service, router)."""
from .currency.router import router as currency_router
from .institute.router import router as institute_router
from .office.router import router as office_router
from .price.router import router as price_router
from .sms_set.router import router as sms_set_router

routers = [currency_router, price_router, sms_set_router, institute_router, office_router]
