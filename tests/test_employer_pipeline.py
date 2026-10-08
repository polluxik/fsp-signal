"""Private shortlist lifecycle, version-pinned counts, and concurrency checks."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import backend.employer_pipeline as pipeline
from backend.db import SessionLocal, engine
from backend.main import app
from backend.models import (CandidateProfile, EmployerShortlistEntry, Invitation,
                            SearchSnapshot, User, now)
from test_calendar import availability, book, send_accept
from test_flow import csrf, register_verified
from test_invitations_v2 import _publish_role
from test_role_cards import role_payload
from test_search_snapshots import make_candidate_profile, make_search_context


def context(employer, candidate):
    employer_user, candidate_user, need_id, _ = make_search_context(employer, candidate, extra_skills=['PostgreSQL'])
    return employer_user, candidate_user, need_id, _publish_role(employer, need_id)


def choose(employer, need_id, version_id, candidate_id, *, saved=True, expected=0, headers=None):
    return employer.put(f'/api/v1/employer/needs/{need_id}/shortlist/{candidate_id}',
        headers=csrf(employer) if headers is None else headers,
        json={'role_version_id': version_id, 'expected_version': expected, 'saved': saved})


def read(employer, need_id, version_id=None):
    suffix = f'?role_version_id={version_id}' if version_id else ''
    return employer.get(f'/api/v1/employer/needs/{need_id}/shortlist{suffix}')


def test_incomplete_initial_draft_and_its_history_return_empty_shortlist_without_server_error():
    with TestClient(app) as employer, TestClient(app) as candidate:
        _, person, need_id, _ = make_search_context(employer, candidate, extra_skills=['PostgreSQL'])
        draft = read(employer, need_id)
        assert draft.status_code == 200, draft.text
        old_version = draft.json()['role_version_id']
        assert draft.json()['entries'] == [] and draft.json()['current']
        assert choose(employer, need_id, old_version, person['id']).json()['detail'] == 'ROLE_NOT_ACTIVE'
        version = _publish_role(employer, need_id)
        assert choose(employer, need_id, version, person['id']).status_code == 200
        historical = read(employer, need_id, old_version)
        assert historical.status_code == 200, historical.text
        assert historical.json()['entries'] == [] and not historical.json()['current']
        assert historical.json()['unavailable_count'] == 0


def test_shortlist_cas_persists_private_cards_and_tombstone_can_be_saved_again():
    with TestClient(app) as employer, TestClient(app) as candidate:
        _, person, need_id, version = context(employer, candidate)
        assert read(employer, need_id).json()['entries'] == []
        first = choose(employer, need_id, version, person['id'])
        assert first.status_code == 200, first.text
        assert first.json()['version'] == 1
        assert choose(employer, need_id, version, person['id']).status_code == 409
        response = read(employer, need_id)
        assert response.status_code == 200, response.text
        card = response.json()['entries'][0]['candidate']
        assert card['id'] == person['id'] and card['match']['algorithm_version'] == 'match_v2'
        assert not ({'full_name', 'contact_email', 'contact_phone', 'preferences', 'min_salary_rub', 'achievement_story'} & card.keys())
        assert candidate.get('/api/v1/candidate/profile').json().get('shortlist') is None
        assert choose(employer, need_id, version, person['id'], headers={}).status_code == 403
        removed = choose(employer, need_id, version, person['id'], saved=False, expected=1)
        assert removed.status_code == 200 and removed.json()['version'] == 2
        assert not read(employer, need_id).json()['entries'][0]['saved']
        assert choose(employer, need_id, version, person['id'], saved=False, expected=2).json()['version'] == 2
        assert choose(employer, need_id, version, person['id'], expected=1).status_code == 409
        assert choose(employer, need_id, version, person['id'], expected=2).json()['version'] == 3
        with SessionLocal() as db:
            assert db.scalar(select(func.count(EmployerShortlistEntry.id)).where(
                EmployerShortlistEntry.role_version_id == version)) == 1


@pytest.mark.parametrize('guard', ['publication', 'processing', 'adult', 'availability', 'blocked', 'category', 'salary', 'format'])
def test_shortlist_rechecks_visibility_without_revealing_withdrawn_candidate(guard):
    with TestClient(app) as employer, TestClient(app) as candidate:
        company, person, need_id, version = context(employer, candidate)
        assert choose(employer, need_id, version, person['id']).status_code == 200
        with SessionLocal() as db:
            profile = db.get(CandidateProfile, person['id'])
            if guard == 'publication': profile.published_at = None
            elif guard == 'processing': profile.consent_processing_at = None
            elif guard == 'adult': profile.adult_attested_at = None
            elif guard == 'availability': profile.available = False; profile.preferences = dict(profile.preferences, available=False)
            elif guard == 'blocked': profile.blocked_employer_ids = [company['id']]
            elif guard == 'category': profile.verified_grade = 'junior'
            elif guard == 'salary': profile.preferences = dict(profile.preferences, salary_min_rub=500000)
            elif guard == 'format': profile.preferences = dict(profile.preferences, allowed_work_formats=['office'], allowed_cities=['Казань'])
            db.commit()
        hidden = read(employer, need_id)
        assert hidden.status_code == 200, hidden.text
        assert hidden.json()['entries'] == [] and hidden.json()['unavailable_count'] == 1
        assert person['id'] not in hidden.text
        assert choose(employer, need_id, version, person['id'], expected=1).status_code == 404
        # Removing an owned hidden bookmark is still allowed; it does not restore visibility.
        assert choose(employer, need_id, version, person['id'], saved=False, expected=1).status_code == 200
        assert read(employer, need_id).json()['unavailable_count'] == 0


def test_other_company_and_candidate_cannot_read_or_modify_a_private_pipeline():
    with TestClient(app) as employer, TestClient(app) as candidate, TestClient(app) as other:
        _, person, need_id, version = context(employer, candidate)
        register_verified(other, f'other-pipeline-{uuid4().hex}@example.test', 'employer')
        assert choose(employer, need_id, version, person['id']).status_code == 200
        for endpoint in ('shortlist', 'funnel'):
            assert other.get(f'/api/v1/employer/needs/{need_id}/{endpoint}').status_code == 404
            assert candidate.get(f'/api/v1/employer/needs/{need_id}/{endpoint}').status_code == 403
        assert choose(other, need_id, version, person['id']).status_code == 404
        assert choose(candidate, need_id, version, person['id']).status_code == 403


def test_shortlist_stays_with_old_conditions_and_saves_require_a_fresh_current_role():
    with TestClient(app) as employer, TestClient(app) as candidate:
        _, person, need_id, old_version = context(employer, candidate)
        assert choose(employer, need_id, old_version, person['id']).status_code == 200
        changed = employer.post(f'/api/v1/employer/needs/{need_id}/versions', headers=csrf(employer),
            json={'expected_version': 2, 'card': role_payload(first_30_days='Другая задача для проверки новой версии')})
        assert changed.status_code == 201, changed.text
        new_list = read(employer, need_id).json()
        assert new_list['entries'] == [] and new_list['role_version_id'] != old_version
        assert len(new_list['versions']) == 3
        history = read(employer, need_id, old_version).json()
        assert not history['current'] and history['entries'][0]['saved']
        assert choose(employer, need_id, old_version, person['id'], expected=1).json()['detail'] == 'ROLE_VERSION_CONFLICT'
        assert choose(employer, need_id, old_version, person['id'], saved=False, expected=1).status_code == 200
        assert choose(employer, need_id, new_list['role_version_id'], person['id']).json()['detail'] == 'ROLE_NOT_ACTIVE'
        published = employer.post(f'/api/v1/employer/needs/{need_id}/publish', headers=csrf(employer),
            json={'expected_version': 3, 'active_headcount_attested': True, 'discoverable': False})
        assert published.status_code == 200
        with SessionLocal() as db:
            from backend.models import HiringNeed
            db.get(HiringNeed, need_id).confirmed_at = now() - timedelta(days=15)
            db.commit()
        assert choose(employer, need_id, new_list['role_version_id'], person['id']).json()['detail'] == 'ROLE_STALE'


def test_role_version_from_another_need_is_not_accepted():
    with TestClient(app) as employer, TestClient(app) as candidate, TestClient(app) as other, TestClient(app) as other_candidate:
        _, person, need_id, _ = context(employer, candidate)
        _, _, _, other_version = context(other, other_candidate)
        assert read(employer, need_id, other_version).status_code == 404
        assert choose(employer, need_id, other_version, person['id']).status_code == 404
        assert employer.get(f'/api/v1/employer/needs/{need_id}/funnel?role_version_id={other_version}').status_code == 404


def test_funnel_deduplicates_and_separates_synthetic_data_and_bilateral_interviews(monkeypatch):
    monkeypatch.setattr(pipeline, 'settings', replace(pipeline.settings, app_mode='production'))
    with TestClient(app) as employer, TestClient(app) as candidate, TestClient(app) as synthetic:
        company, person, need_id, version = context(employer, candidate)
        fake = make_candidate_profile(synthetic, extra_skills=['PostgreSQL'])
        with SessionLocal() as db:
            db.get(User, fake['id']).origin = 'synthetic_fixture'
            for _ in range(2):
                db.add(SearchSnapshot(employer_id=company['id'], need_id=need_id, role_version_id=version,
                    results=[{'candidate_id': person['id']}, {'candidate_id': fake['id']}]))
            db.commit()
        real_invite = send_accept(employer, candidate, person, need_id, version)
        fake_invite = send_accept(employer, synthetic, fake, need_id, version)
        calendar = employer.get('/api/v1/employer/calendar').json()
        _, slots = availability(employer, minutes=60)
        assert book(candidate, calendar, real_invite, slots[0]).status_code == 201
        assert book(synthetic, calendar, fake_invite, slots[1]).status_code == 201
        url = f'/api/v1/employer/needs/{need_id}/funnel'
        first = employer.get(url).json()
        for mode in ('real', 'synthetic'):
            assert first[mode] == {'matched': 1, 'invited': 1, 'accepted': 1, 'scheduled': 1, 'held': 0}
        assert person['id'] not in str(first) and fake['id'] not in str(first)
        assert 'saved' not in first and 'hidden' not in first
        confirmation = f'/api/v1/invitations/{real_invite["id"]}/interview-held-confirmation'
        assert candidate.post(confirmation, headers=csrf(candidate)).status_code == 200
        assert employer.get(url).json()['real']['held'] == 0
        assert employer.post(confirmation, headers=csrf(employer)).status_code == 200
        assert employer.post(confirmation, headers=csrf(employer)).status_code == 200
        assert employer.get(url).json()['real']['held'] == 1
        assert employer.get(url).json()['synthetic']['held'] == 0
        # A different role version starts with its own activity, not the previous totals.
        updated = employer.post(f'/api/v1/employer/needs/{need_id}/versions', headers=csrf(employer),
            json={'expected_version': 2, 'card': role_payload(first_30_days='Проверка независимого среза версии')})
        assert updated.status_code == 201
        fresh = employer.get(url).json()
        assert all(value == 0 for value in fresh['real'].values())
        assert all(value == 0 for value in fresh['synthetic'].values())
        old = employer.get(f'{url}?role_version_id={version}').json()
        assert not old['current'] and old['real']['held'] == 1


@pytest.mark.skipif(engine.dialect.name != 'postgresql', reason='PostgreSQL row-lock race')
@pytest.mark.parametrize('existing', [False, True])
def test_two_employer_tabs_cannot_create_duplicate_or_overwrite_shortlist_state(existing):
    with TestClient(app) as employer, TestClient(app) as candidate, TestClient(app) as other_tab:
        company, person, need_id, version = context(employer, candidate)
        with SessionLocal() as db:
            email = db.get(User, company['id']).email
        assert other_tab.post('/api/v1/auth/login', json={'email': email, 'password': 'CorrectHorse123!'}).status_code == 200
        if existing:
            assert choose(employer, need_id, version, person['id']).status_code == 200
        barrier = Barrier(2)
        def race(client):
            barrier.wait(timeout=5)
            return choose(client, need_id, version, person['id'], saved=not existing, expected=int(existing)).status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            codes = list(executor.map(race, (employer, other_tab)))
        assert sorted(codes) == [200, 409]
        result = read(employer, need_id).json()['entries']
        assert len(result) == 1 and result[0]['saved'] == (not existing)
        assert result[0]['version'] == (2 if existing else 1)
