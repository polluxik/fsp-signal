"""One-page candidate-owned skill passport with explicit evidence provenance."""

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .matching import SKILL_NAMES
from .models import CandidateProfile


INK = HexColor("#201939")
MUTED = HexColor("#675F76")
ACCENT = HexColor("#6C39D5")
PALE = HexColor("#F4EFFD")


def _fonts() -> tuple[str, str]:
    choices = [
        (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")),
        (Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
         Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")),
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
         Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
    ]
    pair = next(((regular, bold) for regular, bold in choices if regular.exists() and bold.exists()), None)
    if pair is None:
        raise FileNotFoundError("PDF_FONT_UNAVAILABLE")
    if "FspRegular" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("FspRegular", str(pair[0])))
    if "FspBold" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("FspBold", str(pair[1])))
    return "FspRegular", "FspBold"


def _line(pdf: canvas.Canvas, text: str, x: float, y: float, font: str, size: int,
          width: float, color=INK) -> None:
    pdf.setFillColor(color)
    pdf.setFont(font, size)
    words = text.split()
    if not words:
        return
    output = words[0]
    truncated = False
    for word in words[1:]:
        candidate = f"{output} {word}"
        if pdfmetrics.stringWidth(candidate, font, size) > width:
            truncated = True
            break
        output = candidate
    while output and pdfmetrics.stringWidth(output + ("…" if truncated else ""), font, size) > width:
        output = output[:-1]
        truncated = True
    pdf.drawString(x, y, output + ("…" if truncated else ""))


def render_passport(profile: CandidateProfile) -> BytesIO:
    regular, bold = _fonts()
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4)
    pdf.setTitle("Паспорт навыков — ФСП Сигнал")
    pdf.setAuthor("ФСП Сигнал")
    width, height = A4
    synthetic = profile.verification_source == "synthetic_fixture"

    pdf.setFillColor(INK)
    pdf.rect(0, height-177, width, 177, fill=1, stroke=0)
    _line(pdf, "ФСП  СИГНАЛ", 42, height-48, bold, 14, 320, HexColor("#FFFFFF"))
    _line(pdf, "ПАСПОРТ НАВЫКОВ", 42, height-102, bold, 24, 500, HexColor("#FFFFFF"))
    _line(pdf, "Категория по результату практической проверки", 42, height-131,
          regular, 11, 500, HexColor("#DAD0F2"))

    pdf.setFillColor(PALE)
    pdf.roundRect(42, 548, width-84, 91, 14, fill=1, stroke=0)
    _line(pdf, "УЧЕБНАЯ КАТЕГОРИЯ" if synthetic else "ПОДТВЕРЖДЁННАЯ КАТЕГОРИЯ",
          60, 608, bold, 9, 330, ACCENT)
    category = (f"{profile.verified_specialization or 'не определена'}  /  "
                f"{profile.verified_grade or '—'}").upper()
    _line(pdf, category, 60, 575, bold, 19, 330)
    pdf.setFillColor(ACCENT)
    pdf.setFont(bold, 26)
    pdf.drawRightString(width-61, 577, str(profile.test_score) if profile.test_score is not None else "—")
    _line(pdf, "/ 100", width-104, 560, regular, 9, 45, MUTED)

    _line(pdf, "ПРОФИЛЬ", 42, 510, bold, 10, 500, ACCENT)
    _line(pdf, profile.full_name or "Имя не указано", 42, 480, bold, 17, width-84)
    details = " · ".join(item for item in (profile.city, profile.work_format) if item)
    _line(pdf, details, 42, 456, regular, 10, width-84, MUTED)
    _line(pdf, "Контакт кандидата: " + (profile.contact_email or "не указан"),
          42, 434, regular, 10, width-84)

    heading = "УЧЕБНЫЕ КОМПЕТЕНЦИИ" if synthetic else "ПРОВЕРЕННЫЕ КОМПЕТЕНЦИИ"
    _line(pdf, heading, 42, 390, bold, 10, 500, ACCENT)
    items = sorted((profile.competencies or {}).items(), key=lambda pair: (-pair[1], pair[0]))[:4]
    if not items:
        _line(pdf, "Данных пока нет", 42, 360, regular, 10, 400, MUTED)
    for index, (skill, value) in enumerate(items):
        y = 359-index*35
        _line(pdf, SKILL_NAMES.get(skill, skill), 42, y, regular, 10, 275)
        pdf.setFillColor(PALE)
        pdf.roundRect(355, y-2, 146, 9, 4.5, fill=1, stroke=0)
        pdf.setFillColor(ACCENT)
        pdf.roundRect(355, y-2, 146*max(0.0, min(float(value), 1.0)), 9, 4.5, fill=1, stroke=0)
        _line(pdf, f"{round(float(value)*100)}%", 510, y, bold, 9, 48, ACCENT)

    _line(pdf, "ЗАЯВЛЕННЫЕ НАВЫКИ", 42, 194, bold, 10, 500, ACCENT)
    declared = ", ".join(profile.skills or []) or "Не указаны"
    _line(pdf, declared, 42, 170, regular, 10, width-84)

    pdf.setStrokeColor(HexColor("#E5DDF3"))
    pdf.line(42, 132, width-42, 132)
    origin = ("Синтетический профиль для демонстрации. Балл не является результатом человека."
              if synthetic else "Оценка получена в тесте ФСП Сигнал; результат привязан к указанной категории.")
    _line(pdf, origin, 42, 112, regular, 9, width-84, MUTED)
    fsp = ("Демо-достижение" if profile.fsp_status == "mock" else
           "Подтверждённое достижение" if profile.fsp_status == "verified_external" else
           "История ФСП не подтверждена")
    _line(pdf, f"ФСП: {fsp}", 42, 94, regular, 9, width-84, MUTED)
    date = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    _line(pdf, f"Сформировано {date} · Личная выгрузка кандидата", 42, 55, regular, 9, width-84, MUTED)
    pdf.showPage()
    pdf.save()
    output.seek(0)
    return output
