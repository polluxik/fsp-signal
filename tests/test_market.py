from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import json
from threading import Barrier

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import delete, func, select

import backend.market as market
import backend.seed_market as importer
import backend.main as main
from backend.db import SessionLocal, engine
from backend.main import app
from backend.models import CandidateProfile, HiringNeed, InterviewMeeting, Invitation, SyntheticMarketRecord, User
from test_flow import register_verified
from test_employer_pipeline import context
from test_calendar import availability, book, send_accept


@pytest.fixture(autouse=True)
def isolated_market():
    # The suite shares its dedicated test DB; isolate only this new corpus table.
    with SessionLocal() as db:
        db.execute(delete(SyntheticMarketRecord))
        db.commit()
    yield
    with SessionLocal() as db:
        db.execute(delete(SyntheticMarketRecord))
        db.commit()


@pytest.fixture
def demo_mode(monkeypatch):
    monkeypatch.setattr(importer, 'settings', replace(importer.settings, app_mode='demo'))
    monkeypatch.setattr(market, 'settings', replace(market.settings, app_mode='demo'))


@pytest.fixture
def corpus(demo_mode):
    with SessionLocal() as db:
        importer.seed_market(db)
        db.commit()
    return importer.load_corpus()


def test_market_import_is_repeatable_and_preserves_accounts_consents_invitation_and_meeting(demo_mode):
    with TestClient(app) as employer, TestClient(app) as candidate:
        company, person, need_id, version = context(employer, candidate)
        invite = send_accept(employer, candidate, person, need_id, version)
        calendar = employer.get('/api/v1/employer/calendar').json()
        _, slots = availability(employer, minutes=30)
        assert book(candidate, calendar, invite, slots[0]).status_code == 201
        funnel_url = f'/api/v1/employer/needs/{need_id}/funnel'
        old_funnel = employer.get(funnel_url).json()
        with SessionLocal() as db:
            profile = db.get(CandidateProfile, person['id'])
            before = {column.name: deepcopy(getattr(profile, column.name)) for column in profile.__table__.columns}
            counts = {model.__name__: db.scalar(select(func.count()).select_from(model)) for model in (User, CandidateProfile, HiringNeed, Invitation, InterviewMeeting)}
            first = importer.seed_market(db)
            db.commit()
            assert first == {'dataset_version': importer.DATASET_VERSION, 'profiles': 200, 'vacancies': 120, 'families': 32, 'inserted': 352}
            assert importer.seed_market(db)['inserted'] == 0
            db.commit()
            assert db.scalar(select(func.count()).select_from(SyntheticMarketRecord)) == 352
            assert before == {column.name: getattr(profile, column.name) for column in profile.__table__.columns}
            assert counts == {model.__name__: db.scalar(select(func.count()).select_from(model)) for model in (User, CandidateProfile, HiringNeed, Invitation, InterviewMeeting)}
        assert employer.get(funnel_url).json() == old_funnel
        assert employer.get(f'/api/v1/employer/candidates/{person["id"]}/contact').status_code == 200


@pytest.mark.parametrize('damage', ['origin', 'assessment', 'contact', 'family', 'skill', 'duplicate', 'truncated', 'broken_json'])
def test_invalid_market_corpus_is_rejected_before_any_records_are_written(demo_mode, tmp_path, damage):
    for name in ('taxonomy.json', 'profiles.jsonl', 'vacancies.jsonl'):
        (tmp_path / name).write_bytes((importer.DATA_ROOT / name).read_bytes())
    profiles = [json.loads(line) for line in (tmp_path / 'profiles.jsonl').read_text(encoding='utf-8').splitlines()]
    if damage == 'origin': profiles[0]['origin'] = 'direct_signup'
    elif damage == 'assessment': profiles[0]['assessment_status'] = 'verified'
    elif damage == 'contact': profiles[0]['contact'] = {'email': 'real@example.test'}
    elif damage == 'family': profiles[0]['target_roles'][0]['role_family_id'] = 'invented'
    elif damage == 'skill': profiles[0]['skills'][0]['verification_status'] = 'verified'
    elif damage == 'duplicate': profiles[1]['profile_id'] = profiles[0]['profile_id']
    elif damage == 'truncated': profiles.pop()
    (tmp_path / 'profiles.jsonl').write_text('\n'.join(json.dumps(row, ensure_ascii=False) for row in profiles), encoding='utf-8')
    if damage == 'broken_json': (tmp_path / 'profiles.jsonl').write_text('{broken', encoding='utf-8')
    with SessionLocal() as db:
        with pytest.raises(ValueError, match='nothing was imported'):
            importer.seed_market(db, tmp_path)
        assert db.scalar(select(func.count()).select_from(SyntheticMarketRecord)) == 0


def test_repeat_import_cannot_silently_overwrite_an_existing_dataset(corpus):
    with SessionLocal() as db:
        row = db.get(SyntheticMarketRecord, 'syn-candidate-001')
        row.payload = {**row.payload, 'summary': 'Existing fixture differs'}
        db.commit()
        with pytest.raises(ValueError, match='instead of overwriting'):
            importer.seed_market(db)
        db.refresh(row)
        assert row.payload['summary'] == 'Existing fixture differs'


def test_catalog_authorization_production_gate_and_no_verified_user_side_effects(corpus, monkeypatch):
    with SessionLocal() as db:
        old_profiles = db.scalar(select(func.count()).select_from(CandidateProfile))
        old_needs = db.scalar(select(func.count()).select_from(HiringNeed))
    with TestClient(app) as employer, TestClient(app) as candidate, TestClient(app) as guest:
        register_verified(employer, 'market-hr@example.test', 'employer')
        register_verified(candidate, 'market-candidate@example.test', 'candidate')
        assert guest.get('/api/v1/demo-market/catalog').status_code == 401
        metadata = employer.get('/api/v1/demo-market/catalog').json()
        assert metadata['profiles'] == 200 and metadata['vacancies'] == 120 and len(metadata['families']) == 32
        assert all(family['profile_count'] >= 5 and family['vacancy_count'] in (3, 4) for family in metadata['families'])
        assert candidate.get('/api/v1/demo-market/profiles').status_code == 403
        assert candidate.get('/api/v1/demo-market/profiles/syn-candidate-001').status_code == 403
        assert candidate.get('/api/v1/demo-market/vacancies/syn-vacancy-001/compare/syn-candidate-001').status_code == 403
        assert candidate.get('/api/v1/demo-market/vacancies/syn-vacancy-001').status_code == 200
        assert employer.get('/api/v1/demo-market/profiles/syn-vacancy-001').status_code == 404
        assert employer.get('/api/v1/demo-market/profiles/does-not-exist').status_code == 404
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(CandidateProfile)) == old_profiles
            assert db.scalar(select(func.count()).select_from(HiringNeed)) == old_needs
        monkeypatch.setattr(market, 'settings', replace(market.settings, app_mode='production'))
        monkeypatch.setattr(importer, 'settings', replace(importer.settings, app_mode='production'))
        monkeypatch.setattr(main, 'settings', replace(main.settings, app_mode='production'))
        assert not employer.get('/api/v1/me').json()['demo_market_enabled']
        for path in ('catalog', 'profiles', 'vacancies', 'profiles/syn-candidate-001', 'vacancies/syn-vacancy-001', 'vacancies/syn-vacancy-001/compare/syn-candidate-001'):
            assert employer.get('/api/v1/demo-market/' + path).status_code == 404
        with SessionLocal() as db, pytest.raises(ValueError, match='APP_MODE=demo'):
            importer.seed_market(db)


def test_market_filters_pagination_and_full_contact_free_resume(corpus):
    with TestClient(app) as employer:
        register_verified(employer, 'market-filters@example.test', 'employer')
        first = employer.get('/api/v1/demo-market/profiles').json()
        second = employer.get('/api/v1/demo-market/profiles?offset=20').json()
        assert first['total'] == second['total'] == 200
        assert len(first['items']) == len(second['items']) == 20
        assert {row['id'] for row in first['items']}.isdisjoint(row['id'] for row in second['items'])
        filtered = employer.get('/api/v1/demo-market/profiles?family=backend&level=junior&work_format=remote&q=Python').json()
        expected = [p for p in corpus[1] if p['target_roles'][0]['role_family_id'] == 'backend'
            and p['target_roles'][0]['declared_level'] == 'junior' and 'remote' in p['preferred_work_formats']
            and 'python' in json.dumps(p, ensure_ascii=False).casefold()]
        assert filtered['total'] == len(expected)
        assert all(row['level'] == 'junior' and row['assessment_status'] == 'not_assessed' for row in filtered['items'])
        assert employer.get('/api/v1/demo-market/profiles?q=xxxxxxxxxx').json()['items'] == []
        assert employer.get('/api/v1/demo-market/profiles?offset=1000').json()['items'] == []
        for query in ('family=bogus', 'level=principal', 'offset=-1', 'limit=41', 'work_format=invalid'):
            assert employer.get('/api/v1/demo-market/profiles?' + query).status_code == 422
        detail = employer.get('/api/v1/demo-market/profiles/syn-candidate-001').json()
        assert detail['details'] == corpus[1][0]
        assert detail['details']['contact'] is None and detail['card']['data_mode'] == 'synthetic'
        assert detail['card']['assessment_status'] == 'not_assessed'
        assert employer.get('/api/v1/demo-market/vacancies?family=backend').json()['total'] == 4


def test_comparison_uses_exact_family_and_claimed_level_never_experience(corpus):
    profile, vacancy = deepcopy(corpus[1][0]), deepcopy(corpus[2][0])
    profile['target_roles'][0]['declared_level'] = vacancy['role_level']
    profile['salary_expectation_rub_month'] = {'min': 1, 'max': 2}
    profile['preferred_work_formats'] = [vacancy['work_format']]
    profile['city'] = vacancy['work_city']
    profile['skills'] = [{'id': skill['id']} for skill in vacancy['required_skills']]
    profile['experience_months_declared'] = 1000
    assert market.compare_claims(profile, vacancy)[0] == 'compatible'
    profile['target_roles'][0]['declared_level'] = 'lead'
    assert market.compare_claims(profile, vacancy)[0] == 'incompatible'
    profile['target_roles'][0]['role_family_id'] = 'frontend'
    profile['summary'] = vacancy['description']
    checks = {check.field: check for check in market.compare_claims(profile, vacancy)[1]}
    assert checks['family'].passed is False and checks['level'].passed is None
    profile['salary_expectation_rub_month'] = None
    profile['preferred_work_formats'] = []
    profile['city'] = None
    profile['skills'] = []
    checks = {check.field: check for check in market.compare_claims(profile, vacancy)[1]}
    assert all(checks[field].passed is None for field in ('salary', 'format', 'city', 'skills'))


def test_comparison_endpoint_returns_explanation_without_creating_hiring_actions(corpus):
    with SessionLocal() as db:
        old_invitations = db.scalar(select(func.count()).select_from(Invitation))
        old_profiles = db.scalar(select(func.count()).select_from(CandidateProfile))
    with TestClient(app) as employer:
        register_verified(employer, 'market-compare@example.test', 'employer')
        result = employer.get('/api/v1/demo-market/vacancies/syn-vacancy-001/compare/syn-candidate-001')
        assert result.status_code == 200, result.text
        data = result.json()
        assert data['data_mode'] == 'synthetic' and data['assessment_status'] == 'not_assessed'
        assert data['status'] in ('compatible', 'incompatible', 'unknown')
        assert 'score' not in data and 'probability' not in data
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(Invitation)) == old_invitations
            assert db.scalar(select(func.count()).select_from(CandidateProfile)) == old_profiles


@pytest.mark.skipif(engine.dialect.name != 'postgresql', reason='PostgreSQL concurrent import')
def test_two_importers_create_one_corpus_without_duplicates(demo_mode):
    barrier = Barrier(2)
    def run(_):
        with SessionLocal() as db:
            barrier.wait(timeout=5)
            result = importer.seed_market(db)
            db.commit()
            return result['inserted']
    with ThreadPoolExecutor(max_workers=2) as pool:
        inserted = list(pool.map(run, range(2)))
    assert sum(inserted) == 352
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(SyntheticMarketRecord)) == 352
