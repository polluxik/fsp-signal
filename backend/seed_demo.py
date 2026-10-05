"""Deterministic synthetic fixtures. Never run against real user data."""

from datetime import timedelta
import random

from sqlalchemy import select

from .assessment import COMPETENCIES
from .config import settings
from .db import SessionLocal
from .models import CandidateProfile, EmployerProfile, HiringNeed, RoleVersion, User, now
from .role_cards import create_role_version, publish_role
from .schemas import RoleCardIn
from .security import hasher


def seed() -> None:
    if settings.app_mode != "demo":
        raise SystemExit("Synthetic seed is allowed only in APP_MODE=demo")
    rng = random.Random(20261005)
    with SessionLocal() as db:
        employer = db.scalar(select(User).where(User.email == "employer@demo.test"))
        if employer is None:
            employer = User(email="employer@demo.test", password_hash=hasher.hash("DemoPass123!"),
                            role="employer", origin="synthetic_fixture", email_verified_at=now())
            db.add(employer); db.flush()
        else:
            employer.origin = "synthetic_fixture"
        if db.get(EmployerProfile, employer.id) is None:
            db.add(EmployerProfile(user_id=employer.id, company_name="Сигнал Финтех [демо]",
                                   description="Учебная компания: обработка событий и пользовательские кабинеты",
                                   industry="ИТ", contact_email="team@demo.test"))

        second = db.scalar(select(User).where(User.email == "other@demo.test"))
        if second is None:
            second = User(email="other@demo.test", password_hash=hasher.hash("DemoPass123!"),
                          role="employer", origin="synthetic_fixture", email_verified_at=now())
            db.add(second); db.flush()
            db.add(EmployerProfile(user_id=second.id, company_name="Другая компания [демо]",
                                   description="Контроль границы доступа", industry="ИТ", contact_email="other@demo.test"))
        else:
            second.origin = "synthetic_fixture"

        need = db.scalar(select(HiringNeed).where(HiringNeed.employer_id == employer.id,
                                                  HiringNeed.title == "Backend Middle: события"))
        if need is None:
            need = HiringNeed(employer_id=employer.id, title="Backend Middle: события",
                              description="Обработка повторных платёжных событий без двойной записи",
                              specialization="backend", grade="middle",
                              competencies=["event_idempotency", "data_integrity"], stack=["Python", "PostgreSQL"],
                              salary_min_rub=180000, salary_max_rub=230000, work_format="remote")
            db.add(need)
            db.flush()

        current = db.scalar(select(RoleVersion).where(
            RoleVersion.need_id == need.id, RoleVersion.version == need.current_role_version
        )) if need.current_role_version else None
        if not current or current.source != "synthetic_demo" or need.publication_state != "active":
            card = RoleCardIn.model_validate({
                "title": need.title, "description": need.description,
                "specialization": "backend", "grade": "middle",
                "competencies": ["event_idempotency", "data_integrity"],
                "stack": ["Python", "PostgreSQL"],
                "salary_min_rub": 180000, "salary_max_rub": 230000,
                "work_format": "remote", "work_city": None,
                "first_30_days": "Убрать повторную обработку платёжных событий без двойной записи.",
                "interview_steps": [
                    {"title": "Знакомство и опыт", "duration_minutes": 45},
                    {"title": "Разбор рабочей задачи", "duration_minutes": 60},
                ],
                "take_home_minutes": 0, "response_sla_hours": 48,
                "employer_contact": "team@demo.test", "active_headcount_attested": True,
            })
            role_version = create_role_version(db, employer.id, need.id, card,
                                               need.current_role_version, now(), source="synthetic_demo")
            publish_role(db, employer.id, need.id, expected_version=role_version.version,
                         active_headcount_attested=True, discoverable=True, at=now())

        for category, skills in COMPETENCIES.items():
            specialization, grade = category.split(":")
            for index in range(12):
                email = f"{specialization}-{grade}-{index+1}@demo.test"
                user = db.scalar(select(User).where(User.email == email))
                if user is not None:
                    user.origin = "synthetic_fixture"
                    profile = db.get(CandidateProfile, user.id)
                    if profile and profile.adult_attested_at is None:
                        profile.adult_attested_at = now()
                    continue
                user = User(email=email, password_hash=hasher.hash("DemoPass123!"),
                            role="candidate", origin="synthetic_fixture", email_verified_at=now())
                db.add(user); db.flush()
                base = 0.58 + index * .035
                competencies = {name: round(min(.96, max(.5, base + rng.uniform(-.09, .09))), 3) for name in skills}
                score = min(98, round(sum(competencies.values())/3*100))
                if score < 70:
                    score = 70
                fsp = "mock" if index in (2, 6, 10) else "unlinked"
                profile = CandidateProfile(
                    user_id=user.id, full_name=f"Демо кандидат {index+1}", contact_email=email,
                    contact_phone=f"+7000000{index:04d}", city="Москва",
                    summary="Синтетический профиль для демонстрации подборки.",
                    skills=["Python", "PostgreSQL"] if specialization == "backend" else ["TypeScript", "React"],
                    experience_months=(index+4)*5, min_salary_rub=90000 if grade == "junior" else 170000,
                    work_format="remote", consent_processing_at=now(), published_at=now(), available=True,
                    adult_attested_at=now(),
                    desired_specialization=specialization, claimed_grade=grade,
                    verified_specialization=specialization, verified_grade=grade, test_score=score,
                    verification_source="synthetic_fixture", competencies=competencies,
                    test_verified_at=now()-timedelta(days=index*5), grade_changed_at=now()-timedelta(days=35),
                    fsp_id=f"demo-{user.id}" if fsp == "mock" else None,
                    fsp_status=fsp, fsp_result="finalist" if fsp == "mock" else None)
                db.add(profile)
        db.commit()
    print("Seed ready: two employers, 48 synthetic candidates, one hiring need.")
    print("Demo accounts: employer@demo.test / DemoPass123!, other@demo.test / DemoPass123!")
    print("Register a new candidate to demonstrate a real assessment.")


if __name__ == "__main__":
    seed()
