from dataclasses import dataclass
from functools import lru_cache
from html.parser import HTMLParser
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from app.core.config import settings
from app.utils.text import normalize_text

try:
    import pypdfium2
except Exception:  # pragma: no cover - optional dependency path
    pypdfium2 = None

try:
    import fitz
except Exception:  # pragma: no cover - optional dependency path
    fitz = None

try:
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        EasyOcrOptions,
        PdfPipelineOptions,
        RapidOcrOptions,
        TesseractCliOcrOptions,
        TesseractOcrOptions,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption
except Exception as exc:  # pragma: no cover - import failure depends on local environment
    InputFormat = None
    PdfPipelineOptions = None
    EasyOcrOptions = None
    RapidOcrOptions = None
    TesseractCliOcrOptions = None
    TesseractOcrOptions = None
    DocumentConverter = None
    PdfFormatOption = None
    DOCLING_IMPORT_ERROR = exc
else:
    DOCLING_IMPORT_ERROR = None


SUPPORTED_EXTENSIONS = {".txt", ".md", ".markdown", ".html", ".htm", ".docx", ".pdf"}
WINDOWS_TESSERACT_DIRS = (
    Path(r"C:\Program Files\Tesseract-OCR"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR"),
)


class DocumentParserError(Exception):
    pass


class UnsupportedDocumentFormatError(DocumentParserError):
    pass


class DocumentExtractionError(DocumentParserError):
    pass


class ParserDependencyError(DocumentParserError):
    pass


@dataclass(slots=True)
class ParsedDocument:
    text_for_chunking: str
    text_for_hashing: str


class HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data and data.strip():
            self.parts.append(data)

    def get_text(self) -> str:
        return " ".join(self.parts)


def ensure_supported_document_filename(filename: str) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise UnsupportedDocumentFormatError(
            f"Unsupported file type '{suffix or 'unknown'}'. Supported formats: {supported}"
        )


def _read_text_file(path: str | Path) -> str:
    file_path = Path(path)
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return file_path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return file_path.read_text(encoding="utf-8", errors="replace")


def _strip_html(raw_html: str) -> str:
    parser = HTMLTextExtractor()
    parser.feed(raw_html)
    parser.close()
    return parser.get_text()


def _normalize(value: str) -> str:
    return normalize_text(value).strip()


def _build_parsed_document(text: str) -> ParsedDocument:
    normalized = _normalize(text)
    return ParsedDocument(text_for_chunking=normalized, text_for_hashing=normalized)


def _require_docling() -> None:
    if DOCLING_IMPORT_ERROR is not None or DocumentConverter is None:
        raise ParserDependencyError(
            "Docling is unavailable. Install backend requirements before ingesting PDF, DOCX, or HTML documents."
        ) from DOCLING_IMPORT_ERROR


@lru_cache(maxsize=1)
def _default_docling_converter():
    _require_docling()
    return DocumentConverter()


def _build_ocr_options():
    engine = settings.pdf_ocr_engine.strip().lower()
    languages = settings.resolved_pdf_ocr_languages

    if engine in {"tesseract_cli", "tesseract-cli"}:
        executable = _resolve_tesseract_executable()
        ocr_options = TesseractCliOcrOptions(lang=_resolve_tesseract_languages(languages))
        _set_model_field_if_supported(ocr_options, "tesseract_cmd", executable)
        _set_model_field_if_supported(ocr_options, "force_full_page_ocr", settings.pdf_force_full_page_ocr)
        return ocr_options
    if engine == "tesseract":
        ocr_options = TesseractOcrOptions(lang=_resolve_tesseract_languages(languages))
        _set_model_field_if_supported(ocr_options, "force_full_page_ocr", settings.pdf_force_full_page_ocr)
        return ocr_options
    if engine == "easyocr":
        ocr_options = EasyOcrOptions(lang=languages)
        _set_model_field_if_supported(ocr_options, "force_full_page_ocr", settings.pdf_force_full_page_ocr)
        return ocr_options
    if engine == "rapidocr":
        ocr_options = RapidOcrOptions(lang=languages)
        _set_model_field_if_supported(ocr_options, "force_full_page_ocr", settings.pdf_force_full_page_ocr)
        return ocr_options
    raise ParserDependencyError(
        f"Unsupported PDF OCR engine '{settings.pdf_ocr_engine}'. "
        "Use one of: tesseract_cli, tesseract, easyocr, rapidocr."
    )


def _ensure_tesseract_cli_on_path() -> None:
    current_path = os.environ.get("PATH", "")
    path_entries = current_path.split(os.pathsep) if current_path else []
    if any((Path(entry) / "tesseract.exe").exists() for entry in path_entries if entry):
        return

    for directory in WINDOWS_TESSERACT_DIRS:
        if (directory / "tesseract.exe").exists():
            os.environ["PATH"] = f"{directory}{os.pathsep}{current_path}" if current_path else str(directory)
            return

    raise ParserDependencyError(
        "PDF OCR is enabled but Tesseract was not found. Install Tesseract OCR or switch to another OCR engine."
    )


def _resolve_tesseract_executable() -> str:
    _ensure_tesseract_cli_on_path()
    executable = shutil.which("tesseract")
    if not executable:
        raise ParserDependencyError(
            "PDF OCR is enabled but Tesseract was not found. Install Tesseract OCR or switch to another OCR engine."
    )
    return executable


def _resolve_tesseract_languages(requested_languages: list[str]) -> list[str]:
    executable_path = Path(_resolve_tesseract_executable()).resolve()
    tessdata_dir = executable_path.parent / "tessdata"
    if not tessdata_dir.exists():
        return requested_languages

    available_languages = {item.stem.lower() for item in tessdata_dir.glob("*.traineddata")}
    resolved_languages = [language for language in requested_languages if language.lower() in available_languages]
    if resolved_languages:
        return resolved_languages
    if "eng" in available_languages:
        return ["eng"]
    if available_languages:
        return [sorted(available_languages)[0]]
    return requested_languages


def _set_model_field_if_supported(model, field_name: str, value) -> None:
    model_fields = getattr(type(model), "model_fields", {})
    if field_name in model_fields:
        setattr(model, field_name, value)


@lru_cache(maxsize=1)
def _ocr_pdf_converter():
    _require_docling()
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = True
    _set_model_field_if_supported(pipeline_options, "force_full_page_ocr", settings.pdf_force_full_page_ocr)
    pipeline_options.ocr_options = _build_ocr_options()
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
        }
    )


def _convert_with_docling(path: str | Path, *, use_ocr: bool = False) -> str:
    converter = _ocr_pdf_converter() if use_ocr else _default_docling_converter()
    try:
        result = converter.convert(Path(path))
        document = result.document
        exported = document.export_to_markdown()
        return _normalize(exported)
    except ParserDependencyError:
        raise
    except Exception as exc:  # pragma: no cover - depends on parser backend/provider
        message = str(exc)
        if use_ocr and re.search(r"tesseract|easyocr|rapidocr|ocr", message, re.IGNORECASE):
            raise ParserDependencyError(
                "PDF OCR is enabled but the OCR backend is unavailable. "
                "Install and configure the selected OCR engine, then retry the upload."
            ) from exc
        action = "OCR-backed PDF parsing" if use_ocr else "Document parsing"
        raise DocumentExtractionError(f"{action} failed: {message}") from exc


def _run_tesseract_on_image(image_path: Path) -> str:
    output_base = image_path.with_suffix("")
    command = [
        _resolve_tesseract_executable(),
        str(image_path),
        str(output_base),
        "-l",
        "+".join(settings.resolved_pdf_ocr_languages) or "eng",
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip() or "Unknown OCR error"
        raise DocumentExtractionError(f"Tesseract OCR failed: {stderr}")
    text_path = output_base.with_suffix(".txt")
    return _read_text_file(text_path)


def _ocr_pdf_with_pypdfium(path: str | Path) -> str:
    if pypdfium2 is None:
        raise ParserDependencyError("pypdfium2 is unavailable for PDF page rasterization.")

    pdf = pypdfium2.PdfDocument(str(path))
    page_texts: list[str] = []
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            for page_index in range(len(pdf)):
                page = pdf[page_index]
                try:
                    rendered = page.render(scale=2)
                    image = rendered.to_pil()
                finally:
                    close_page = getattr(page, "close", None)
                    if callable(close_page):
                        close_page()

                image_path = Path(temp_dir) / f"page-{page_index + 1}.png"
                image.save(image_path, format="PNG")
                page_texts.append(_run_tesseract_on_image(image_path))
    finally:
        close_pdf = getattr(pdf, "close", None)
        if callable(close_pdf):
            close_pdf()

    return _normalize("\n\n".join(page_texts))


def _ocr_pdf_with_fitz(path: str | Path) -> str:
    if fitz is None:
        raise ParserDependencyError("PyMuPDF is unavailable for PDF page rasterization.")

    document = fitz.open(str(path))
    page_texts: list[str] = []
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            for page_index, page in enumerate(document, start=1):
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image_path = Path(temp_dir) / f"page-{page_index}.png"
                pixmap.save(str(image_path))
                page_texts.append(_run_tesseract_on_image(image_path))
    finally:
        document.close()

    return _normalize("\n\n".join(page_texts))


def _ocr_pdf_via_rasterization(path: str | Path) -> str:
    errors: list[str] = []
    for strategy in (_ocr_pdf_with_pypdfium, _ocr_pdf_with_fitz):
        try:
            text = strategy(path)
            if text:
                return text
        except DocumentParserError as exc:
            errors.append(str(exc))
        except Exception as exc:  # pragma: no cover - renderer-specific failure path
            errors.append(str(exc))

    if errors:
        raise DocumentExtractionError(f"Rasterized OCR fallback failed: {'; '.join(errors[:2])}")
    raise ParserDependencyError("No PDF rasterization backend is available for OCR fallback.")


def _parse_pdf(path: str | Path) -> ParsedDocument:
    base_text = ""
    base_error: DocumentParserError | None = None
    try:
        base_text = _convert_with_docling(path, use_ocr=False)
    except DocumentParserError as exc:
        base_error = exc

    if base_text and (not settings.pdf_ocr_enabled or len(base_text) >= settings.pdf_ocr_min_chars):
        return _build_parsed_document(base_text)

    if settings.pdf_ocr_enabled:
        ocr_errors: list[str] = []

        try:
            ocr_text = _convert_with_docling(path, use_ocr=True)
            if len(ocr_text) > len(base_text):
                return _build_parsed_document(ocr_text)
            if ocr_text and not base_text:
                return _build_parsed_document(ocr_text)
        except DocumentParserError as exc:
            ocr_errors.append(str(exc))

        try:
            rasterized_ocr_text = _ocr_pdf_via_rasterization(path)
            if len(rasterized_ocr_text) > len(base_text):
                return _build_parsed_document(rasterized_ocr_text)
            if rasterized_ocr_text and not base_text:
                return _build_parsed_document(rasterized_ocr_text)
        except DocumentParserError as exc:
            ocr_errors.append(str(exc))

        if base_text:
            return _build_parsed_document(base_text)
        if base_error is not None:
            if ocr_errors:
                raise DocumentExtractionError(f"{base_error} OCR fallback also failed: {'; '.join(ocr_errors[:2])}")
            raise base_error
        if ocr_errors:
            raise DocumentExtractionError(f"OCR fallback failed: {'; '.join(ocr_errors[:2])}")

    if base_text:
        return _build_parsed_document(base_text)
    if base_error is not None:
        raise base_error
    raise DocumentExtractionError("Unable to extract text from the PDF.")


def _parse_docling_document(path: str | Path) -> ParsedDocument:
    return _build_parsed_document(_convert_with_docling(path, use_ocr=False))


def parse_document_file(storage_path: str | Path, filename: str | None = None) -> ParsedDocument:
    resolved_name = filename or Path(storage_path).name
    ensure_supported_document_filename(resolved_name)
    suffix = Path(resolved_name).suffix.lower()

    try:
        if suffix in {".txt", ".md", ".markdown"}:
            return _build_parsed_document(_read_text_file(storage_path))
        if suffix in {".html", ".htm"}:
            raw_html = _read_text_file(storage_path)
            stripped_text = _strip_html(raw_html)
            if stripped_text:
                return _build_parsed_document(stripped_text)
            return _parse_docling_document(storage_path)
        if suffix == ".docx":
            return _parse_docling_document(storage_path)
        if suffix == ".pdf":
            return _parse_pdf(storage_path)
    except DocumentParserError:
        raise
    except FileNotFoundError as exc:
        raise DocumentExtractionError(f"Document file was not found: {storage_path}") from exc
    except Exception as exc:  # pragma: no cover - defensive parser wrapper
        raise DocumentExtractionError(f"Unable to extract text from {resolved_name}: {exc}") from exc

    raise UnsupportedDocumentFormatError(f"Unsupported file type '{suffix or 'unknown'}'")
