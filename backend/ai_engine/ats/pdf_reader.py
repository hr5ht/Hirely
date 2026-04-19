import os
import logging
import pdfplumber
logger = logging.getLogger(__name__)
def extract_text_from_pdf(pdf_path: str) -> str:
    if not os.path.exists(pdf_path):
        logger.error(f"PDF file not found at {pdf_path}")
        return ""
    text = _extract_with_pdfplumber(pdf_path)
    if not text.strip():
        logger.info("pdfplumber returned no text — attempting OCR fallback...")
        text = _extract_with_ocr(pdf_path)
    return text.strip()
def _extract_with_pdfplumber(pdf_path: str) -> str:
    text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        logger.error(f"pdfplumber failed: {e}")
    return text
def _extract_with_ocr(pdf_path: str) -> str:
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except ImportError as e:
        logger.warning(f"OCR fallback unavailable — missing package: {e}")
        return ""
    try:
        pages = convert_from_path(pdf_path, dpi=300)
        ocr_text = ""
        for i, page_image in enumerate(pages, start=1):
            page_text = pytesseract.image_to_string(page_image, lang="eng")
            if page_text:
                ocr_text += page_text + "\n"
        return ocr_text
    except Exception as e:
        logger.error(f"OCR fallback failed: {e}")
        return ""
