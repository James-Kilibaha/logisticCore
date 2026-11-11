from sqlalchemy.orm import joinedload

from ..core.dao import BaseDao, to_uuid
from .model import Product


class ProductDao(BaseDao[Product]):
    model = Product

    def all_with_price(self) -> list[Product]:
        return self.all(joinedload(Product.price))

    def by_invoice(self, invoice_id) -> list[Product]:
        return self.find_all(Product.invoice_id == to_uuid(invoice_id), options=[joinedload(Product.price)])

    def with_image(self, invoice_id) -> list[Product]:
        return self.find_all(Product.invoice_id == to_uuid(invoice_id), Product.path.isnot(None))
