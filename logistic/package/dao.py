from ..core.dao import BaseDao
from .model import Package


class PackageDao(BaseDao[Package]):
    model = Package

    def by_box_id(self, box_id: str) -> Package | None:
        return self.find_one(Package.boxId == box_id)

    def by_track_number(self, track: str) -> Package | None:
        return self.find_one(Package.trackNumber == track)

    def containing_product(self, product_id) -> Package | None:
        return self.find_one(Package.productList.contains(str(product_id)))

    def by_flags(self, is_collect: bool, is_box_close: bool) -> list[Package]:
        return self.find_all(Package.isCollect == is_collect, Package.isBoxClose == is_box_close,
                             order_by=Package.created_at.desc())

    def all_ordered(self) -> list[Package]:
        return self.find_all(order_by=Package.created_at.desc())
