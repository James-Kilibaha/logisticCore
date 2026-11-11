from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from ..core.enums import Action, Module
from ..core.permission import require
from ..db import get_db
from . import schema, service

router = APIRouter(tags=["Package"], prefix="/api/package")


def _pdf(content: bytes, name: str) -> Response:
    return Response(content, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}.pdf"'})


@router.post("", status_code=status.HTTP_201_CREATED)
def create_package(request: schema.Insert, db: Session = Depends(get_db),
                   current_user=Depends(require(Module.PACKAGE, Action.INSERT))):
    return service.create(db, request, current_user.id)


@router.put("/add-product-package", status_code=status.HTTP_201_CREATED)
def add_product(request: schema.AddProduct, db: Session = Depends(get_db),
                _=Depends(require(Module.PACKAGE, Action.UPDATE))):
    return service.add_product(db, request)


@router.put("/remove-product-package", status_code=status.HTTP_201_CREATED)
def remove_product(request: schema.RemoveProduct, db: Session = Depends(get_db),
                   _=Depends(require(Module.PACKAGE, Action.UPDATE))):
    return service.remove_product(db, request)


@router.get("/late", status_code=status.HTTP_200_OK)
def late_packages(db: Session = Depends(get_db), _=Depends(require(Module.PACKAGE, Action.SELECT))):
    """Mabox yaliyo safarini ambayo tarehe ya kutarajia kufika (ETA) imepita."""
    return service.late(db)


@router.put("/{package_id}/eta", status_code=status.HTTP_200_OK)
def set_eta(package_id: str, request: schema.SetEta, db: Session = Depends(get_db),
            current_user=Depends(require(Module.PACKAGE, Action.UPDATE))):
    """Kubadilisha ETA ya box lililo safarini (hiari: SMS kwa wateja wake)."""
    from ..core.audit import note

    package = service.set_eta(db, package_id, request, current_user.id)
    note(f"Box {package.boxId}: ETA {request.eta:%d/%m/%Y}" + (" (wateja wamejulishwa)" if request.notify else ""))
    return package


@router.put("/close-package", status_code=status.HTTP_201_CREATED)
def close_package(request: schema.ClosePackage, db: Session = Depends(get_db),
                  current_user=Depends(require(Module.PACKAGE, Action.UPDATE))):
    return service.close(db, request, current_user.id)


@router.put("/is-correct-package", status_code=status.HTTP_201_CREATED)
def mark_collected(request: schema.MarkCollected, db: Session = Depends(get_db),
                   current_user=Depends(require(Module.PACKAGE, Action.UPDATE))):
    return service.mark_collected(db, request, current_user.id)


@router.get("/available-products", status_code=status.HTTP_200_OK)
def get_available_products(db: Session = Depends(get_db), _=Depends(require(Module.PACKAGE, Action.SELECT))):
    """Bidhaa za invoice zenye hali PARKING ambazo bado hazijawekwa kwenye box lolote."""
    return service.available_products(db)


@router.get("/{package_id}/products", status_code=status.HTTP_200_OK)
def get_package_products(package_id: str, db: Session = Depends(get_db),
                         _=Depends(require(Module.PACKAGE, Action.SELECT))):
    return service.products_in(db, package_id)


@router.get("/{package_id}/next-track", status_code=status.HTTP_200_OK)
def package_next_track(package_id: str, db: Session = Depends(get_db),
                       _=Depends(require(Module.PACKAGE, Action.SELECT))):
    """Track number ya safari inayopendekezwa (ya mfumo) kwa box hili."""
    return service.suggest_track(db, package_id)


@router.get("/{package_id}/arrivals", status_code=status.HTTP_200_OK)
def package_arrivals(package_id: str, db: Session = Depends(get_db),
                     _=Depends(require(Module.PACKAGE, Action.SELECT))):
    """Ankara za box (wateja, mizigo, pesa) na hali ya SMS ya "mzigo umefika"."""
    return service.arrivals(db, package_id)


@router.get("/{package_id}/arrivals.xlsx", status_code=status.HTTP_200_OK)
def package_arrivals_excel(package_id: str, db: Session = Depends(get_db),
                           _=Depends(require(Module.PACKAGE, Action.SELECT))):
    content, name = service.arrivals_excel(db, package_id)
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})


@router.post("/{package_id}/notify-store", status_code=status.HTTP_200_OK)
def package_notify_store(package_id: str, request: schema.NotifyStore, db: Session = Depends(get_db),
                         current_user=Depends(require(Module.SMS, Action.INSERT))):
    """Kutuma SMS ya "mzigo umefika" kwa mteja mmoja mmoja au wote wa box hili."""
    return service.notify_store(db, package_id, request, current_user.id)


@router.get("/{package_id}/manifest", status_code=status.HTTP_200_OK)
def package_manifest(package_id: str, db: Session = Depends(get_db),
                     _=Depends(require(Module.PACKAGE, Action.SELECT))):
    content, name = service.manifest_pdf(db, package_id)
    return _pdf(content, name)


@router.get("/{package_id}/labels", status_code=status.HTTP_200_OK)
def package_labels(package_id: str, perCarton: bool = False, db: Session = Depends(get_db),
                   _=Depends(require(Module.PACKAGE, Action.SELECT))):
    content, name = service.labels_pdf(db, package_id, perCarton)
    return _pdf(content, name)


@router.get("/invoice/{invoice_id}/labels", status_code=status.HTTP_200_OK)
def invoice_labels(invoice_id: str, perCarton: bool = False, db: Session = Depends(get_db),
                   _=Depends(require(Module.INVOICE, Action.SELECT))):
    content, name = service.invoice_labels_pdf(db, invoice_id, perCarton)
    return _pdf(content, name)


@router.get("/{isCollect}/{isBoxClose}", status_code=status.HTTP_200_OK)
def get_packages_by_flags(isCollect: bool, isBoxClose: bool, db: Session = Depends(get_db),
                          _=Depends(require(Module.PACKAGE, Action.SELECT))):
    return service.by_flags(db, isCollect, isBoxClose)


@router.get("", status_code=status.HTTP_200_OK)
def get_all_packages(db: Session = Depends(get_db), _=Depends(require(Module.PACKAGE, Action.SELECT))):
    return service.list_all(db)


@router.delete("/{package_id}", status_code=status.HTTP_200_OK)
def delete_package(package_id: str, db: Session = Depends(get_db),
                   _=Depends(require(Module.PACKAGE, Action.DELETE))):
    return service.delete(db, package_id)
