"""Deterministic synthetic fixtures. Never run against real user data."""

from datetime import timedelta
import random

from sqlalchemy import select

from .assessment import COMPETENCIES
from .config import settings
from .db import SessionLocal
from .models import CandidateProfile, EmployerProfile, HiringNeed, RoleDecision, RoleVersion, User, now
from .role_cards import create_role_version, publish_role
from .schemas import RoleCardIn
from .security import hasher


DISCOVERY_ROLE_FIXTURES = (
    {
        "title": "Backend Junior: полезные API",
        "description": "Развивать API кабинета и разбирать реальные ошибки валидации.",
        "specialization": "backend", "grade": "junior",
        "competencies": ["data_trace", "validation", "http_api"],
        "stack": ["Python", "FastAPI"], "salary_min_rub": 100000, "salary_max_rub": 140000,
        "work_format": "remote", "work_city": None,
        "first_30_days": "Добавить понятную валидацию в один пользовательский сценарий.",
        "industry": "ИТ", "take_home_minutes": 0,
    },
    {
        "title": "Backend Middle: платёжные события",
        "description": "Убрать повторную обработку платежей и улучшить восстановление после сбоев.",
        "specialization": "backend", "grade": "middle",
        "competencies": ["event_idempotency", "data_integrity", "failure_recovery"],
        "stack": ["Python", "PostgreSQL"], "salary_min_rub": 190000, "salary_max_rub": 250000,
        "work_format": "hybrid", "work_city": "Москва",
        "first_30_days": "Согласовать безопасную обработку повторных событий.",
        "industry": "Финтех", "take_home_minutes": 0,
    },
    {
        "title": "Frontend Junior: интерфейс кабинета",
        "description": "Собирать доступные формы и исправлять несогласованные состояния интерфейса.",
        "specialization": "frontend", "grade": "junior",
        "competencies": ["javascript_trace", "ui_state", "forms"],
        "stack": ["TypeScript", "React"], "salary_min_rub": 110000, "salary_max_rub": 150000,
        "work_format": "office", "work_city": "Казань",
        "first_30_days": "Упростить одну форму и добавить обработку ошибок отправки.",
        "industry": "ИТ", "take_home_minutes": 30,
    },
    {
        "title": "Frontend Middle: надёжные сценарии",
        "description": "Улучшить отзывчивость кабинета и защитить запросы от гонок и потери состояния.",
        "specialization": "frontend", "grade": "middle",
        "competencies": ["request_races", "derived_state", "error_recovery"],
        "stack": ["TypeScript", "React"], "salary_min_rub": 200000, "salary_max_rub": 270000,
        "work_format": "remote", "work_city": None,
        "first_30_days": "Найти и устранить один конфликт параллельных запросов.",
        "industry": "ИТ", "take_home_minutes": 0,
    },
    {
        "title": "Backend Junior: выгрузки без потерь",
        "description": "Поддерживать API выгрузок и находить ошибки в обработке данных.",
        "specialization": "backend", "grade": "junior",
        "competencies": ["data_trace", "validation", "http_api"],
        "stack": ["Python", "FastAPI"], "salary_min_rub": 120000, "salary_max_rub": 165000,
        "work_format": "remote", "work_city": None,
        "first_30_days": "Добавить проверку целостности для одного вида выгрузки.",
        "industry": "ИТ", "take_home_minutes": 30,
    },
    {
        "title": "QA Junior: качество пользовательских сценариев",
        "description": "Проверять критичные сценарии, фиксировать воспроизводимые дефекты и валидировать API.",
        "specialization": "qa", "grade": "junior",
        "competencies": ["test_design", "bug_reporting", "api_testing"],
        "stack": ["Postman", "SQL"], "salary_min_rub": 100000, "salary_max_rub": 150000,
        "work_format": "remote", "work_city": None,
        "first_30_days": "Покрыть критичный сценарий входными и граничными проверками.",
        "industry": "ИТ", "take_home_minutes": 30,
    },
    {
        "title": "QA Middle: автоматизация и устойчивость",
        "description": "Приоритизировать риски, развивать автотесты и проверять восстановление после отказов.",
        "specialization": "qa", "grade": "middle",
        "competencies": ["risk_based_testing", "automation_design", "reliability_testing"],
        "stack": ["Playwright", "Python"], "salary_min_rub": 180000, "salary_max_rub": 260000,
        "work_format": "hybrid", "work_city": "Москва",
        "first_30_days": "Выбрать высокорисковый поток и закрепить его автоматическими проверками.",
        "industry": "ИТ", "take_home_minutes": 0,
    },
    {
        "title": "Аналитик данных Junior: SQL и качество витрин",
        "description": "Проверять данные, собирать SQL-выборки и согласовывать определения продуктовых метрик.",
        "specialization": "data_analyst", "grade": "junior",
        "competencies": ["sql_querying", "data_quality", "metric_definition"],
        "stack": ["SQL", "Python"], "salary_min_rub": 110000, "salary_max_rub": 165000,
        "work_format": "remote", "work_city": None,
        "first_30_days": "Описать контракт одной витрины и добавить проверки качества данных.",
        "industry": "ИТ", "take_home_minutes": 30,
    },
    {
        "title": "Аналитик данных Middle: эксперименты и метрики",
        "description": "Оценивать эксперименты, проверять целостность метрик и валидировать аналитические данные.",
        "specialization": "data_analyst", "grade": "middle",
        "competencies": ["experiment_analysis", "metric_integrity", "data_validation"],
        "stack": ["SQL", "Python", "Tableau"], "salary_min_rub": 200000, "salary_max_rub": 290000,
        "work_format": "office", "work_city": "Санкт-Петербург",
        "first_30_days": "Проверить трактовку ключевого эксперимента и надёжность исходных данных.",
        "industry": "ИТ", "take_home_minutes": 0,
    },
)


def _seed_discovery_roles(db, employer: User, at) -> None:
    for index, fixture in enumerate(DISCOVERY_ROLE_FIXTURES):
        need = db.scalar(select(HiringNeed).where(
            HiringNeed.employer_id == employer.id, HiringNeed.title == fixture["title"]
        ))
        if need is not None:
            continue
        card_data = {
            **fixture,
            "interview_steps": [{"title": "Знакомство и разбор опыта", "duration_minutes": 45}],
            "response_sla_hours": 48,
            "employer_contact": "other@demo.test",
            "active_headcount_attested": True,
        }
        card = RoleCardIn.model_validate(card_data)
        need = HiringNeed(
            employer_id=employer.id,
            title=card.title,
            description=card.description,
            specialization=card.specialization,
            grade=card.grade,
            competencies=card.competencies,
            stack=card.stack,
            salary_min_rub=card.salary_min_rub,
            salary_max_rub=card.salary_max_rub,
            work_format=card.work_format,
        )
        db.add(need)
        db.flush()
        fixture_at = at - timedelta(seconds=index)
        version = create_role_version(db, employer.id, need.id, card, need.current_role_version,
                                      fixture_at, source="synthetic_demo")
        publish_role(db, employer.id, need.id, expected_version=version.version,
                     active_headcount_attested=True, discoverable=True, at=fixture_at)


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

        _seed_discovery_roles(db, second, now())

        browser_candidate = db.scalar(select(User).where(User.email == "new-candidate@demo.test"))
        if browser_candidate is None:
            browser_candidate = User(email="new-candidate@demo.test", password_hash=hasher.hash("DemoPass123!"),
                                     role="candidate", origin="synthetic_fixture", email_verified_at=now())
            db.add(browser_candidate)
        else:
            browser_candidate.origin = "synthetic_fixture"

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

        demo_skills = {
            "backend": ["Python", "PostgreSQL"],
            "frontend": ["TypeScript", "React"],
            "qa": ["Playwright", "Postman"],
            "data_analyst": ["SQL", "Python"],
        }
        demo_summaries = {
            "backend": "Синтетический профиль: Python, PostgreSQL, API, платёжные события, обработка повторов и восстановление после отказов.",
            "frontend": "Синтетический профиль: TypeScript, React, формы, состояния интерфейса и надёжные запросы.",
            "qa": "Синтетический профиль: Playwright, Postman, проверка пользовательских сценариев и API, регрессии.",
            "data_analyst": "Синтетический профиль: SQL, Python, качество данных, витрины, аналитика и проверка метрик.",
        }
        synthetic_profile_count = 0
        for category, skills in COMPETENCIES.items():
            specialization, grade = category.split(":")
            for index in range(12):
                email = f"{specialization}-{grade}-{index+1}@demo.test"
                user = db.scalar(select(User).where(User.email == email))
                if user is not None:
                    if user.origin == "synthetic_fixture":
                        profile = db.get(CandidateProfile, user.id)
                        if profile:
                            profile.recommendation_consent = True  # synthetic cohort, never real consent
                            if profile.summary == "Синтетический профиль для демонстрации подборки.":
                                profile.summary = demo_summaries[specialization]
                            if profile.adult_attested_at is None:
                                profile.adult_attested_at = now()
                            if profile.verification_source == "synthetic_fixture":
                                synthetic_profile_count += 1
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
                    summary=demo_summaries[specialization], recommendation_consent=True,
                    skills=demo_skills[specialization],
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
                synthetic_profile_count += 1
        db.flush()
        version = db.scalar(select(RoleVersion).where(RoleVersion.need_id == need.id,
                                                    RoleVersion.version == need.current_role_version))
        if version and need.publication_state == "active":
            for index in range(7, 13):
                peer = db.scalar(select(User).where(User.email == f"backend-middle-{index}@demo.test",
                                                   User.origin == "synthetic_fixture"))
                if peer and not db.scalar(select(RoleDecision.id).where(RoleDecision.candidate_id == peer.id,
                                                                        RoleDecision.need_id == need.id)):
                    profile = db.get(CandidateProfile, peer.id)
                    db.add(RoleDecision(candidate_id=peer.id, need_id=need.id, role_version_id=version.id,
                                        action="saved", preferences_version=profile.preferences_version))
        db.commit()
    print(f"Seed ready: two employers, {synthetic_profile_count} synthetic assessment profiles, "
          "one profile-free candidate, nine discovery roles.")
    print("Demo accounts: employer@demo.test / DemoPass123!, other@demo.test / DemoPass123!")
    print("Register a new candidate to demonstrate a real assessment.")


if __name__ == "__main__":
    seed()
