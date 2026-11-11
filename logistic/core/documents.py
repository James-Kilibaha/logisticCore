"""
Kutengeneza PDF kutoka template za Word (assets/sample/*.docx).

Inatumika na invoice, store na report - code moja badala ya nakala tatu.
"""
import logging
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from docxtpl import DocxTemplate

from .. import config
from . import files
from .exceptions import AppError

logger = logging.getLogger(__name__)


def _libreoffice() -> str:
    candidates = [config.LIBREOFFICE_PATH, shutil.which("soffice"), shutil.which("libreoffice"),
                  "/usr/lib/libreoffice/program/soffice"]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise AppError("LibreOffice is not installed on the server (needed to create PDF)")


# MS Word (COM) haiwezi kubadilisha nyaraka mbili kwa wakati mmoja - zinapanga foleni.
_word_lock = threading.Lock()


def _word_to_pdf(docx_path: Path, pdf_path: Path) -> None:
    """
    Windows: MS Word kupitia COM. FastAPI inaendesha kila request kwenye thread tofauti, na COM
    lazima iandaliwe (CoInitialize) kwenye kila thread inayoitumia - vinginevyo:
    'CoInitialize has not been called'.
    """
    import pythoncom  # pywin32 (inakuja na docx2pdf)
    from docx2pdf import convert

    with _word_lock:
        pythoncom.CoInitialize()
        try:
            convert(str(docx_path), str(pdf_path))
        finally:
            pythoncom.CoUninitialize()


def _libreoffice_to_pdf(docx_path: Path, pdf_path: Path) -> None:
    subprocess.run(
        [_libreoffice(), "--headless", "--convert-to", "pdf", str(docx_path), "--outdir", str(pdf_path.parent)],
        check=True, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _to_pdf(docx_path: Path, pdf_path: Path) -> None:
    if not sys.platform.startswith("win"):
        _libreoffice_to_pdf(docx_path, pdf_path)
        return
    try:
        _word_to_pdf(docx_path, pdf_path)
    except Exception as word_error:
        # Word haipo / imekwama: jaribu LibreOffice kama imewekwa (LIBREOFFICE_PATH)
        logger.warning("MS Word imeshindwa kutengeneza PDF (%s); najaribu LibreOffice", word_error)
        try:
            _libreoffice_to_pdf(docx_path, pdf_path)
        except AppError:
            raise AppError(f"Failed to create PDF with MS Word: {word_error}")


def render_pdf(template: str, context: dict, relative_path: str) -> Path:
    """
    template      : jina la template bila .docx (mfano 'InvoiceSample', 'range')
    relative_path : njia ya kuhifadhi bila extension (mfano '<company_id>/Report/debt')
    Inarudisha njia kamili ya PDF.
    """
    target = files.absolute(relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    docx_path = target.with_suffix(".docx")
    pdf_path = target.with_suffix(".pdf")

    doc = DocxTemplate(str(config.TEMPLATES_DIR / f"{template}.docx"))
    doc.render(context)
    doc.save(str(docx_path))
    try:
        _to_pdf(docx_path, pdf_path)
    except AppError:
        raise
    except Exception as error:
        logger.exception("PDF conversion failed")
        raise AppError(f"Failed to create PDF: {error}")
    finally:
        docx_path.unlink(missing_ok=True)

    if not pdf_path.exists():
        raise AppError("Failed to create PDF")
    return pdf_path
