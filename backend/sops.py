import logging
import re
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from backend.database import list_approved_sop_sections


APP_ROOT = Path(__file__).resolve().parent.parent
SOP_DIR = APP_ROOT / "data" / "sops" / "approved"
LOGGER = logging.getLogger(__name__)
STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "before", "by", "can", "do",
    "for", "from", "how", "i", "in", "is", "it", "me", "of", "on", "or",
    "should", "staff", "the", "this", "to", "what", "when", "where", "which",
    "who", "why", "with",
}
def tokenize(text: str) -> list[str]:
    normalized: list[str] = []
    for token in re.findall(r"[a-z0-9]+", text.casefold()):
        if len(token) <= 1 or token in STOP_WORDS:
            continue
        if token.endswith("ies") and len(token) > 4 and token not in {"movies", "series", "species"}:
            token = token[:-3] + "y"
        elif token.endswith(("ches", "shes", "xes", "zes")):
            token = token[:-2]
        elif (
            token.endswith("s")
            and len(token) > 4
            and not token.endswith(("ss", "us", "is", "sis"))
        ):
            token = token[:-1]
        normalized.append(token)
    return normalized


def parse_front_matter(text: str) -> tuple[dict[str, Any], str] | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    try:
        end_index = next(
            index for index in range(1, len(lines)) if lines[index].strip() == "---"
        )
    except StopIteration:
        return None

    metadata = yaml.safe_load("\n".join(lines[1:end_index]))
    if not isinstance(metadata, dict):
        return None
    normalized = {str(key).strip().casefold(): value for key, value in metadata.items()}
    return normalized, "\n".join(lines[end_index + 1 :])


def split_sections(markdown: str) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    heading = "Overview"
    body: list[str] = []
    for line in markdown.splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if match:
            if "\n".join(body).strip():
                sections.append({"heading": heading, "body": "\n".join(body).strip()})
            heading = match.group(1).strip()
            body = []
        else:
            body.append(line)
    if "\n".join(body).strip():
        sections.append({"heading": heading, "body": "\n".join(body).strip()})
    return sections


def load_sops(department: str | None = None) -> list[dict[str, Any]]:
    if not SOP_DIR.is_dir():
        raise FileNotFoundError(f"Approved SOP directory does not exist: {SOP_DIR}")
    today = datetime.now(timezone.utc).date()
    by_sop_id: dict[str, dict[str, Any]] = {}
    for file_path in sorted(SOP_DIR.glob("**/*.md")):
        try:
            parsed = parse_front_matter(file_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            LOGGER.error("Unable to read SOP document %s: %s", file_path, exc)
            continue
        if parsed is None:
            LOGGER.warning("Skipping SOP without valid YAML front matter: %s", file_path)
            continue

        metadata, markdown = parsed
        if str(metadata.get("status", "")).strip().casefold() != "approved":
            continue
        required = ("id", "title", "department", "version", "effective_date")
        if any(not str(metadata.get(key, "")).strip() for key in required):
            LOGGER.warning("Skipping SOP with incomplete required metadata: %s", file_path)
            continue
        try:
            effective_date_value = metadata["effective_date"]
            if isinstance(effective_date_value, datetime):
                effective_date = effective_date_value.date()
            elif isinstance(effective_date_value, date):
                effective_date = effective_date_value
            else:
                effective_date = date.fromisoformat(str(effective_date_value))
        except (TypeError, ValueError):
            LOGGER.warning("Skipping SOP with invalid effective_date: %s", file_path)
            continue
        if effective_date > today:
            continue

        sop_department = str(metadata["department"]).strip()
        if department and sop_department.casefold() != department.casefold():
            continue

        sections = split_sections(markdown)
        if not sections:
            LOGGER.warning("Skipping approved SOP with no content sections: %s", file_path)
            continue

        document = {
            "sop_id": str(metadata["id"]).strip(),
            "title": str(metadata["title"]).strip(),
            "department": sop_department,
            "owner": str(metadata.get("owner", "")).strip(),
            "version": str(metadata["version"]).strip(),
            "status": "Approved",
            "effective_date": effective_date.isoformat(),
            "approved_by": str(metadata.get("approved_by", "")).strip(),
            "approved_date": str(metadata.get("approved_date", "")).strip(),
            "source_path": str(file_path.relative_to(APP_ROOT)),
            "effective_date_sort": effective_date,
            "version_sort": tuple(
                int(part) for part in re.findall(r"\d+", str(metadata["version"]))
            ),
            "sections": sections,
        }
        current = by_sop_id.get(document["sop_id"])
        if current is None or (
            document["effective_date_sort"], document["version_sort"]
        ) > (
            current["effective_date_sort"], current["version_sort"]
        ):
            by_sop_id[document["sop_id"]] = document
        elif current["version"] == document["version"]:
            LOGGER.warning(
                "Multiple approved files have the same SOP ID and version: %s %s",
                document["sop_id"],
                document["version"],
            )

    flattened: list[dict[str, Any]] = []
    for document in by_sop_id.values():
        public_document = {
            key: value
            for key, value in document.items()
            if key not in {"sections", "effective_date_sort", "version_sort"}
        }
        for section in document["sections"]:
            flattened.append(
                {
                    **public_document,
                    "section_heading": section["heading"],
                    "section_text": section["body"],
                }
            )
    return flattened


def get_departments() -> list[str]:
    database_documents = list_approved_sop_sections()
    database_sop_ids = {document["sop_id"] for document in database_documents}
    repository_documents = [
        document for document in load_sops()
        if document["sop_id"] not in database_sop_ids
    ]
    return sorted({
        document["department"]
        for document in [*database_documents, *repository_documents]
    })


def retrieve_sops(
    question: str,
    department: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    query_terms = list(dict.fromkeys(tokenize(question)))
    if not query_terms:
        return []

    database_documents = list_approved_sop_sections()
    if department:
        database_documents = [
            doc for doc in database_documents
            if doc["department"].casefold() == department.casefold()
        ]
    database_sop_ids = {document["sop_id"] for document in database_documents}
    repository_documents = [
        document for document in load_sops(department)
        if document["sop_id"] not in database_sop_ids
    ]
    documents = [*database_documents, *repository_documents]
    if not documents:
        return []

    doc_terms = [
        tokenize(
            document["title"]
            + " "
            + str(document.get("section_heading", ""))
            + " "
            + str(document.get("section_text", ""))
        )
        for document in documents
    ]
    document_frequency: Counter[str] = Counter()
    for terms in doc_terms:
        document_frequency.update(set(terms))
    average_length = sum(map(len, doc_terms)) / len(doc_terms) or 1
    scored: list[dict[str, Any]] = []

    for document, terms in zip(documents, doc_terms):
        frequencies = Counter(terms)
        matched_terms = [term for term in query_terms if frequencies[term]]
        coverage = len(matched_terms) / len(query_terms)
        if not matched_terms or coverage < 0.2:
            continue

        heading_terms = set(tokenize(str(document.get("section_heading", ""))))
        score = 0.0
        for term in matched_terms:
            frequency = frequencies[term]
            inverse_frequency = 1 + (
                (len(documents) - document_frequency[term] + 0.5)
                / (document_frequency[term] + 0.5)
            )
            length_normalizer = 1.2 * (0.25 + 0.75 * len(terms) / average_length)
            score += inverse_frequency * (frequency * 2.2 / (frequency + length_normalizer))
            if term in heading_terms:
                score += inverse_frequency * 1.5
        score += coverage
        scored.append({**document, "score": score})

    scored.sort(
        key=lambda item: (
            -item["score"],
            item.get("source_path", ""),
            item.get("section_heading", ""),
        )
    )
    return scored[:limit]

