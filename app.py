from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templates import Jinja2Templates
from pathlib import Path
from pydantic import BaseModel
import re
from typing import List, Dict, Any, Optional

APP_ROOT = Path(__file__).resolve().parent
SOP_DIR = APP_ROOT / "data" / "sops" / "approved"

app = FastAPI(title="Foodies SOP RAG System")
app.mount("/static", StaticFiles(directory=str(APP_ROOT / "static")), name="static")

templates = Jinja2Templates(directory=str(APP_ROOT / "templates"))


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9]+", text.lower())


def parse_front_matter(text: str) -> Dict[str, str]:
    if not text.startswith("---\n"):
        return {}

    end_index = text.find("\n---\n", 4)
    if end_index == -1:
        return {}

    meta_block = text[4:end_index]
    metadata: Dict[str, str] = {}
    for line in meta_block.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip().lower()] = value.strip()
    return metadata


def split_sections(markdown: str) -> List[Dict[str, str]]:
    sections: List[Dict[str, str]] = []
    current_heading = "Overview"
    current_body: List[str] = []

    lines = markdown.splitlines()
    for line in lines:
        if line.startswith("#"):
            if current_body or current_heading:
                sections.append({
                    "heading": current_heading,
                    "body": "\n".join(current_body).strip()
                })
            current_heading = re.sub(r"^#+\s*", "", line).strip() or "Overview"
            current_body = []
        else:
            current_body.append(line)

    if current_body or current_heading:
        sections.append({
            "heading": current_heading,
            "body": "\n".join(current_body).strip()
        })

    return sections


def load_sops() -> List[Dict[str, Any]]:
    documents: List[Dict[str, Any]] = []
    if not SOP_DIR.exists():
        return documents

    for file_path in sorted(SOP_DIR.glob("**/*.md")):
        text = file_path.read_text(encoding="utf-8")
        metadata = parse_front_matter(text)
        content_without_front_matter = text
        if metadata:
            content_without_front_matter = text[text.find("\n---\n", 4) + 5:] if "\n---\n" in text else text

        if not metadata.get("status", "Approved").lower() == "approved":
            continue

        sections = split_sections(content_without_front_matter)
        for idx, section in enumerate(sections, start=1):
            section_text = " ".join([
                section.get("heading", ""),
                section.get("body", "")
            ]).strip()

            if not section_text:
                continue

            documents.append({
                "sop_id": metadata.get("id", file_path.stem.upper()),
                "title": metadata.get("title", file_path.stem.replace("-", " ").title()),
                "department": metadata.get("department", "General"),
                "owner": metadata.get("owner", "Operations"),
                "version": metadata.get("version", "1.0"),
                "status": metadata.get("status", "Approved"),
                "effective_date": metadata.get("effective_date", "N/A"),
                "approved_by": metadata.get("approved_by", "N/A"),
                "approved_date": metadata.get("approved_date", "N/A"),
                "section_heading": section.get("heading", f"Section {idx}"),
                "section_text": section_text,
                "source_path": str(file_path.relative_to(APP_ROOT)),
            })

    return documents


def score_section(question_tokens: List[str], section: Dict[str, Any]) -> float:
    text = (section.get("section_heading", "") + " " + section.get("section_text", "")).lower()
    content_tokens = tokenize(text)
    token_set = set(content_tokens)

    score = 0.0
    for token in question_tokens:
        if token in token_set:
            score += 2.0
    heading = section.get("section_heading", "").lower()
    for token in question_tokens:
        if token in heading:
            score += 4.0

    if len(question_tokens) > 0:
        overlap = sum(1 for token in question_tokens if token in token_set)
        score += overlap * 0.5

    return score


def retrieve_sops(question: str, department: Optional[str] = None) -> List[Dict[str, Any]]:
    docs = load_sops()
    q_tokens = tokenize(question)
    if not q_tokens:
        return []

    scored = []
    for section in docs:
        if department and section["department"].lower() != department.lower():
            continue
        score = score_section(q_tokens, section)
        if score > 0:
            scored.append({**section, "score": score})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:5]


def build_answer(question: str, department: Optional[str] = None) -> Dict[str, Any]:
    matches = retrieve_sops(question, department)
    if not matches:
        return {
            "answer": "I could not find a matching approved SOP in the Foodies SOP repository for that question. Please confirm the department or ask for a policy that is already approved and stored in the SOP library.",
            "citations": [],
            "department": department,
            "question": question,
        }

    best = matches[0]
    section_text = best["section_text"]
    summary = section_text[:450].replace("\n", " ")
    if len(section_text) > 450:
        summary += "..."

    answer = (
        f"According to {best['sop_id']} - {best['title']} ({best['department']}), "
        f"Section: {best['section_heading']}, the approved guidance is: {summary}"
    )

    citations = []
    for item in matches[:3]:
        citations.append({
            "sop_id": item["sop_id"],
            "title": item["title"],
            "department": item["department"],
            "section": item["section_heading"],
            "version": item["version"],
            "source": item["source_path"],
            "effective_date": item["effective_date"],
        })

    return {
        "answer": answer,
        "citations": citations,
        "department": department,
        "question": question,
    }


class QueryRequest(BaseModel):
    question: str
    department: Optional[str] = None


@app.get("/", response_class=HTMLResponse)
def home():
    return templates.TemplateResponse("index.html", {"request": {}})


@app.post("/api/query")
def query_sop(payload: QueryRequest):
    if not payload.question.strip():
        raise HTTPException(status_code=400, detail="Question is required.")

    result = build_answer(payload.question, payload.department)
    return result


@app.get("/api/health")
def health():
    return {"status": "ok", "approved_sops": len(load_sops())}


@app.get("/api/departments")
def departments():
    docs = load_sops()
    values = sorted({doc["department"] for doc in docs})
    return {"departments": values}


@app.get("/api/sops")
def list_sops():
    docs = load_sops()
    unique = []
    seen = set()
    for doc in docs:
        key = doc["sop_id"]
        if key not in seen:
            unique.append({
                "sop_id": doc["sop_id"],
                "title": doc["title"],
                "department": doc["department"],
                "version": doc["version"],
                "effective_date": doc["effective_date"],
                "status": doc["status"],
            })
            seen.add(key)
    return {"sops": unique}
