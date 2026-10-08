from typing import Any, Protocol


MISSING_ANSWER = (
    "I could not find this in the approved SOP repository. Please ask your "
    "manager to have the relevant policy reviewed or added."
)


class AnswerProvider(Protocol):
    def generate(
        self,
        question: str,
        sources: list[dict[str, Any]],
    ) -> str: ...


class ExtractiveAnswerProvider:
    def generate(
        self,
        question: str,
        sources: list[dict[str, Any]],
    ) -> str:
        del question
        best = sources[0]
        return (
            f"According to {best['sop_id']} - {best['title']}, Section "
            f"{best['section_heading']} (version {best['version']}), "
            f"{best['section_text'].strip()}"
        )


def answer_question(
    question: str,
    department: str | None,
    matches: list[dict[str, Any]],
    provider: AnswerProvider | None = None,
) -> dict[str, Any]:
    if not matches:
        return {
            "answer": MISSING_ANSWER,
            "citations": [],
            "department": department,
            "question": question,
            "missing_sop": True,
        }

    sources = matches[:3]
    answer = (provider or ExtractiveAnswerProvider()).generate(question, sources)
    if not answer.strip():
        raise RuntimeError("The answer provider returned an empty answer.")

    citations = [
        {
            "sop_id": item["sop_id"],
            "title": item["title"],
            "department": item["department"],
            "section": item["section_heading"],
            "version": item["version"],
            "source": item["source_path"],
            "effective_date": item["effective_date"],
        }
        for item in sources
    ]
    return {
        "answer": answer,
        "citations": citations,
        "department": department,
        "question": question,
        "missing_sop": False,
    }
