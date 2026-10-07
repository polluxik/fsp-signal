"""Demo-only paid-placement lifecycle, kept independent from candidate matching."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .domain_errors import DomainError
from .models import HiringNeed, PromotionCampaign, RoleVersion, User
from .product_events import product_event_data_mode, write_product_event
from .role_cards import is_role_fresh, terms_hash
from .schemas import RoleCardIn


DEMO_CAMPAIGN_DURATION = timedelta(days=14)


class PromotionError(DomainError):
    pass


def _eligible_role(db: Session, employer_id: str, need_id: str, at: datetime) -> tuple[HiringNeed, RoleVersion]:
    need = db.scalar(select(HiringNeed).where(HiringNeed.id == need_id).with_for_update())
    if need is None or need.employer_id != employer_id:
        raise PromotionError("NOT_FOUND", 404)
    if (need.publication_state != "active" or not need.discoverable
            or not is_role_fresh(need.confirmed_at, at)):
        raise PromotionError("PROMOTION_ROLE_NOT_ELIGIBLE", 409)
    version = db.scalar(select(RoleVersion).where(
        RoleVersion.need_id == need.id,
        RoleVersion.version == need.current_role_version,
    ))
    if version is None or version.terms_hash != terms_hash(version.payload or {}):
        raise PromotionError("PROMOTION_ROLE_NOT_ELIGIBLE", 409)
    try:
        RoleCardIn.model_validate(version.payload or {})
    except Exception as exc:
        raise PromotionError("PROMOTION_ROLE_NOT_ELIGIBLE", 409) from exc
    return need, version


def active_campaign_for_role(db: Session, need: HiringNeed, at: datetime) -> PromotionCampaign | None:
    if (need.publication_state != "active" or not need.discoverable
            or not is_role_fresh(need.confirmed_at, at)):
        return None
    current_version_id = db.scalar(select(RoleVersion.id).where(
        RoleVersion.need_id == need.id,
        RoleVersion.version == need.current_role_version,
    ))
    if current_version_id is None:
        return None
    return db.scalar(select(PromotionCampaign).where(
        PromotionCampaign.need_id == need.id,
        PromotionCampaign.employer_id == need.employer_id,
        PromotionCampaign.role_version_id == current_version_id,
        PromotionCampaign.active_from <= at,
        PromotionCampaign.active_until > at,
        PromotionCampaign.demo_only.is_(True),
    ).order_by(PromotionCampaign.created_at.desc()).limit(1))


def get_demo_campaign(db: Session, employer_id: str, need_id: str,
                      at: datetime) -> PromotionCampaign | None:
    need = db.scalar(select(HiringNeed).where(
        HiringNeed.id == need_id, HiringNeed.employer_id == employer_id,
    ))
    if need is None:
        raise PromotionError("NOT_FOUND", 404)
    return active_campaign_for_role(db, need, at)


def activate_demo_campaign(db: Session, employer_id: str, need_id: str,
                           at: datetime) -> tuple[PromotionCampaign, bool]:
    need, role_version = _eligible_role(db, employer_id, need_id, at)
    existing = db.scalar(select(PromotionCampaign).where(
        PromotionCampaign.need_id == need.id,
        PromotionCampaign.role_version_id == role_version.id,
        PromotionCampaign.active_from <= at,
        PromotionCampaign.active_until > at,
        PromotionCampaign.demo_only.is_(True),
    ).order_by(PromotionCampaign.created_at.desc()).limit(1))
    if existing:
        return existing, False

    campaign = PromotionCampaign(
        need_id=need.id,
        employer_id=employer_id,
        role_version_id=role_version.id,
        active_from=at,
        active_until=at + DEMO_CAMPAIGN_DURATION,
        demo_only=True,
        created_at=at,
    )
    db.add(campaign)
    db.flush()
    employer = db.get(User, employer_id)
    write_product_event(
        db,
        type="promotion_demo_activated",
        entity_type="promotion_campaign",
        entity_id=campaign.id,
        employer_id=employer_id,
        actor_id=employer_id,
        dedupe_key=f"promotion:{campaign.id}:activated",
        data_mode=product_event_data_mode(settings.app_mode, employer),
        payload={"role_version_id": role_version.id},
        at=at,
    )
    return campaign, True
