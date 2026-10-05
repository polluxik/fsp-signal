"""Small, reviewable PDF-to-profile draft; extracted text is never persisted."""

from io import BytesIO
import re

from pypdf import PdfReader


MAX_PDF_BYTES = 5 * 1024 * 1024
MAX_PAGES = 10
SKILL_TERMS = (
    "Python", "Java", "Go", "C#", "JavaScript", "TypeScript", "React", "Vue",
    "Node.js", "FastAPI", "Django", "PostgreSQL", "MySQL", "Redis", "Docker",
    "Kubernetes", "Git", "SQL", "HTML", "CSS", "REST", "GraphQL", "Linux",
)


class ResumeImportError(ValueError):
    pass


def preview_pdf(content: bytes) -> dict:
    if len(content) > MAX_PDF_BYTES:
        raise ResumeImportError("PDF_TOO_LARGE")
    if not content.startswith(b"%PDF-"):
        raise ResumeImportError("NOT_A_PDF")
    try:
        reader = PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise ResumeImportError("PDF_ENCRYPTED")
        if not 1 <= len(reader.pages) <= MAX_PAGES:
            raise ResumeImportError("PDF_PAGE_LIMIT")
        pages = [page.extract_text(extraction_mode="plain") or "" for page in reader.pages]
    except ResumeImportError:
        raise
    except Exception as exc:
        raise ResumeImportError("PDF_UNREADABLE") from exc

    text = re.sub(r"[\x00-\x08\x0b-\x1f]", " ", "\n".join(pages))
    text = re.sub(r"[ \t]+", " ", text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(" ".join(lines)) < 40:
        raise ResumeImportError("PDF_TEXT_NOT_FOUND")

    email_match = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, re.I)
    phone_match = re.search(r"(?<!\d)(?:\+7|8)[\s(.-]*\d{3}[)\s.-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}(?!\d)", text)
    name = next((line for line in lines[:12]
                 if 2 <= len(line.split()) <= 4 and len(line) <= 100
                 and re.fullmatch(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё .'-]+", line)
                 and not any(word in line.lower() for word in ("резюме", "resume", "опыт работы", "разработчик"))), "")
    skills = [skill for skill in SKILL_TERMS if re.search(r"(?<![\w])" + re.escape(skill) + r"(?![\w])", text, re.I)]
    experience = re.search(r"(?:опыт(?: работы)?|experience)\D{0,25}(\d{1,2})\s*(?:лет|года|год|years?)", text, re.I)
    warnings = ["Проверьте извлечённые поля перед сохранением. Исходный PDF не сохраняется."]
    if not name:
        warnings.append("Имя не найдено — введите вручную.")
    if not skills:
        warnings.append("Навыки не распознаны — добавьте вручную.")
    return {
        "full_name": name,
        "contact_email": email_match.group(0) if email_match else "",
        "contact_phone": phone_match.group(0) if phone_match else "",
        "summary": "\n".join(lines)[:4000],
        "skills": skills,
        "experience_months": int(experience.group(1)) * 12 if experience else 0,
        "warnings": warnings,
        "pages": len(reader.pages),
    }
