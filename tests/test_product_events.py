import pytest

from backend.db import SessionLocal
from backend.models import now
from backend.product_events import ProductEventError, write_product_event


def test_role_event_payload_is_allowlisted_and_deduplicated():
    with SessionLocal() as db:
        event = write_product_event(
            db, type="role_published", entity_type="role", entity_id="need-demo",
            employer_id=None, actor_id=None, dedupe_key="role-event-test-001",
            data_mode="synthetic", payload={"version": 1, "discoverable": True}, at=now(),
        )
        event_id = event.id
        assert write_product_event(
            db, type="role_published", entity_type="role", entity_id="need-demo",
            employer_id=None, actor_id=None, dedupe_key="role-event-test-001",
            data_mode="synthetic", payload={"version": 1, "discoverable": True}, at=now(),
        ).id == event_id
        with pytest.raises(ProductEventError, match="EVENT_DEDUPE_CONFLICT"):
            write_product_event(
                db, type="role_published", entity_type="role", entity_id="need-demo",
                employer_id=None, actor_id=None, dedupe_key="role-event-test-001",
                data_mode="synthetic", payload={"version": 1, "discoverable": False}, at=now(),
            )
        with pytest.raises(ValueError, match="allowlisted"):
            write_product_event(
                db, type="role_published", entity_type="role", entity_id="need-demo",
                employer_id=None, actor_id=None, dedupe_key="role-event-pii-test",
                data_mode="synthetic", payload={"version": 1, "email": "private@example.test"}, at=now(),
            )
        db.commit()


def test_held_interview_event_is_allowlisted_and_deduplicated():
    with SessionLocal() as db:
        payload = {"state_version": 2, "role_version_id": "role-version-held-1"}
        event = write_product_event(
            db, type="interview_held", entity_type="invitation", entity_id="held-invitation-1",
            employer_id=None, actor_id=None, dedupe_key="held-invitation-1:interview-held",
            data_mode="synthetic", payload=payload, at=now(),
        )
        replay = write_product_event(
            db, type="interview_held", entity_type="invitation", entity_id="held-invitation-1",
            employer_id=None, actor_id=None, dedupe_key="held-invitation-1:interview-held",
            data_mode="synthetic", payload=payload, at=now(),
        )

        assert replay.id == event.id
        assert replay.type == "interview_held"
        assert replay.payload == payload
        db.commit()


def test_sponsored_impression_is_deduplicated_and_payload_rejects_private_data():
    with SessionLocal() as db:
        payload = {"role_version_id": "sponsored-role-version", "placement": "candidate_roles_shelf"}
        event = write_product_event(
            db, type="sponsored_role_impression", entity_type="promotion_campaign",
            entity_id="sponsored-campaign-1", employer_id=None, actor_id=None,
            dedupe_key="sponsored-impression-candidate-campaign-day",
            data_mode="synthetic", payload=payload, at=now(),
        )
        replay = write_product_event(
            db, type="sponsored_role_impression", entity_type="promotion_campaign",
            entity_id="sponsored-campaign-1", employer_id=None, actor_id=None,
            dedupe_key="sponsored-impression-candidate-campaign-day",
            data_mode="synthetic", payload=payload, at=now(),
        )
        assert replay.id == event.id
        with pytest.raises(ValueError, match="allowlisted"):
            write_product_event(
                db, type="sponsored_role_decision", entity_type="promotion_campaign",
                entity_id="sponsored-campaign-1", employer_id=None, actor_id=None,
                dedupe_key="sponsored-decision-private-data",
                data_mode="synthetic",
                payload={"role_version_id": "sponsored-role-version", "action": "saved",
                         "email": "candidate@example.test"},
                at=now(),
            )
        db.commit()
