import json

from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..core import files
from ..core.enums import ESmsStatus
from ..core.exceptions import BadRequest, NotFound
from ..core.utils import title
from ..invoice.dao import InvoiceDao
from ..sms import service as sms_service
from . import schema
from .dao import ProductDao
from .model import Product


def parse_create(raw: str) -> schema.Create:
    """App inatuma JSON kama string ndani ya multipart (`stringValue`)."""
    try:
        return schema.Create(**json.loads(raw))
    except json.JSONDecodeError:
        raise BadRequest("stringValue must be valid JSON")
    except ValidationError as error:
        raise BadRequest("; ".join(e["msg"].replace("Value error, ", "") for e in error.errors()))


_COLUMN = {"priceId": "price_id"}


def _fields(data, *, only_set: bool = False) -> dict:
    values = data.model_dump(exclude={"id", "invoiceId", "officeCode"}, exclude_none=only_set)
    if values.get("description"):
        values["description"] = title(values["description"])
    return {_COLUMN.get(k, k): v for k, v in values.items()}


def create(db: Session, data: schema.Create, filename: str | None, content: bytes | None, current_user_id) -> Product:
    invoice = InvoiceDao(db).with_details(data.invoiceId)
    if invoice is None:
        raise NotFound("Invoice not found...")

    from ..core import office_code

    code = office_code.for_new_product(db, data.officeCode)
    path = files.save_image(filename, content) if content else None  # picha si lazima
    try:
        product = ProductDao(db).create(path=path, invoice_id=invoice.id, logsId=current_user_id, officeCode=code,
                                       **_fields(data))
    except Exception:
        files.remove(path)
        raise

    customer = invoice.customer[0] if invoice.customer else None
    if customer:
        sms_service.queue(db, ESmsStatus.RECEIVED, text=sms_service.received_message(product, customer.name),
                          msisdn=customer.phoneNumber, reference=str(product.id), invoice_id=invoice.id,
                          logs_id=current_user_id)
    if path is None:  # picha iliyopigwa kwa simu (QR ya code ya ofisi) kabla ya kuhifadhi
        from .photo import attach_staged

        attach_staged(db, product)
    return product


def update(db: Session, data: schema.Update) -> Product:
    dao = ProductDao(db)
    product = dao.get(data.id)
    if product is None:
        raise NotFound("Product not found...")
    return dao.update(product, **_fields(data, only_set=True))


def list_all(db: Session):
    return ProductDao(db).all_with_price()


def by_invoice(db: Session, invoice_id):
    return ProductDao(db).by_invoice(invoice_id)


def delete(db: Session, product_id) -> bool:
    dao = ProductDao(db)
    product = dao.get(product_id)
    if product is None:
        raise NotFound("The Product does not exist")
    if not files.remove(product.path):
        raise BadRequest("Image is not deleted...")
    return dao.delete(product)


def image_path(folder: str, images_folder: str, image: str):
    relative = f"{folder}/{images_folder}/{image}"
    if not files.owned(relative):  # picha ya kampuni nyingine
        from ..core.exceptions import NotFound

        raise NotFound("File not found")
    return files.existing(relative)
