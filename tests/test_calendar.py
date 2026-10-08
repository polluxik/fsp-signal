from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier, Event

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from backend import meeting_ai
from backend.config import settings
from backend.db import SessionLocal, engine
from backend.main import app
from backend.models import AvailabilitySlot, InterviewCalendar, InterviewMeeting
from backend.security import aware
from backend.models import now
from test_flow import csrf, register_verified
from test_invitations_v2 import _candidate_evidence_id, _invitation_payload, _publish_role
from test_search_snapshots import make_candidate_profile, make_search_context


def prepare(employer, candidate):
    employer_user, candidate_user, need_id, _ = make_search_context(employer, candidate)
    version_id = _publish_role(employer, need_id)
    invitation = send_accept(employer, candidate, candidate_user, need_id, version_id)
    calendar = employer.get('/api/v1/employer/calendar').json()
    return employer_user, candidate_user, need_id, version_id, invitation, calendar


def send_accept(employer, candidate, candidate_user, need_id, version_id):
    invitation = employer.post('/api/v1/employer/invitations', headers=csrf(employer) | {
        'Idempotency-Key': f'calendar-{candidate_user["id"]}'}, json=_invitation_payload(
            candidate_user['id'], need_id, version_id, _candidate_evidence_id(candidate))).json()
    accepted = candidate.post(f'/api/v1/invitations/{invitation["id"]}/accept', headers=csrf(candidate), json={
        'expected_terms_hash': invitation['terms_hash'], 'expected_preferences_version': 1})
    assert accepted.status_code == 200, accepted.text
    return invitation


def availability(employer, minutes=360, duration=30):
    start = (now() + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    payload = {'starts_at': start.isoformat(), 'ends_at': (start + timedelta(minutes=minutes)).isoformat(),
               'duration_minutes': duration}
    response = employer.post('/api/v1/employer/calendar/availability', headers=csrf(employer), json=payload)
    assert response.status_code == 201, response.text
    return payload, response.json()['slots']


def book(candidate, calendar, invitation, slot):
    token = calendar['public_url'].rsplit('/', 1)[-1]
    return candidate.post(f'/api/v1/calendars/{token}/book', headers=csrf(candidate), json={
        'slot_id': slot['id'], 'invitation_id': invitation['id']})


def put(candidate, meeting, path, **fields):
    return candidate.put(f'/api/v1/meetings/{meeting["id"]}/{path}', headers=csrf(candidate),
                         json={'expected_version': meeting['version'], **fields})


def test_calendar_initialization_is_idempotent_under_concurrent_first_reads():
    email = f"calendar-race-{now().timestamp()}@example.test"
    with TestClient(app) as first, TestClient(app) as second:
        employer = register_verified(first, email, "employer")
        assert second.post("/api/v1/auth/login", json={
            "email": email, "password": "CorrectHorse123!",
        }).status_code == 200
        barrier = Barrier(2)

        def read_calendar(client):
            barrier.wait(timeout=10)
            response = client.get("/api/v1/employer/calendar")
            return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [future.result(timeout=30) for future in (
                pool.submit(read_calendar, first), pool.submit(read_calendar, second)
            )]
        assert [status for status, _ in results] == [200, 200]
        assert results[0][1]["public_url"] == results[1][1]["public_url"]
        with SessionLocal() as db:
            assert len(db.scalars(select(InterviewCalendar).where(
                InterviewCalendar.employer_id == employer["id"])).all()) == 1


@pytest.mark.postgres
@pytest.mark.skipif(engine.dialect.name != 'postgresql', reason='requires dedicated PostgreSQL *_test database')
def test_concurrent_ranges_in_existing_calendar_cannot_create_overlapping_slots():
    email = f"calendar-range-race-{now().timestamp()}@example.test"
    with TestClient(app) as first, TestClient(app) as second:
        employer = register_verified(first, email, 'employer')
        assert second.post('/api/v1/auth/login', json={
            'email': email, 'password': 'CorrectHorse123!',
        }).status_code == 200
        assert first.get('/api/v1/employer/calendar').status_code == 200
        barrier = Barrier(2)
        first_insert = Event()
        competing_insert = Event()

        def hold_first_slot_insert(connection, cursor, statement, parameters, context, executemany):
            if not statement.lower().startswith('insert into availability_slots'):
                return
            if first_insert.is_set():
                competing_insert.set()
            else:
                first_insert.set()
                # Pause after the overlap check, before any slots are visible.
                # A competing request must wait at the employer lock; without
                # that lock it also inserts and produces two successful ranges.
                competing_insert.wait(timeout=1)
        start = (now() + timedelta(days=1)).replace(microsecond=0)
        payload = {'starts_at': start.isoformat(),
                   'ends_at': (start + timedelta(hours=1)).isoformat(), 'duration_minutes': 30}

        def add(client):
            barrier.wait(timeout=10)
            return client.post('/api/v1/employer/calendar/availability', headers=csrf(client), json=payload).status_code

        event.listen(engine, 'before_cursor_execute', hold_first_slot_insert)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(add, first), pool.submit(add, second)]
                assert sorted(future.result(timeout=30) for future in futures) == [201, 409]
        finally:
            event.remove(engine, 'before_cursor_execute', hold_first_slot_insert)
        with SessionLocal() as db:
            slots = db.scalars(select(AvailabilitySlot).where(AvailabilitySlot.employer_id == employer['id'])).all()
            assert len(slots) == 2


def test_hr_range_timezone_overlap_book_cancel_and_access():
    with TestClient(app) as employer, TestClient(app) as candidate, TestClient(app) as anonymous, TestClient(app) as stranger:
        _, _, _, _, invitation, calendar = prepare(employer, candidate)
        register_verified(stranger, f'stranger-{invitation["id"]}@example.test', 'employer')
        payload, slots = availability(employer)
        assert len(slots) == 12
        assert employer.post('/api/v1/employer/calendar/availability', headers=csrf(employer), json=payload).status_code == 409
        naive = {**payload, 'starts_at': payload['starts_at'].split('+')[0]}
        assert employer.post('/api/v1/employer/calendar/availability', headers=csrf(employer), json=naive).status_code == 422
        update = employer.put('/api/v1/employer/calendar', headers=csrf(employer), json={
            'timezone': 'America/New_York', 'call_url': 'https://meet.example.test/interview'})
        assert update.status_code == 200
        token = calendar['public_url'].rsplit('/', 1)[-1]
        public = anonymous.get(f'/api/v1/calendars/{token}').json()
        assert len(public['slots']) == 12 and public['timezone'] == 'America/New_York'
        assert 'call_url' not in public and 'candidate' not in str(public)
        booked = book(candidate, calendar, invitation, slots[0])
        assert booked.status_code == 201, booked.text
        meeting = booked.json()
        assert meeting['call_url'] == 'https://meet.example.test/interview'
        assert book(candidate, calendar, invitation, slots[0]).status_code == 409
        assert len(anonymous.get(f'/api/v1/calendars/{token}').json()['slots']) == 11
        assert employer.delete(f'/api/v1/employer/calendar/slots/{slots[0]["id"]}', headers=csrf(employer)).status_code == 409
        assert stranger.get('/api/v1/meetings').json() == []
        assert stranger.get(f'/api/v1/meetings/{meeting["id"]}/calendar.ics').status_code == 404
        ics = candidate.get(f'/api/v1/meetings/{meeting["id"]}/calendar.ics')
        assert ics.status_code == 200 and 'BEGIN:VEVENT' in ics.text and 'DTSTART:' in ics.text
        cancelled = candidate.post(f'/api/v1/meetings/{meeting["id"]}/cancel', headers=csrf(candidate),
                                   json={'expected_version': meeting['version']})
        assert cancelled.status_code == 200
        assert len(anonymous.get(f'/api/v1/calendars/{token}').json()['slots']) == 12
        assert employer.delete(f'/api/v1/employer/calendar/slots/{slots[0]["id"]}', headers=csrf(employer)).status_code == 200
        assert book(candidate, calendar, invitation, slots[0]).status_code == 409


def test_booking_requires_accepted_invitation_and_20_minute_boundaries():
    with TestClient(app) as employer, TestClient(app) as candidate:
        _, _, _, _, invitation, calendar = prepare(employer, candidate)
        payload, slots = availability(employer, 120, 20)
        assert len(slots) == 6
        invalid = {**payload, 'ends_at': (now() + timedelta(days=2)).isoformat()}
        assert employer.post('/api/v1/employer/calendar/availability', headers=csrf(employer), json=invalid).status_code == 422
        with SessionLocal() as db:
            from backend.models import Invitation
            db.get(Invitation, invitation['id']).state = 'sent'
            db.commit()
        assert book(candidate, calendar, invitation, slots[0]).status_code == 403
        assert employer.post('/api/v1/employer/calendar/availability', json=payload).status_code == 403


def test_materials_recording_consent_versions_and_privacy(monkeypatch):
    with TestClient(app) as employer, TestClient(app) as candidate, TestClient(app) as stranger:
        _, _, _, _, invitation, calendar = prepare(employer, candidate)
        _, slots = availability(employer, 30)
        meeting = book(candidate, calendar, invitation, slots[0]).json()
        assert put(candidate, meeting, 'materials', notes='Обсудить API', transcript='Текст').status_code == 403
        meeting = put(candidate, meeting, 'recording-consent', consent=True).json()
        meeting = put(employer, meeting, 'recording-consent', consent=True).json()
        assert put(candidate, meeting, 'materials', notes='Обсудить API', transcript='Текст').status_code == 409
        with SessionLocal() as db:
            slot = db.get(AvailabilitySlot, slots[0]['id'])
            slot.starts_at, slot.ends_at = now() - timedelta(hours=1), now() - timedelta(minutes=30)
            db.commit()
        audio = b'RIFF' + (40).to_bytes(4, 'little') + b'WAVEfmt ' + b'\0' * 40
        uploaded = candidate.post(f'/api/v1/meetings/{meeting["id"]}/recording?expected_version={meeting["version"]}',
            headers=csrf(candidate), files={'file': ('call.wav', audio, 'audio/wav')})
        assert uploaded.status_code == 200, uploaded.text
        meeting = uploaded.json()
        assert meeting['has_recording']
        assert candidate.get(f'/api/v1/meetings/{meeting["id"]}/recording').content == audio
        assert stranger.get(f'/api/v1/meetings/{meeting["id"]}/recording').status_code == 401
        meeting = put(candidate, meeting, 'materials', notes='Общие заметки', transcript='Кандидат: обсудили Python. HR: следующий шаг — задача по API.').json()
        stale = put(employer, {**meeting, 'version': meeting['version'] - 1}, 'materials', notes='старое', transcript='')
        assert stale.status_code == 409
        monkeypatch.setattr('backend.scheduling.meeting_summary', lambda text: {
            'summary': 'Обсудили Python.', 'decisions': [], 'next_steps': ['Задача по API'], 'open_questions': []})
        result = candidate.post(f'/api/v1/meetings/{meeting["id"]}/summary', headers=csrf(candidate), json={
            'expected_version': meeting['version'], 'external_ai_consent': False})
        assert result.status_code == 422
        result = candidate.post(f'/api/v1/meetings/{meeting["id"]}/summary', headers=csrf(candidate), json={
            'expected_version': meeting['version'], 'external_ai_consent': True})
        assert result.status_code == 200, result.text
        meeting = result.json()
        assert meeting['summary']['next_steps'] == ['Задача по API']
        meeting = put(candidate, meeting, 'recording-consent', consent=False).json()
        assert meeting['transcript'] == '' and meeting['summary'] is None and not meeting['has_recording']
        assert candidate.get(f'/api/v1/meetings/{meeting["id"]}/recording').status_code == 403
        grants = candidate.get('/api/v1/candidate/contact-grants').json()
        candidate.post(f'/api/v1/candidate/contact-grants/{grants[0]["id"]}/revoke', headers=csrf(candidate))
        saved = employer.get('/api/v1/meetings').json()[0]
        assert saved['access_revoked'] and saved['notes'] == ''
        assert put(employer, meeting, 'materials', notes='blocked', transcript='').status_code == 403


def test_ai_summary_is_bounded_redacts_contacts_and_handles_provider_errors():
    configured = replace(settings, frontierai_api_key='fixture-only')
    seen = []
    def handler(request):
        seen.append(request.content.decode())
        return httpx.Response(200, json={'choices': [{'message': {'content':
            '{"summary":"Обсудили Python","decisions":[],"next_steps":[],"open_questions":[]}'}}]})
    assert meeting_ai.meeting_summary('Связь person@example.test, обсудили Python.', configured=configured,
                                      transport=httpx.MockTransport(handler))['summary'] == 'Обсудили Python'
    assert 'person@example.test' not in seen[0]
    with pytest.raises(Exception) as error:
        meeting_ai.meeting_summary('Текст', configured=configured, transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={'choices': []})))
    assert error.value.status_code == 502


@pytest.mark.postgres
@pytest.mark.skipif(engine.dialect.name != 'postgresql', reason='requires dedicated PostgreSQL *_test database')
def test_two_candidates_cannot_book_the_same_slot_concurrently():
    with TestClient(app) as employer, TestClient(app) as first, TestClient(app) as second:
        _, _, need_id, version_id, invitation1, calendar = prepare(employer, first)
        candidate2 = make_candidate_profile(second)
        invitation2 = send_accept(employer, second, candidate2, need_id, version_id)
        _, slots = availability(employer, 30)
        barrier = Barrier(2)
        def race(client, invitation):
            barrier.wait(timeout=10)
            return book(client, calendar, invitation, slots[0]).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(race, first, invitation1), pool.submit(race, second, invitation2)]
            assert sorted(future.result(timeout=30) for future in futures) == [201, 409]
        with SessionLocal() as db:
            assert len(db.scalars(select(InterviewMeeting).where(
                InterviewMeeting.slot_id == slots[0]['id'], InterviewMeeting.state == 'scheduled')).all()) == 1
