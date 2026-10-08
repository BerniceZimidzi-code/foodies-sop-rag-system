import hashlib
import io
import re
import uuid
import zipfile
from pathlib import Path
from typing import Any

from docx import Document
from fastapi import UploadFile
from pypdf import PdfReader
from yaml import YAMLError

from backend.sops import parse_front_matter, split_sections


APP_ROOT = Path(__file__).resolve().parent.parent
UPLOAD_DIR = APP_ROOT / "data" / "uploads"
SUPPORTED_EXTENSIONS = {".md", ".pdf", ".docx"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_EXTRACTED_CHARACTERS = 2_000_000
MAX_PDF_PAGES = 500
MAX_DOCX_EXPANDED_BYTES = 50 * 1024 * 1024
MAX_CHUNK_CHARACTERS = 1400


class IngestionError(ValueError):
    pass


async def read_upload(upload: UploadFile) -> bytes:
    content = bytearray()
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > MAX_UPLOAD_BYTES:
            raise IngestionError("The uploaded file exceeds the 15 MB size limit.")
    if not content:
        raise IngestionError("The uploaded file is empty.")
    return bytes(content)


def ingest_document(filename: str, content: bytes) -> list[dict[str, str]]:
    extension = Path(filename).suffix.casefold()
    if extension not in SUPPORTED_EXTENSIONS:
        raise IngestionError("Upload a Markdown (.md), PDF (.pdf), or Word (.docx) file.")

    try:
        if extension == ".md":
            text = _markdown_text(content)
        elif extension == ".pdf":
            text = _pdf_text(content)
        else:
            text = _docx_text(content)
    except IngestionError:
        raise
    except (UnicodeError, zipfile.BadZipFile, OSError, ValueError) as exc:
        raise IngestionError("The file could not be read. Check that it is a valid document.") from exc

    if len(text) > MAX_EXTRACTED_CHARACTERS:
        raise IngestionError("The extracted document text exceeds the 2 MB character limit.")
    sections = split_sections(text)
    chunks: list[dict[str, str]] = []
    for section in sections:
        chunks.extend(_split_section(section["heading"], section["body"]))
    if not chunks:
        raise IngestionError(
            "No readable text or headings were found. Scanned PDFs need OCR before upload."
        )
    return chunks


def save_original(filename: str, content: bytes) -> Path:
    extension = Path(filename).suffix.casefold()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = UPLOAD_DIR / f"{uuid.uuid4().hex}{extension}"
    target.write_bytes(content)
    return target


def content_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _markdown_text(content: bytes) -> str:
    text = content.decode("utf-8-sig")
    if "\x00" in text:
        raise IngestionError("The Markdown file contains invalid binary data.")
    if text.lstrip().startswith("---"):
        try:
            parsed = parse_front_matter(text)
        except YAMLError as exc:
            raise IngestionError("The Markdown YAML front matter is invalid.") from exc
        if parsed is None:
            raise IngestionError("The Markdown YAML front matter is not closed correctly.")
        return parsed[1]
    return text


def _pdf_text(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content), strict=True)
    if reader.is_encrypted:
        raise IngestionError("Password-protected PDFs are not supported.")
    if len(reader.pages) > MAX_PDF_PAGES:
        raise IngestionError("PDFs may contain no more than 500 pages.")
    page_text = []
    for page_number, page in enumerate(reader.pages, start=1):
        extracted = page.extract_text()
        if extracted and extracted.strip():
            page_text.append(f"## Page {page_number}\n\n{extracted.strip()}")
    if not page_text:
        raise IngestionError(
            "No selectable text was found in this PDF. Scanned PDFs need OCR before upload."
        )
    return "\n\n".join(page_text)


def _docx_text(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        entries = archive.infolist()
        if len(entries) > 1000 or sum(item.file_size for item in entries) > MAX_DOCX_EXPANDED_BYTES:
            raise IngestionError("The Word document expands beyond the allowed size.")
        if "word/document.xml" not in archive.namelist():
            raise IngestionError("The file is not a valid Word document.")

    document = Document(io.BytesIO(content))
    lines = []
    for paragraph in document.paragraphs:
        value = paragraph.text.strip()
        if not value:
            continue
        style_name = paragraph.style.name.casefold() if paragraph.style else ""
        if style_name.startswith("heading"):
            level = re.search(r"\d+", style_name)
            prefix = "#" * min(int(level.group()) if level else 2, 6)
            lines.append(f"{prefix} {value}")
        else:
            lines.append(value)
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                lines.append(" | ".join(cells))
    if not lines:
        raise IngestionError("No readable text was found in this Word document.")
    return "\n\n".join(lines)


def _split_section(heading: str, body: str) -> list[dict[str, str]]:
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", body) if paragraph.strip()]
    chunks: list[dict[str, str]] = []
    current = ""

    def append_chunk(value: str) -> None:
        if value:
            chunks.append({"heading": heading, "content": value})

    for paragraph in paragraphs:
        if len(paragraph) > MAX_CHUNK_CHARACTERS:
            if current:
                append_chunk(current)
                current = ""
            words = paragraph.split()
            part = ""
            for word in words:
                if len(word) > MAX_CHUNK_CHARACTERS:
                    if part:
                        append_chunk(part)
                        part = ""
                    for offset in range(0, len(word), MAX_CHUNK_CHARACTERS):
                        append_chunk(word[offset:offset + MAX_CHUNK_CHARACTERS])
                    continue
                candidate = f"{part} {word}".strip()
                if len(candidate) > MAX_CHUNK_CHARACTERS:
                    append_chunk(part)
                    part = word
                else:
                    part = candidate
            if part:
                current = part
            continue

        candidate = f"{current}\n\n{paragraph}".strip()
        if current and len(candidate) > MAX_CHUNK_CHARACTERS:
            append_chunk(current)
            current = paragraph
        else:
            current = candidate

    if current:
        append_chunk(current)
    return chunks


def metadata_for_storage(metadata: dict[str, Any]) -> dict[str, str]:
    return {key: str(value) for key, value in metadata.items()}
