"""Bounded retry policy, including a lower-grade fallback after failure."""
from datetime import timedelta

from .security import aware

GRADE_ORDER = {'junior': 0, 'middle': 1}


def failed_higher_attempts(attempts, specialization, grade):
    rank = GRADE_ORDER[grade]
    return [attempt for attempt in attempts if attempt.specialization == specialization
            and GRADE_ORDER.get(attempt.grade, -1) > rank
            and attempt.state == 'scored' and attempt.outcome == 'failed']


def grade_change_cooling_down(profile, specialization, grade, attempts, current):
    if not profile.grade_changed_at or not profile.verified_grade:
        return False
    if (profile.verified_specialization, profile.verified_grade) == (specialization, grade):
        return False
    if aware(profile.grade_changed_at) + timedelta(days=30) <= current:
        return False
    lower_in_same_specialization = (profile.verified_specialization == specialization
        and GRADE_ORDER[grade] < GRADE_ORDER.get(profile.verified_grade, -1))
    failed_since_confirmation = any(attempt.submitted_at
        and aware(attempt.submitted_at) >= aware(profile.grade_changed_at)
        for attempt in failed_higher_attempts(attempts, specialization, grade))
    return not (lower_in_same_specialization and failed_since_confirmation)
