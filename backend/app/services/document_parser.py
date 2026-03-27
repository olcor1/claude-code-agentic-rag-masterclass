from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile


SUPPORTED_DOCUMENT_EXTENSIONS = (".txt", ".md", ".html", ".docx", ".pdf")


class DocumentParserError(RuntimeError):
    pass


class UnsupportedDocumentFormatError(DocumentParserError):
    pass


class ParserDependencyError(DocumentParserError):
    pass


class DocumentExtractionError(DocumentParserError):
    pass


@dataclass(frozen=True)
class ParsedDocument:
    text_for_hashing: str
    text_for_chunking: str
    source_extension: str
    parser_name: str


class _HTMLTextExtractor(HTMLParser):
    _BLOCK_TAGS = {
        "article",
        "aside",
        "blockquote",
        "br",
        "div",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "p",
        "section",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        if tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        if tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        if data:
            self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def describe_supported_document_extensions() -> str:
    return ", ".join(SUPPORTED_DOCUMENT_EXTENSIONS)


def get_document_extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def ensure_supported_document_filename(filename: str) -> str:
    extension = get_document_extension(filename)
    if extension in SUPPORTED_DOCUMENT_EXTENSIONS:
        return extension
    raise UnsupportedDocumentFormatError(
        f"Unsupported file type '{extension or '[none]'}'. Supported file types: {describe_supported_document_extensions()}"
    )


def parse_document_file(storage_path: str, filename: str | None = None) -> ParsedDocument:
    path = Path(storage_path)
    if not path.exists():
        raise FileNotFoundError(storage_path)

    resolved_name = filename or path.name
    extension = ensure_supported_document_filename(resolved_name)

    if extension in {".txt", ".md"}:
        return _parse_text_file(path, extension)
    if extension == ".html":
        try:
            return _parse_with_docling(path, extension)
        except (ParserDependencyError, DocumentExtractionError):
            return _parse_html_file(path, extension)
    if extension == ".docx":
        try:
            return _parse_with_docling(path, extension)
        except (ParserDependencyError, DocumentExtractionError):
            return _parse_docx_file(path, extension)
    if extension == ".pdf":
        return _parse_with_docling(path, extension)

    raise UnsupportedDocumentFormatError(
        f"Unsupported file type '{extension}'. Supported file types: {describe_supported_document_extensions()}"
    )


def _build_parsed_document(*, content: str, source_extension: str, parser_name: str) -> ParsedDocument:
    if not content.strip():
        raise DocumentExtractionError("The uploaded document does not contain any extractable text")
    return ParsedDocument(
        text_for_hashing=content,
        text_for_chunking=content,
        source_extension=source_extension,
        parser_name=parser_name,
    )


def _parse_text_file(path: Path, extension: str) -> ParsedDocument:
    try:
        content = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DocumentExtractionError("Text and markdown uploads must be UTF-8 encoded") from exc
    return _build_parsed_document(content=content, source_extension=extension, parser_name="native-text")


def _parse_html_file(path: Path, extension: str) -> ParsedDocument:
    try:
        content = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DocumentExtractionError("HTML uploads must be UTF-8 encoded") from exc

    parser = _HTMLTextExtractor()
    parser.feed(content)
    parser.close()
    return _build_parsed_document(content=parser.get_text(), source_extension=extension, parser_name="native-html")


def _parse_docx_file(path: Path, extension: str) -> ParsedDocument:
    try:
        with ZipFile(path) as archive:
            xml_payload = archive.read("word/document.xml")
    except FileNotFoundError:
        raise
    except (BadZipFile, KeyError) as exc:
        raise DocumentExtractionError("DOCX upload is missing readable document content") from exc

    try:
        root = ElementTree.fromstring(xml_payload)
    except ElementTree.ParseError as exc:
        raise DocumentExtractionError("DOCX upload contains invalid XML content") from exc

    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        fragments = [node.text for node in paragraph.findall(".//w:t", namespace) if node.text]
        if fragments:
            paragraphs.append("".join(fragments))

    return _build_parsed_document(
        content="\n\n".join(paragraphs),
        source_extension=extension,
        parser_name="native-docx",
    )


@lru_cache(maxsize=1)
def _get_docling_converter():
    try:
        from docling.document_converter import DocumentConverter
    except Exception as exc:  # pragma: no cover - optional dependency
        raise ParserDependencyError(
            "This file type requires Docling. Install backend requirements and retry."
        ) from exc
    return DocumentConverter()


def _parse_with_docling(path: Path, extension: str) -> ParsedDocument:
    converter = _get_docling_converter()
    try:
        result = converter.convert(str(path))
        document = result.document
        content = document.export_to_markdown()
    except ParserDependencyError:
        raise
    except Exception as exc:
        raise DocumentExtractionError(f"Failed to parse {extension} document: {exc}") from exc

    return _build_parsed_document(content=content, source_extension=extension, parser_name="docling")
