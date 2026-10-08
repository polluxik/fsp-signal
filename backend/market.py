"""Authenticated demo catalog and comparison of fictional, unassessed claims."""
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import SyntheticMarketRecord, User
from .security import get_user, require
from .seed_market import DATASET_VERSION

Level = Literal['junior', 'middle', 'senior', 'lead']
Format = Literal['remote', 'hybrid', 'office']


def demo_only():
    if settings.app_mode != 'demo':
        raise HTTPException(404, 'NOT_FOUND')


router = APIRouter(prefix='/api/v1/demo-market', tags=['Synthetic demo market'], dependencies=[Depends(demo_only)])


class MarketFamily(BaseModel):
    id: str
    name: str
    aliases: list[str]
    profile_count: int
    vacancy_count: int


class MarketCatalog(BaseModel):
    dataset_version: str
    data_mode: Literal['synthetic'] = 'synthetic'
    profiles: int
    vacancies: int
    families: list[MarketFamily]


class MarketCard(BaseModel):
    id: str
    kind: Literal['profile', 'vacancy']
    title: str
    family_id: str
    family_name: str
    level: Level
    city: str | None
    work_formats: list[Format]
    skills: list[str]
    summary: str
    salary_min: int | None
    salary_max: int | None
    data_mode: Literal['synthetic'] = 'synthetic'
    assessment_status: Literal['not_assessed'] = 'not_assessed'


class MarketPage(BaseModel):
    items: list[MarketCard]
    total: int
    offset: int
    limit: int


class MarketDetail(BaseModel):
    card: MarketCard
    # Original versioned fixture schema, never a real user's CV.
    details: dict[str, Any]


class DeclaredCheck(BaseModel):
    field: str
    label: str
    passed: bool | None
    explanation: str


class MarketComparison(BaseModel):
    profile_id: str
    vacancy_id: str
    status: Literal['compatible', 'incompatible', 'unknown']
    checks: list[DeclaredCheck]
    matched_skills: list[str]
    missing_skills: list[str]
    data_mode: Literal['synthetic'] = 'synthetic'
    assessment_status: Literal['not_assessed'] = 'not_assessed'
    notice: str = 'Сравнение вымышленных заявленных условий. Навыки и уровень не проверены; это не вероятность найма.'


def _rows(db, kind):
    return db.scalars(select(SyntheticMarketRecord).where(SyntheticMarketRecord.dataset_version == DATASET_VERSION,
        SyntheticMarketRecord.kind == kind).order_by(SyntheticMarketRecord.id)).all()


def _record(db, record_id, kind):
    record = db.scalar(select(SyntheticMarketRecord).where(SyntheticMarketRecord.id == record_id,
        SyntheticMarketRecord.dataset_version == DATASET_VERSION, SyntheticMarketRecord.kind == kind))
    if not record:
        raise HTTPException(404, 'NOT_FOUND')
    return record


def _card(row):
    payload = row.payload
    if row.kind == 'profile':
        target = payload['target_roles'][0]
        salary = payload.get('salary_expectation_rub_month') or {}
        return MarketCard(id=row.id, kind='profile', title=payload['resume_title'],
            family_id=row.family_id, family_name=target['role_family_name'], level=row.level,
            city=payload.get('city'), work_formats=payload['preferred_work_formats'],
            skills=[skill['label'] for skill in payload['skills']], summary=payload['summary'],
            salary_min=salary.get('min'), salary_max=salary.get('max'))
    salary = payload['salary']
    return MarketCard(id=row.id, kind='vacancy', title=payload['title'], family_id=row.family_id,
        family_name=payload['role_family_name'], level=row.level, city=payload.get('work_city'),
        work_formats=[payload['work_format']], skills=[skill['label'] for skill in payload['required_skills']],
        summary=payload['description'], salary_min=salary['min_rub_month_gross'], salary_max=salary['max_rub_month_gross'])


@router.get('/catalog', response_model=MarketCatalog)
def catalog(user: User = Depends(get_user), db: Session = Depends(get_db)):
    profiles, vacancies = _rows(db, 'profile'), _rows(db, 'vacancy')
    return MarketCatalog(dataset_version=DATASET_VERSION, profiles=len(profiles), vacancies=len(vacancies),
        families=[MarketFamily(id=row.family_id, name=row.payload['name_ru'], aliases=row.payload['aliases'],
            profile_count=sum(p.family_id == row.family_id for p in profiles),
            vacancy_count=sum(v.family_id == row.family_id for v in vacancies)) for row in _rows(db, 'family')])


def _page(db, kind, family, level, work_format, q, offset, limit):
    if family and not any(row.family_id == family for row in _rows(db, 'family')):
        raise HTTPException(422, 'INVALID_MARKET_FAMILY')
    cards = []
    for row in _rows(db, kind):
        if family and row.family_id != family or level and row.level != level:
            continue
        card = _card(row)
        if work_format and work_format not in card.work_formats:
            continue
        if q and q.strip().casefold() not in json.dumps(row.payload, ensure_ascii=False).casefold():
            continue
        cards.append(card)
    return MarketPage(items=cards[offset:offset + limit], total=len(cards), offset=offset, limit=limit)


@router.get('/profiles', response_model=MarketPage)
def profiles(family: str | None = Query(None, max_length=64), level: Level | None = None,
             work_format: Format | None = None, q: str = Query('', max_length=120),
             offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=40),
             user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, 'employer')
    return _page(db, 'profile', family, level, work_format, q, offset, limit)


@router.get('/vacancies', response_model=MarketPage)
def vacancies(family: str | None = Query(None, max_length=64), level: Level | None = None,
              work_format: Format | None = None, q: str = Query('', max_length=120),
              offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=40),
              user: User = Depends(get_user), db: Session = Depends(get_db)):
    return _page(db, 'vacancy', family, level, work_format, q, offset, limit)


@router.get('/profiles/{profile_id}', response_model=MarketDetail)
def profile_detail(profile_id: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, 'employer')
    row = _record(db, profile_id, 'profile')
    return MarketDetail(card=_card(row), details=row.payload)


@router.get('/vacancies/{vacancy_id}', response_model=MarketDetail)
def vacancy_detail(vacancy_id: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    row = _record(db, vacancy_id, 'vacancy')
    return MarketDetail(card=_card(row), details=row.payload)


def compare_claims(profile, vacancy):
    targets = [target for target in profile['target_roles'] if target['role_family_id'] == vacancy['role_family_id']]
    salary = profile.get('salary_expectation_rub_month')
    formats = profile.get('preferred_work_formats')
    city = profile.get('city')
    format_match = vacancy['work_format'] in formats if formats else None
    city_match = True if vacancy['work_format'] == 'remote' else city.strip().casefold() == vacancy['work_city'].strip().casefold() if city and vacancy.get('work_city') else None
    declared = {skill['id'] for skill in profile.get('skills', [])}
    required = vacancy['required_skills']
    matched = [skill['label'] for skill in required if skill['id'] in declared]
    missing = [skill['label'] for skill in required if skill['id'] not in declared]
    checks = [
        DeclaredCheck(field='family', label='Семейство роли', passed=bool(targets), explanation='Точное совпадение целевого семейства; сходство текста его не заменяет.'),
        DeclaredCheck(field='level', label='Заявленный уровень', passed=any(t['declared_level'] == vacancy['role_level'] for t in targets) if targets else None, explanation='Уровень указан персонажем, не присвоен тестом или стажем.'),
        DeclaredCheck(field='salary', label='Зарплатный минимум', passed=vacancy['salary']['max_rub_month_gross'] >= salary['min'] if salary else None, explanation='Верхняя граница роли должна покрывать заявленный минимум. Диапазоны вымышлены.'),
        DeclaredCheck(field='format', label='Формат работы', passed=format_match, explanation='Формат роли сравнивается с перечисленными пожеланиями.'),
        DeclaredCheck(field='city', label='Город для офиса/гибрида', passed=city_match, explanation='Для офиса/гибрида требуется совпадение города; для удалённой роли город не ограничивает сравнение.'),
        DeclaredCheck(field='skills', label='Обязательные навыки — заявлены', passed=not missing if declared else None, explanation='Сравниваются canonical ID перечисленных навыков; отсутствие данных означает неизвестно. Это не проверка владения навыками.'),
    ]
    status = 'incompatible' if any(c.passed is False for c in checks) else 'unknown' if any(c.passed is None for c in checks) else 'compatible'
    return status, checks, matched, missing


@router.get('/vacancies/{vacancy_id}/compare/{profile_id}', response_model=MarketComparison)
def comparison(vacancy_id: str, profile_id: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, 'employer')
    profile = _record(db, profile_id, 'profile').payload
    vacancy = _record(db, vacancy_id, 'vacancy').payload
    status, checks, matched, missing = compare_claims(profile, vacancy)
    return MarketComparison(profile_id=profile_id, vacancy_id=vacancy_id, status=status,
        checks=checks, matched_skills=matched, missing_skills=missing)
