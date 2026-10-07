from uuid import uuid4

from fastapi.testclient import TestClient

from backend.db import SessionLocal
from backend.discovery_match import discovery_match
from backend.main import app
from backend.models import CandidateProfile, HiringNeed, RoleDecision, RoleVersion, User, now
from test_flow import csrf
from test_invitations_v2 import _publish_role
from test_search_snapshots import make_search_context


def test_match_has_explanation_and_no_fabricated_unknown_competencies():
    with TestClient(app) as employer, TestClient(app) as candidate:
        _, person, need_id, _ = make_search_context(employer, candidate)
        version_id = _publish_role(employer, need_id)
        with SessionLocal() as db:
            profile = db.get(CandidateProfile, person['id'])
            need, version = db.get(HiringNeed, need_id), db.get(RoleVersion, version_id)
            profile.summary = version.payload['description'] + ' ' + version.payload['first_30_days']
            matched = discovery_match(db, profile, need, version)
            profile.summary = 'Рисую акварели и выращиваю растения'
            unrelated = discovery_match(db, profile, need, version)
            assert matched['percent'] > unrelated['percent']
            assert all(0 <= component['percent'] <= 100 for component in matched['components'])
            assert not any('компетенции' in component['label'].casefold() for component in matched['components'])
            assert matched['peer_signal'] is None
            assert discovery_match(db, None, need, version)['percent'] is None
        consent = candidate.put('/api/v1/candidate/recommendations/consent', headers=csrf(candidate), json={'consent': True})
        assert consent.status_code == 200 and consent.json()['consent']
        assert candidate.get('/api/v1/candidate/recommendations/consent').json()['consent']
        assert employer.put('/api/v1/candidate/recommendations/consent', headers=csrf(employer), json={'consent': True}).status_code == 403


def test_peer_signal_requires_five_opted_in_current_published_profiles_and_never_exposes_texts():
    with TestClient(app) as employer, TestClient(app) as candidate:
        _, person, need_id, _ = make_search_context(employer, candidate)
        version_id = _publish_role(employer, need_id)
        with SessionLocal() as db:
            profile = db.get(CandidateProfile, person['id'])
            profile.summary = 'Python API PostgreSQL повторные события'
            need, version = db.get(HiringNeed, need_id), db.get(RoleVersion, version_id)
            peer_profiles = []
            for index in range(5):
                peer = User(email=f'cohort-{uuid4().hex}@example.test', password_hash='unused', role='candidate',
                            origin='direct_signup', email_verified_at=now())
                db.add(peer); db.flush()
                peer_profile = CandidateProfile(user_id=peer.id, full_name=f'Private name {index}',
                    summary=f'Python API PostgreSQL unique_private_text_{index}', skills=['Python', 'PostgreSQL'],
                    recommendation_consent=index < 4, available=True, consent_processing_at=now(),
                    published_at=now(), adult_attested_at=now(), verification_source='assessment')
                db.add(peer_profile)
                db.add(RoleDecision(candidate_id=peer.id, need_id=need.id, role_version_id=version.id,
                                    action='saved', preferences_version=1))
                peer_profiles.append(peer_profile)
            db.flush()
            assert discovery_match(db, profile, need, version)['peer_signal'] is None
            peer_profiles[-1].recommendation_consent = True
            db.flush()
            result = discovery_match(db, profile, need, version)
            assert result['peer_signal']['cohort_size'] == 5
            assert result['peer_signal']['common_skills'] == ['python', 'postgresql'] or set(result['peer_signal']['common_skills']) == {'python', 'postgresql'}
            assert 'unique_private_text' not in str(result) and 'Private name' not in str(result) and '@' not in str(result)
            peer_profiles[0].preferences_version += 1
            db.flush()
            assert discovery_match(db, profile, need, version)['peer_signal'] is None
