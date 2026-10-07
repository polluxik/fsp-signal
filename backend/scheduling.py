"""UTC availability, serialized bookings and private meeting materials."""
from datetime import datetime, timedelta, timezone
from io import BytesIO
import secrets
import os
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .meeting_ai import meeting_summary, transcribe_audio
from .models import (AssistantUsage, AvailabilitySlot, CandidateProfile, ContactGrant, EmployerProfile,
                     InterviewCalendar, InterviewMeeting, Invitation, MailOutbox, User, now)
from .preferences import is_blocked
from .security import aware, csrf_guard, get_user, require

router = APIRouter(prefix="/api/v1", tags=["interview-calendar"])
MAX_AUDIO_BYTES = 15 * 1024 * 1024


def fail(code, status=409):
    raise HTTPException(status, detail=code)


class CalendarSettingsIn(BaseModel):
    timezone: str = "Europe/Moscow"
    call_url: str = Field(default="", max_length=500)

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise ValueError("unknown timezone") from None
        return value

    @field_validator("call_url")
    @classmethod
    def valid_url(cls, value):
        value = value.strip()
        if value and (urlsplit(value).scheme != "https" or not urlsplit(value).hostname
                      or urlsplit(value).username or urlsplit(value).password):
            raise ValueError("use an HTTPS meeting URL without credentials")
        return value


class AvailabilityIn(BaseModel):
    starts_at: datetime
    ends_at: datetime
    duration_minutes: int = Field(default=30)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def timestamp_has_zone(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone offset is required")
        return value.astimezone(timezone.utc)

    @field_validator("duration_minutes")
    @classmethod
    def duration(cls, value):
        if value not in (20, 30):
            raise ValueError("choose 20 or 30 minutes")
        return value


class BookingIn(BaseModel):
    slot_id: str
    invitation_id: str


class VersionIn(BaseModel):
    expected_version: int = Field(ge=1)


class ConsentIn(VersionIn):
    consent: bool


class MaterialsIn(VersionIn):
    notes: str = Field(default="", max_length=12000)
    transcript: str = Field(default="", max_length=12000)


class SummaryIn(VersionIn):
    external_ai_consent: bool


def _employer_lock(db, employer_id):
    db.scalar(select(User).where(User.id == employer_id).with_for_update())


def _calendar(db, employer_id):
    _employer_lock(db, employer_id)
    calendar = db.get(InterviewCalendar, employer_id)
    if not calendar:
        calendar = InterviewCalendar(employer_id=employer_id, public_token=secrets.token_urlsafe(24))
        db.add(calendar)
        db.flush()
    return calendar


def _calendar_url(calendar):
    return f"{settings.public_base_url}/calendar/{calendar.public_token}"


def _grant(db, invitation):
    return db.scalar(select(ContactGrant).where(
        ContactGrant.invitation_id == invitation.id, ContactGrant.revoked_at.is_(None))
        .execution_options(populate_existing=True))


def _pair_allowed(db, invitation):
    profile = db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == invitation.candidate_id)
                        .execution_options(populate_existing=True))
    return invitation.state == "accepted" and _grant(db, invitation) and profile and not is_blocked(
        profile, invitation.employer_id)


def _slot_data(slot, booked=False):
    return {"id": slot.id, "starts_at": aware(slot.starts_at).isoformat(),
            "ends_at": aware(slot.ends_at).isoformat(), "booked": booked}


def _calendar_data(db, calendar, *, owner=False):
    taken = select(InterviewMeeting.id).where(
        InterviewMeeting.slot_id == AvailabilitySlot.id, InterviewMeeting.state == "scheduled").exists()
    rows = db.execute(select(AvailabilitySlot, taken.label("booked")).where(
        AvailabilitySlot.employer_id == calendar.employer_id, AvailabilitySlot.active.is_(True),
        AvailabilitySlot.starts_at > now(), AvailabilitySlot.starts_at <= now() + timedelta(days=90)
    ).order_by(AvailabilitySlot.starts_at).limit(2000)).all()
    company = db.get(EmployerProfile, calendar.employer_id)
    result = {"company_name": company.company_name if company else "Работодатель",
              "timezone": calendar.timezone,
              "slots": [_slot_data(slot, booked) for slot, booked in rows if owner or not booked]}
    if owner:
        result.update(public_url=_calendar_url(calendar), call_url=calendar.call_url)
    return result


@router.get("/employer/calendar")
def read_calendar(user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    calendar = _calendar(db, user.id)
    result = _calendar_data(db, calendar, owner=True)
    db.commit()
    return result


@router.put("/employer/calendar", dependencies=[Depends(csrf_guard)])
def update_calendar(data: CalendarSettingsIn, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    calendar = _calendar(db, user.id)
    calendar.timezone, calendar.call_url = data.timezone, data.call_url
    db.commit()
    return _calendar_data(db, calendar, owner=True)


@router.post("/employer/calendar/availability", status_code=201, dependencies=[Depends(csrf_guard)])
def add_availability(data: AvailabilityIn, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    if (data.starts_at < now() + timedelta(minutes=5) or data.ends_at > now() + timedelta(days=90)
            or data.ends_at <= data.starts_at or data.ends_at - data.starts_at > timedelta(hours=12)):
        fail("AVAILABILITY_RANGE_INVALID", 422)
    seconds = (data.ends_at - data.starts_at).total_seconds()
    if seconds % (data.duration_minutes * 60):
        fail("AVAILABILITY_NOT_DIVISIBLE", 422)
    calendar = _calendar(db, user.id)
    if db.scalar(select(AvailabilitySlot.id).where(
        AvailabilitySlot.employer_id == user.id, AvailabilitySlot.active.is_(True),
        AvailabilitySlot.starts_at < data.ends_at, AvailabilitySlot.ends_at > data.starts_at).limit(1)):
        fail("AVAILABILITY_OVERLAP")
    start = data.starts_at
    while start < data.ends_at:
        end = start + timedelta(minutes=data.duration_minutes)
        db.add(AvailabilitySlot(employer_id=user.id, starts_at=start, ends_at=end))
        start = end
    db.commit()
    return _calendar_data(db, calendar, owner=True)


@router.delete("/employer/calendar/slots/{slot_id}", dependencies=[Depends(csrf_guard)])
def remove_slot(slot_id: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "employer")
    _employer_lock(db, user.id)
    slot = db.scalar(select(AvailabilitySlot).where(
        AvailabilitySlot.id == slot_id, AvailabilitySlot.employer_id == user.id).with_for_update())
    if not slot:
        fail("NOT_FOUND", 404)
    if db.scalar(select(InterviewMeeting.id).where(
        InterviewMeeting.slot_id == slot.id, InterviewMeeting.state == "scheduled")):
        fail("SLOT_ALREADY_BOOKED")
    slot.active = False
    db.commit()
    return {"status": "removed"}


@router.get("/calendars/{token}")
def public_calendar(token: str, response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    calendar = db.scalar(select(InterviewCalendar).where(InterviewCalendar.public_token == token))
    if not calendar:
        fail("NOT_FOUND", 404)
    return _calendar_data(db, calendar)


@router.get("/invitations/{invitation_id}/calendar")
def invitation_calendar(invitation_id: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    invitation = db.get(Invitation, invitation_id)
    if not invitation or user.id not in (invitation.candidate_id, invitation.employer_id):
        fail("NOT_FOUND", 404)
    if not _pair_allowed(db, invitation):
        fail("CONTACT_LOCKED", 403)
    calendar = _calendar(db, invitation.employer_id)
    result = {"url": _calendar_url(calendar), "invitation_id": invitation.id}
    db.commit()
    return result


def _meeting(db, meeting_id, user, *, lock=False, materials=False):
    initial = db.get(InterviewMeeting, meeting_id)
    if not initial or user.id not in (initial.candidate_id, initial.employer_id):
        fail("NOT_FOUND", 404)
    if materials and lock:
        # Privacy changes lock the candidate before grants. Use the same order
        # before editing meeting materials, including after an external AI call.
        db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == initial.candidate_id)
                  .with_for_update().execution_options(populate_existing=True))
    query = select(InterviewMeeting).where(InterviewMeeting.id == meeting_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    meeting = db.scalar(query)
    if not meeting or user.id not in (meeting.candidate_id, meeting.employer_id):
        fail("NOT_FOUND", 404)
    if materials and user.id == meeting.employer_id and not _pair_allowed(
            db, db.get(Invitation, meeting.invitation_id)):
        fail("CONTACT_LOCKED", 403)
    return meeting


def _check_version(meeting, expected):
    if meeting.version != expected:
        fail("MEETING_VERSION_CONFLICT")


def _consented(meeting):
    if not (meeting.candidate_recording_consent and meeting.employer_recording_consent):
        fail("RECORDING_CONSENT_REQUIRED", 403)


def _meeting_data(db, meeting, viewer_id):
    slot = db.get(AvailabilitySlot, meeting.slot_id)
    invitation = db.get(Invitation, meeting.invitation_id)
    accessible = viewer_id == meeting.candidate_id or bool(_pair_allowed(db, invitation))
    return {"id": meeting.id, "invitation_id": meeting.invitation_id, "version": meeting.version,
            "state": meeting.state, "starts_at": aware(slot.starts_at).isoformat(),
            "ends_at": aware(slot.ends_at).isoformat(), "company_name": invitation.company_name,
            "candidate_alias": f"Кандидат #{meeting.candidate_id[:8]}",
            "call_url": meeting.call_url if accessible else "", "access_revoked": not accessible,
            "notes": meeting.notes if accessible else "", "transcript": meeting.transcript if accessible else "",
            "summary": meeting.summary if accessible else None,
            "has_recording": bool(meeting.recording_type) if accessible else False,
            "candidate_recording_consent": meeting.candidate_recording_consent,
            "employer_recording_consent": meeting.employer_recording_consent}


@router.post("/calendars/{token}/book", status_code=201, dependencies=[Depends(csrf_guard)])
def book_slot(token: str, data: BookingIn, user: User = Depends(get_user), db: Session = Depends(get_db)):
    require(user, "candidate")
    calendar = db.scalar(select(InterviewCalendar).where(InterviewCalendar.public_token == token))
    if not calendar:
        fail("NOT_FOUND", 404)
    db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user.id).with_for_update())
    _employer_lock(db, calendar.employer_id)
    db.refresh(calendar)
    invitation = db.get(Invitation, data.invitation_id)
    if (not invitation or invitation.candidate_id != user.id
            or invitation.employer_id != calendar.employer_id):
        fail("NOT_FOUND", 404)
    if not _pair_allowed(db, invitation):
        fail("ACCEPT_INVITATION_FIRST", 403)
    slot = db.scalar(select(AvailabilitySlot).where(
        AvailabilitySlot.id == data.slot_id, AvailabilitySlot.employer_id == calendar.employer_id
    ).with_for_update())
    if not slot or not slot.active or aware(slot.starts_at) <= now() + timedelta(minutes=5):
        fail("SLOT_NOT_AVAILABLE")
    if db.scalar(select(InterviewMeeting.id).where(
        InterviewMeeting.state == "scheduled",
        or_(InterviewMeeting.slot_id == slot.id, InterviewMeeting.invitation_id == invitation.id))):
        fail("SLOT_ALREADY_BOOKED")
    # Do not allow the same candidate to book overlapping calls with two companies.
    if db.scalar(select(InterviewMeeting.id).join(AvailabilitySlot).where(
        InterviewMeeting.candidate_id == user.id, InterviewMeeting.state == "scheduled",
        AvailabilitySlot.starts_at < slot.ends_at, AvailabilitySlot.ends_at > slot.starts_at)):
        fail("MEETING_TIME_CONFLICT")
    meeting = InterviewMeeting(slot_id=slot.id, invitation_id=invitation.id,
                               employer_id=calendar.employer_id, candidate_id=user.id,
                               call_url=calendar.call_url)
    db.add(meeting)
    for participant_id in (user.id, calendar.employer_id):
        participant = db.get(User, participant_id)
        db.add(MailOutbox(recipient=participant.email, subject="Созвон назначен — ФСП Сигнал",
            body=f"Созвон назначен на {aware(slot.starts_at).isoformat()} (UTC). "
                 f"Время в вашем часовом поясе и ссылка: {settings.public_base_url}"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        fail("SLOT_ALREADY_BOOKED")
    return _meeting_data(db, meeting, user.id)


@router.get("/meetings")
def list_meetings(response: Response, user: User = Depends(get_user), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    meetings = db.scalars(select(InterviewMeeting).where(or_(
        InterviewMeeting.candidate_id == user.id, InterviewMeeting.employer_id == user.id
    )).order_by(InterviewMeeting.created_at.desc()).limit(100)).all()
    return [_meeting_data(db, meeting, user.id) for meeting in meetings]


@router.get("/meetings/capabilities")
def meeting_capabilities(user: User = Depends(get_user)):
    return {"summary": bool(settings.frontierai_api_key), "transcription": all(os.getenv(name) for name in (
        "TRANSCRIPTION_API_URL", "TRANSCRIPTION_API_KEY", "TRANSCRIPTION_MODEL"))}


@router.post("/meetings/{meeting_id}/cancel", dependencies=[Depends(csrf_guard)])
def cancel_meeting(meeting_id: str, data: VersionIn, user: User = Depends(get_user), db: Session = Depends(get_db)):
    initial = _meeting(db, meeting_id, user)
    _employer_lock(db, initial.employer_id)
    meeting = _meeting(db, meeting_id, user, lock=True)
    _check_version(meeting, data.expected_version)
    if meeting.state == "cancelled":
        return _meeting_data(db, meeting, user.id)
    meeting.state = "cancelled"
    meeting.version += 1
    for participant_id in (meeting.candidate_id, meeting.employer_id):
        db.add(MailOutbox(recipient=db.get(User, participant_id).email,
                         subject="Созвон отменён — ФСП Сигнал", body=f"Созвон отменён. {settings.public_base_url}"))
    db.commit()
    return _meeting_data(db, meeting, user.id)


@router.put("/meetings/{meeting_id}/recording-consent", dependencies=[Depends(csrf_guard)])
def recording_consent(meeting_id: str, data: ConsentIn, user: User = Depends(get_user), db: Session = Depends(get_db)):
    meeting = _meeting(db, meeting_id, user, lock=True, materials=True)
    _check_version(meeting, data.expected_version)
    if user.id == meeting.candidate_id:
        meeting.candidate_recording_consent = data.consent
    else:
        meeting.employer_recording_consent = data.consent
    if not data.consent:
        meeting.recording_data = meeting.recording_type = meeting.summary = None
        meeting.transcript = ""
    meeting.version += 1
    db.commit()
    return _meeting_data(db, meeting, user.id)


@router.put("/meetings/{meeting_id}/materials", dependencies=[Depends(csrf_guard)])
def save_materials(meeting_id: str, data: MaterialsIn, user: User = Depends(get_user), db: Session = Depends(get_db)):
    meeting = _meeting(db, meeting_id, user, lock=True, materials=True)
    _check_version(meeting, data.expected_version)
    if data.transcript:
        _consented(meeting)
        if aware(db.get(AvailabilitySlot, meeting.slot_id).ends_at) > now():
            fail("MEETING_NOT_FINISHED")
    if data.transcript != meeting.transcript:
        meeting.summary = None
    meeting.notes, meeting.transcript = data.notes, data.transcript
    meeting.version += 1
    db.commit()
    return _meeting_data(db, meeting, user.id)


def _audio_type(content: bytes, mime: str):
    mime = mime.split(";")[0]
    signatures = {"audio/webm": content.startswith(b"\x1aE\xdf\xa3"),
        "audio/ogg": content.startswith(b"OggS"),
        "audio/wav": content.startswith(b"RIFF") and content[8:12] == b"WAVE",
        "audio/mpeg": content.startswith(b"ID3") or (len(content) > 1 and content[0] == 255 and content[1] & 224 == 224),
        "audio/mp4": content[4:8] == b"ftyp"}
    if not signatures.get(mime):
        fail("AUDIO_FORMAT_INVALID", 422)
    return mime


@router.post("/meetings/{meeting_id}/recording", dependencies=[Depends(csrf_guard)])
def upload_recording(meeting_id: str, expected_version: int = Query(ge=1), file: UploadFile = File(...),
                     user: User = Depends(get_user), db: Session = Depends(get_db)):
    content = file.file.read(MAX_AUDIO_BYTES + 1)
    if not content or len(content) > MAX_AUDIO_BYTES:
        fail("AUDIO_TOO_LARGE", 413)
    mime = _audio_type(content, file.content_type or "")
    meeting = _meeting(db, meeting_id, user, lock=True, materials=True)
    _check_version(meeting, expected_version)
    _consented(meeting)
    if meeting.state != "scheduled" or aware(db.get(AvailabilitySlot, meeting.slot_id).starts_at) > now():
        fail("MEETING_NOT_STARTED")
    meeting.recording_data, meeting.recording_type = content, mime
    meeting.transcript, meeting.summary = "", None
    meeting.version += 1
    db.commit()
    return _meeting_data(db, meeting, user.id)


@router.get("/meetings/{meeting_id}/recording")
def download_recording(meeting_id: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    meeting = _meeting(db, meeting_id, user, materials=True)
    _consented(meeting)
    if not meeting.recording_type:
        fail("NOT_FOUND", 404)
    return StreamingResponse(BytesIO(meeting.recording_data), media_type=meeting.recording_type,
                             headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/meetings/{meeting_id}/calendar.ics")
def export_meeting(meeting_id: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    meeting = _meeting(db, meeting_id, user)
    slot = db.get(AvailabilitySlot, meeting.slot_id)
    stamp = lambda value: aware(value).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    content = "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//FSP Signal//Interviews//RU",
        "BEGIN:VEVENT", f"UID:{meeting.id}@fsp-signal", f"DTSTAMP:{stamp(meeting.created_at)}",
        f"DTSTART:{stamp(slot.starts_at)}", f"DTEND:{stamp(slot.ends_at)}", "SUMMARY:Созвон ФСП Сигнал",
        f"STATUS:{'CANCELLED' if meeting.state == 'cancelled' else 'CONFIRMED'}",
        f"SEQUENCE:{meeting.version}", "END:VEVENT", "END:VCALENDAR", ""])
    return Response(content, media_type="text/calendar", headers={"Cache-Control": "no-store",
                    "Content-Disposition": 'attachment; filename="interview.ics"'})


def _ai_usage(db, user_id, intent):
    _employer_lock(db, user_id)
    count = db.scalar(select(func.count(AssistantUsage.id)).where(
        AssistantUsage.user_id == user_id, AssistantUsage.created_at >= now() - timedelta(hours=1))) or 0
    if count >= 10:
        fail("AI_RATE_LIMIT_EXCEEDED", 429)
    db.add(AssistantUsage(user_id=user_id, intent=intent))
    db.commit()


@router.post("/meetings/{meeting_id}/summary", dependencies=[Depends(csrf_guard)])
def summarize_meeting(meeting_id: str, data: SummaryIn, user: User = Depends(get_user), db: Session = Depends(get_db)):
    meeting = _meeting(db, meeting_id, user, materials=True)
    _check_version(meeting, data.expected_version)
    _consented(meeting)
    if not data.external_ai_consent:
        fail("EXTERNAL_AI_CONSENT_REQUIRED", 422)
    if not meeting.transcript.strip():
        fail("TRANSCRIPT_REQUIRED", 422)
    transcript = meeting.transcript
    _ai_usage(db, user.id, "meeting_summary")
    summary = meeting_summary(transcript)
    meeting = _meeting(db, meeting_id, user, lock=True, materials=True)
    _check_version(meeting, data.expected_version)
    _consented(meeting)
    meeting.summary = summary
    meeting.version += 1
    db.commit()
    return _meeting_data(db, meeting, user.id)


@router.post("/meetings/{meeting_id}/transcribe", dependencies=[Depends(csrf_guard)])
def transcribe_meeting(meeting_id: str, data: SummaryIn, user: User = Depends(get_user), db: Session = Depends(get_db)):
    meeting = _meeting(db, meeting_id, user, materials=True)
    _check_version(meeting, data.expected_version)
    _consented(meeting)
    if not data.external_ai_consent:
        fail("EXTERNAL_AI_CONSENT_REQUIRED", 422)
    if not meeting.recording_type:
        fail("NOT_FOUND", 404)
    if aware(db.get(AvailabilitySlot, meeting.slot_id).ends_at) > now():
        fail("MEETING_NOT_FINISHED")
    audio, mime = meeting.recording_data, meeting.recording_type
    _ai_usage(db, user.id, "meeting_transcription")
    text = transcribe_audio(audio, mime)
    meeting = _meeting(db, meeting_id, user, lock=True, materials=True)
    _check_version(meeting, data.expected_version)
    _consented(meeting)
    meeting.transcript, meeting.summary = text, None
    meeting.version += 1
    db.commit()
    return _meeting_data(db, meeting, user.id)
