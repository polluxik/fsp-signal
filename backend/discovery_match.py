"""Explainable candidate discovery score; never a hiring probability."""
from collections import Counter
import math
import re

from sqlalchemy import select

from .ai_assistant import redact_contact_details
from .matching import score_profile_v2
from .models import CandidateProfile, RoleDecision, User
from .preferences import is_blocked, preferences_data
from .schemas import RoleCardIn

_STOP = set("и в на с по для из о к у не это как что мы вы он она они но или до от за при будет есть работа работать команда опыт навыки года лет обязанности требования кандидата компании the a an and or of to in with for is are you we this that work team experience".split())


def _tokens(text):
    return Counter(token for token in re.findall(r"[\w+#]+", redact_contact_details(text).casefold())
                   if len(token) > 2 and token not in _STOP and not token.isdigit())


def _cosine(left, right):
    if not left or not right:
        return None
    norm = math.sqrt(sum(v*v for v in left.values()) * sum(v*v for v in right.values()))
    return sum(value * right.get(token, 0) for token, value in left.items()) / norm


def discovery_match(db, profile, need, version):
    empty = {"percent": None, "components": [], "peer_signal": None,
             "algorithm_version": "discovery_match_v1"}
    if not profile:
        return empty
    role = RoleCardIn.model_validate(version.payload)
    own = _tokens(" ".join([profile.summary or "", *(profile.skills or []),
                            *preferences_data(profile).get("preferred_tasks", [])]))
    role_text = _tokens(" ".join([role.title, role.description, role.first_30_days, *role.stack]))
    signals = []
    text_score = _cosine(own, role_text)
    if text_score is not None:
        signals.append(("Описание и задачи", text_score, .45))
    skills = {s.casefold() for s in (profile.skills or [])}
    skills |= {s.casefold() for s in preferences_data(profile).get("preferred_stack", [])}
    if role.stack and skills:
        signals.append(("Заявленный и желаемый стек", len(skills & {s.casefold() for s in role.stack}) / len(role.stack), .25))
    if (profile.verified_specialization, profile.verified_grade) == (role.specialization, role.grade):
        assessment = score_profile_v2(profile, role)
        competency = assessment.components.get("competencies")
        if competency is not None:
            signals.append(("Проверенные компетенции" if profile.verification_source != "synthetic_fixture"
                            else "Компетенции демо-профиля", competency, .20))
    # A save remains private. Only an opted-in, published cohort of >=5 others is used.
    peers = db.execute(select(CandidateProfile, User, RoleDecision.preferences_version).join(User, User.id == CandidateProfile.user_id)
        .join(RoleDecision, RoleDecision.candidate_id == User.id).where(
            RoleDecision.need_id == need.id, RoleDecision.role_version_id == version.id,
            RoleDecision.action == "saved", User.id != profile.user_id,
            CandidateProfile.recommendation_consent.is_(True),
            CandidateProfile.published_at.is_not(None), CandidateProfile.consent_processing_at.is_not(None),
            CandidateProfile.adult_attested_at.is_not(None), CandidateProfile.available.is_(True)
        ).limit(500)).all()
    peers = [(p, u) for p, u, saved_version in peers if not is_blocked(p, need.employer_id)
             and not is_blocked(profile, need.employer_id)
             and p.preferences_version == saved_version
             and (u.origin == "synthetic_fixture") == (profile.verification_source == "synthetic_fixture")]
    peer_signal = None
    if len(peers) >= 5 and own:
        centroid = Counter()
        common_skills = Counter()
        for peer, _ in peers:
            tokens = _tokens(" ".join([peer.summary or "", *(peer.skills or [])]))
            size = math.sqrt(sum(v*v for v in tokens.values())) or 1
            centroid.update({token: value / size for token, value in tokens.items()})
            common_skills.update({s.casefold() for s in peer.skills or []
                                  if len(s) <= 80 and redact_contact_details(s) == s})
        similarity = _cosine(own, centroid)
        if similarity is not None:
            signals.append(("Интерес похожих кандидатов", similarity, .10))
            peer_signal = {"percent": round(similarity * 100), "cohort_size": len(peers),
                "common_skills": [skill for skill, count in common_skills.most_common(8) if count >= 3],
                "synthetic": all(u.origin == "synthetic_fixture" for _, u in peers)}
    if not signals:
        return empty
    total_weight = sum(weight for _, _, weight in signals)
    return {"percent": round(sum(value * weight for _, value, weight in signals) / total_weight * 100),
        "components": [{"label": label, "percent": round(value * 100),
                        "weight_percent": round(weight / total_weight * 100)} for label, value, weight in signals],
        "peer_signal": peer_signal, "algorithm_version": "discovery_match_v1"}
