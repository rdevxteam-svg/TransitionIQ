import hashlib
import hmac
import logging
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Literal
from urllib.parse import quote
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator

from career import CAREER_HISTORY
from resume_matching import compare_resume, extract_resume_text, jd_skills
from workflow import (KNOWLEDGE, ONBOARDING_CHECKS, READINESS_QUESTIONS, SCENARIO,
                      TRS_THRESHOLD, evaluate_interview, evaluate_readiness, learning_paths)
from sqlalchemy import JSON, Column, Integer, LargeBinary, String, Text, UniqueConstraint, create_engine, delete, select
from sqlalchemy.orm import Session, declarative_base, deferred

DATABASE_URL = os.getenv("TRANSITION_DATABASE_URL", "sqlite:///./transition.db")
engine = create_engine(DATABASE_URL)
Base = declarative_base()
POLICY_VERSION = "demo-v1"
logger = logging.getLogger(__name__)

# Synthetic identities used exclusively by the local demonstration.
ACCOUNT_NAMES = {
    "manager": "Receiving Engagement Manager",
    "devuser": "Dev User",
    "vikram": "Vikram Sethi",
    "anika": "Anika Rao",
    "leo": "Leo Chen",
    "sme": "Transition Partner",
    "release": "Releasing Engagement Manager",
    "lnd": "Learning & Development",
}
PROFILES = {
    "vikram": {"role": "Backend Engineer", "skills": {"Python": 5, "APIs": 4, "Reliability": 3}},
    "anika": {"role": "Software Engineer", "skills": {"Python": 3, "APIs": 3, "Reliability": 2}},
    "leo": {"role": "Software Engineer", "skills": {"Python": 4}},
}
EMPLOYEE = "employee"
ENGAGEMENT_MANAGER = "engagement_manager"
TRANSITION_PARTNER = "transition_partner"
LEARNING_TEAM = "learning_team"
RECEIVING = "receiving"
RELEASING = "releasing"
ENGAGEMENT_SIDES = {"manager": RECEIVING, "devuser": RECEIVING, "release": RELEASING}
ACCOUNT_ROLES = {
    **dict.fromkeys(ENGAGEMENT_SIDES, ENGAGEMENT_MANAGER),
    "sme": TRANSITION_PARTNER,
    "lnd": LEARNING_TEAM,
    **dict.fromkeys(PROFILES, EMPLOYEE),
}
COOKIE_NAME = "transition_session"
SESSION_SECONDS = 8 * 60 * 60
RESUME_INTERVAL_DAYS = 90
RESUME_MAX_BYTES = 5 * 1024 * 1024
RESUME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

STAGES = {
    "sme_review": ("fitment", "retry_requested"),
    "fitment": ("receiving_review", "not_selected"),
    "client_interview": ("receiving_review", "not_selected"),
    "activation_review": ("activated", "readiness_assessment"),
    "receiving_review": ("release_review", "receiving_hold"),
    "release_review": ("approved", "release_hold"),
}
ACTIONS = {
    "interested": (EMPLOYEE, "draft_plan"), "planning": (EMPLOYEE, "confirm_plan"),
    "practice": (EMPLOYEE, "submit_attempt"), "retry_requested": (EMPLOYEE, "submit_attempt"),
    "sme_review": (TRANSITION_PARTNER, "decide"),
    "fitment": (TRANSITION_PARTNER, "schedule_interview", "decide"),
    "client_interview": (RECEIVING, "schedule_interview", "decide"),
    "receiving_review": (RECEIVING, "decide"), "receiving_hold": (RECEIVING, "resume"),
    "release_review": (RELEASING, "decide"), "release_hold": (RELEASING, "resume"),
    "approved": (RECEIVING, "provision_access"),
    "onboarding": (EMPLOYEE, "complete_task"),
    "readiness_assessment": (EMPLOYEE, "assess_readiness"),
    "activation_review": (RECEIVING, "decide"),
}


class Opportunity(Base):
    __tablename__ = "opportunities"
    id = Column(String, primary_key=True)
    details = Column(JSON, nullable=False)


class Application(Base):
    __tablename__ = "applications"
    id = Column(String, primary_key=True)
    opportunity_id = Column(String, nullable=False)
    employee = Column(String, nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    record = Column(JSON, nullable=False)
    __mapper_args__ = {"version_id_col": revision}


class Aspiration(Base):
    __tablename__ = "aspirations"
    employee = Column(String, primary_key=True)
    goal = Column(String, nullable=False)


class Job(Base):
    __tablename__ = "jobs"
    id = Column(String, primary_key=True)
    application_id = Column(String, nullable=False, index=True)
    kind = Column(String, nullable=False)
    status = Column(String, nullable=False)
    details = Column(JSON, nullable=False)
    available = Column(Integer, nullable=False, default=0)


class Credential(Base):
    __tablename__ = "credentials"
    username = Column(String, primary_key=True)
    salt = Column(String(32), nullable=False)
    password_hash = Column(String(64), nullable=False)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash = Column(String(64), primary_key=True)
    username = Column(String, nullable=False, index=True)
    credential_salt = Column(String(32), nullable=False)
    expires_at = Column(Integer, nullable=False, index=True)


class EmployeeResume(Base):
    __tablename__ = "employee_resumes"
    employee = Column(String, primary_key=True)
    filename = Column(String(180), nullable=False)
    media_type = Column(String(100), nullable=False)
    updated_at = Column(String, nullable=False)
    content = deferred(Column(LargeBinary, nullable=False))


class ResumeMatchText(Base):
    __tablename__ = "resume_match_text"
    employee = Column(String, primary_key=True)
    resume_updated_at = Column(String, nullable=False)
    text = Column(Text, nullable=False)


class LearningTicket(Base):
    __tablename__ = "learning_tickets"
    __table_args__ = (UniqueConstraint("employee", "opportunity_id"),)
    id = Column(String(32), primary_key=True)
    employee = Column(String, nullable=False)
    opportunity_id = Column(String, nullable=False)
    subject = Column(String(180), nullable=False)
    message = Column(Text, nullable=False)
    skills = Column(JSON, nullable=False)
    created_at = Column(String, nullable=False)
    acknowledged_at = Column(String, nullable=True)


@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine, tables=[Credential.__table__, LoginSession.__table__,
                                             LearningRequest.__table__, EmployeeResume.__table__,
                                             ResumeMatchText.__table__, LearningTicket.__table__])
    yield


app = FastAPI(title="Transition IQ", lifespan=lifespan)


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class RoleInput(BaseModel):
    title: str = Field(min_length=2, max_length=100)
    project: str = Field(min_length=2, max_length=100)
    growth: str = Field(min_length=2, max_length=500)
    needed_by: str = Field(max_length=30)
    criteria: dict[str, int] = Field(default_factory=dict, max_length=10)
    description: str = Field(default="", max_length=12000)
    experience: str = Field(default="", max_length=500)
    interview_questions: list[str] = Field(default_factory=list, max_length=6)
    client_interview_required: bool = False
    publish: bool = True

    @field_validator("interview_questions")
    @classmethod
    def validate_questions(cls, questions):
        cleaned = [question.strip() for question in questions]
        if any(not 5 <= len(question) <= 400 for question in cleaned):
            raise ValueError("Each interview question must have 5 to 400 characters.")
        return cleaned

    @field_validator("criteria")
    @classmethod
    def validate_levels(cls, criteria):
        if any(not skill.strip() or len(skill) > 60 or level < 1 or level > 5 for skill, level in criteria.items()):
            raise ValueError("Provide named skills with required levels from 1 to 5.")
        return criteria


class GoalInput(BaseModel):
    goal: str = Field(min_length=2, max_length=500)


class Interest(BaseModel):
    interested: bool


class Change(BaseModel):
    revision: int


class PlanInput(Change):
    alignment: str = Field(min_length=2, max_length=500)


class AttemptInput(Change):
    answer: str | None = Field(default=None, min_length=12, max_length=4000)
    answers: list[str] = Field(default_factory=list, max_length=6)

    @field_validator("answers")
    @classmethod
    def validate_answers(cls, answers):
        cleaned = [answer.strip() for answer in answers]
        if any(not 12 <= len(answer) <= 4000 for answer in cleaned):
            raise ValueError("Each response must have 12 to 4,000 characters.")
        return cleaned


class Decision(Change):
    approved: bool
    reason: str = Field(min_length=2, max_length=500)


class ScheduleInput(Change):
    scheduled_at: datetime
    details: str = Field(min_length=2, max_length=500)


class TaskInput(Change):
    task: str = Field(max_length=40)


class ReadinessInput(Change):
    responses: list[int] = Field(min_length=len(READINESS_QUESTIONS), max_length=len(READINESS_QUESTIONS))


class SupportInput(BaseModel):
    question: str = Field(min_length=2, max_length=300)


class LearningApproval(BaseModel):
    approved: Literal[True]
    resume_updated_at: str = Field(min_length=1, max_length=60)
    subject: str = Field(min_length=3, max_length=180)
    message: str = Field(min_length=10, max_length=4000)

    @field_validator("subject", "message", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class LearningRequest(Base):
    __tablename__ = "learning_requests"
    employee = Column(String, primary_key=True)
    opportunity_id = Column(String, primary_key=True)
    requested_at = Column(String, nullable=False)


def now():
    return datetime.now(timezone.utc).isoformat()


def db():
    with Session(engine) as session:
        yield session


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**15, r=8, p=1,
                          maxmem=64 * 1024 * 1024, dklen=32).hex()


def cookie_hash(request):
    token = request.cookies.get(COOKIE_NAME)
    return hashlib.sha256(token.encode()).hexdigest() if token else None


def require_browser_header(request: Request):
    if request.headers.get("X-Transition-Request") != "1":
        raise HTTPException(403, "This request is missing its required header.")


def actor(request: Request, session=Depends(db)):
    token_hash = cookie_hash(request)
    login = session.get(LoginSession, token_hash) if token_hash else None
    if login is None or login.expires_at <= int(time.time()) or login.username not in ACCOUNT_ROLES:
        raise HTTPException(401, "Sign in to continue.")
    credential = session.get(Credential, login.username)
    expected = request.headers.get("X-Expected-Account")
    if credential is None or credential.salt != login.credential_salt or expected not in (None, login.username):
        raise HTTPException(401, "Sign in to continue.")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_browser_header(request)
    return login.username


def has_access(user, role_or_side):
    return role_or_side == ACCOUNT_ROLES[user] or role_or_side == ENGAGEMENT_SIDES.get(user)


def allow(user, role_or_side):
    if not has_access(user, role_or_side):
        raise HTTPException(403, "This action is unavailable to your account.")


def account_profile(session, user):
    goal = session.get(Aspiration, user)
    role = ACCOUNT_ROLES[user]
    return {"id": user, "name": ACCOUNT_NAMES[user], "role": role,
            "engagement_side": ENGAGEMENT_SIDES.get(user),
            "employee": role == EMPLOYEE, "goal": goal.goal if goal else ""}


def lookup(session, model, key):
    row = session.get(model, key)
    if row is None:
        raise HTTPException(404, "Record not found.")
    return row


def accessible(session, key, user):
    row = lookup(session, Application, key)
    if not can_view(row, user):
        raise HTTPException(403, "This application is outside your review scope.")
    return row


def can_view(row, user):
    if user == row.employee or has_access(user, RECEIVING):
        return True
    states = {entry["state"] for entry in row.record["history"]}
    return ((has_access(user, TRANSITION_PARTNER) and "sme_review" in states)
            or (has_access(user, RELEASING) and "release_review" in states))


def permissions(row, user):
    state = row.record["state"]
    owner, *actions = ACTIONS.get(state, ("",))
    if not has_access(user, owner) or (owner == EMPLOYEE and user != row.employee):
        return []
    if state in {"fitment", "client_interview"} and state not in row.record.get("interviews", {}):
        return ["schedule_interview"]
    return actions


def require(row, user, revision, action):
    if row.revision != revision:
        raise HTTPException(409, "This record changed. Refresh and try again.")
    if action not in permissions(row, user):
        raise HTTPException(403, "This action is unavailable at this stage.")


def event(row, user, state, reason, **updates):
    history = row.record["history"] + [{"by": ACCOUNT_NAMES.get(user, user), "state": state, "reason": reason, "at": now()}]
    row.record = {**row.record, **updates, "state": state, "history": history}


def commit(session):
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm.exc import StaleDataError

    try:
        session.commit()
    except (IntegrityError, StaleDataError):
        session.rollback()
        raise HTTPException(409, "This record changed. Refresh and try again.") from None


def matching(opportunity, employee):
    evidence = {skill.casefold(): level for skill, level in PROFILES[employee]["skills"].items()}
    breakdown = [
        {"skill": skill, "needed": needed, "level": evidence.get(skill.casefold()),
         "source": f"DEMO-{employee.upper()}-{skill.upper()}" if skill.casefold() in evidence else None}
        for skill, needed in opportunity.details["criteria"].items()
    ]
    known = [item for item in breakdown if item["level"] is not None]
    score = round(100 * sum(min(1, item["level"] / item["needed"]) for item in known) / len(breakdown)) if known else None
    confidence = "High" if len(known) == len(breakdown) else ("Partial" if known else "Missing")
    return {"employee": employee, "name": ACCOUNT_NAMES[employee], "role": PROFILES[employee]["role"],
            "score": score, "confidence": confidence, "evidence": breakdown, "policy": POLICY_VERSION}


def serialize(row, user):
    record = dict(row.record)
    if record["state"] in {"interested", "drafting", "planning", "declined"}:
        record.pop("interview_questions", None)
    return {**record, "id": row.id, "opportunity_id": row.opportunity_id, "employee": row.employee,
            "name": ACCOUNT_NAMES[row.employee], "revision": row.revision,
            "allowed_actions": permissions(row, user)}


def job_id(row, kind, key):
    return hashlib.sha256(f"{row.id}:{kind}:{key}".encode()).hexdigest()[:32]


def enqueue(session, row, kind, key, details):
    job = Job(id=job_id(row, kind, key), application_id=row.id, kind=kind, status="queued", details=details, available=0)
    session.add(job)
    return job


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/auth/login", dependencies=[Depends(require_browser_header)])
def login(payload: LoginInput, request: Request, response: Response, session=Depends(db)):
    username = payload.username.strip().casefold()
    credential = session.get(Credential, username) if username in ACCOUNT_ROLES else None
    candidate = password_hash(payload.password, credential.salt if credential else "0" * 32)
    if not hmac.compare_digest(candidate, credential.password_hash if credential else "0" * 64) or credential is None:
        raise HTTPException(401, "Invalid username or password.")

    profile = account_profile(session, username)
    token = secrets.token_urlsafe(32)
    issued = int(time.time())
    session.execute(delete(LoginSession).where(
        (LoginSession.expires_at <= issued) | (LoginSession.token_hash == cookie_hash(request))))
    session.add(LoginSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), username=username,
                             credential_salt=credential.salt, expires_at=issued + SESSION_SECONDS))
    commit(session)
    secure = request.url.scheme == "https" or os.getenv("TRANSITION_SECURE_COOKIE") == "1"
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, path="/api",
                        httponly=True, secure=secure, samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return profile


@app.post("/api/auth/logout", status_code=204, dependencies=[Depends(require_browser_header)])
def logout(request: Request, response: Response, session=Depends(db)):
    token_hash = cookie_hash(request)
    if token_hash:
        session.execute(delete(LoginSession).where(LoginSession.token_hash == token_hash))
        commit(session)
    response.delete_cookie(COOKIE_NAME, path="/api")


def published(item):
    return item.details.get("status", "published") == "published"


def opening(session, key, user):
    item = lookup(session, Opportunity, key)
    if not published(item) and not has_access(user, RECEIVING):
        raise HTTPException(404, "Opportunity not found.")
    return item


def opening_payload(item, user):
    details = {"status": "published", **item.details}
    if not has_access(user, RECEIVING):
        details.pop("interview_questions", None)
    return {"id": item.id, **details}


@app.get("/api/opportunities")
def opportunities(user=Depends(actor), session=Depends(db)):
    if has_access(user, LEARNING_TEAM):
        raise HTTPException(403, "The L&D dashboard is your workspace.")
    items = session.scalars(select(Opportunity).order_by(Opportunity.id))
    return [opening_payload(item, user) for item in items if published(item) or has_access(user, RECEIVING)]


@app.post("/api/opportunities", status_code=201)
def create_opportunity(payload: RoleInput, user=Depends(actor), session=Depends(db)):
    allow(user, RECEIVING)
    details = payload.model_dump(exclude={"publish"})
    details["criteria"] = payload.criteria or dict.fromkeys(jd_skills(payload.description), 3)
    if not details["criteria"]:
        raise HTTPException(422, "Enter skill levels or include recognized skills in the job description.")
    details.update(status="published" if payload.publish else "draft",
                   created_at=now(), published_at=now() if payload.publish else None)
    item = Opportunity(id=uuid4().hex, details=details)
    session.add(item)
    commit(session)
    return opening_payload(item, user)


@app.post("/api/opportunities/{key}/publish")
def publish_opening(key: str, user=Depends(actor), session=Depends(db)):
    allow(user, RECEIVING)
    item = opening(session, key, user)
    if not published(item):
        item.details = {**item.details, "status": "published", "published_at": now()}
        commit(session)
    return opening_payload(item, user)


def employee_resume_evidence(session, user):
    resume = session.get(EmployeeResume, user)
    if resume is None:
        return None, ""
    stored = session.get(ResumeMatchText, user)
    if stored is not None and stored.resume_updated_at == resume.updated_at:
        return resume, stored.text
    return resume, extract_resume_text(resume.content, resume.media_type)


@app.get("/api/opportunities/recommendations")
def recommendations(response: Response, user=Depends(actor), session=Depends(db)):
    allow(user, EMPLOYEE)
    response.headers["Cache-Control"] = "no-store"
    resume, text = employee_resume_evidence(session, user)
    results = []
    for item in session.scalars(select(Opportunity)):
        if not published(item):
            continue
        match = compare_resume(item.details, text)
        results.append({"id": item.id, "title": item.details["title"], "project": item.details["project"],
                        "score": match["score"], "matched_count": match["matched_count"],
                        "requirements_count": len(match["requirements"]),
                        "gaps": [gap["skill"] for gap in match["gaps"]]})
    results.sort(key=lambda entry: (-(entry["score"] if entry["score"] is not None else -1),
                                    -entry["matched_count"], entry["title"].casefold(), entry["id"]))
    return {"resume_status": "ready" if text else "unreadable" if resume else "missing",
            "opportunities": results}


def find_ticket(session, user, opportunity_id):
    return session.scalar(select(LearningTicket).where(
        LearningTicket.employee == user, LearningTicket.opportunity_id == opportunity_id))


def ticket_summary(ticket):
    return {"id": ticket.id, "created_at": ticket.created_at, "acknowledged_at": ticket.acknowledged_at}


def ticket_details(ticket, item):
    return {**ticket_summary(ticket), "employee": ACCOUNT_NAMES[ticket.employee], "skills": ticket.skills,
            "title": item.details["title"], "project": item.details["project"],
            "subject": ticket.subject, "message": ticket.message}


@app.get("/api/opportunities/{key}/my-match")
def my_match(key: str, response: Response, user=Depends(actor), session=Depends(db)):
    allow(user, EMPLOYEE)
    item = opening(session, key, user)
    resume, text = employee_resume_evidence(session, user)
    ticket = find_ticket(session, user, key)
    response.headers["Cache-Control"] = "no-store"
    return {**compare_resume(item.details, text),
            "resume_status": "ready" if text else "unreadable" if resume else "missing",
            "ticket": ticket_summary(ticket) if ticket else None}


def ticket_gaps(item, resume_text):
    if not resume_text:
        raise HTTPException(422, "Upload a resume with selectable text before requesting learning support.")
    gaps = compare_resume(item.details, resume_text)["gaps"]
    if not gaps:
        raise HTTPException(422, "There are no resume skill gaps for this opportunity.")
    return gaps


@app.get("/api/opportunities/{key}/learning-request-draft")
def learning_request_draft(key: str, response: Response, user=Depends(actor), session=Depends(db)):
    allow(user, EMPLOYEE)
    item = opening(session, key, user)
    if find_ticket(session, user, key):
        raise HTTPException(409, "A learning request has already been submitted for this opportunity.")
    resume, text = employee_resume_evidence(session, user)
    gaps = ticket_gaps(item, text)
    skills = ", ".join(gap["skill"] for gap in gaps)
    title = item.details["title"]
    project = item.details["project"]
    message = (f"Hi L&D team,\n\nI am preparing for the {title} opportunity on {project}. "
               f"I would like learning support for {skills}.\n\nSuggested learning plan:\n")
    for gap in gaps:
        steps = "\n".join(f"- {step}" for step in gap["steps"])
        section = f'\n{gap["skill"]}\n{steps}\n'
        if len(message) + len(section) > 3800:
            break
        message += section
    message += "\nCould you recommend training, a practice environment, and a mentor where available? Thank you."
    response.headers["Cache-Control"] = "no-store"
    return {"subject": f"Learning support for {title}"[:180], "message": message,
            "resume_updated_at": resume.updated_at}


@app.post("/api/opportunities/{key}/learning-requests", status_code=201)
def request_learning(key: str, payload: LearningApproval, user=Depends(actor), session=Depends(db)):
    allow(user, EMPLOYEE)
    item = opening(session, key, user)
    existing = find_ticket(session, user, key)
    if existing:
        return ticket_summary(existing)
    resume, text = employee_resume_evidence(session, user)
    if resume is None or resume.updated_at != payload.resume_updated_at:
        raise HTTPException(409, "Your resume changed. Generate a new request draft.")
    skills = [gap["skill"] for gap in ticket_gaps(item, text)]
    ticket = LearningTicket(id=uuid4().hex, employee=user, opportunity_id=key, subject=payload.subject,
                            message=payload.message, skills=skills, created_at=now())
    session.add(ticket)
    if session.get(LearningRequest, (user, key)) is None:
        session.add(LearningRequest(employee=user, opportunity_id=key, requested_at=ticket.created_at))
    commit(session)
    return ticket_summary(ticket)


@app.get("/api/learning-tickets")
def learning_tickets(response: Response, user=Depends(actor), session=Depends(db)):
    allow(user, LEARNING_TEAM)
    response.headers["Cache-Control"] = "no-store"
    query = (select(LearningTicket, Opportunity).join(Opportunity, Opportunity.id == LearningTicket.opportunity_id)
             .order_by(LearningTicket.acknowledged_at.is_not(None), LearningTicket.created_at.desc()))
    tickets = [ticket_details(ticket, item) for ticket, item in session.execute(query)]
    return {"new_count": sum(ticket["acknowledged_at"] is None for ticket in tickets), "tickets": tickets}


@app.post("/api/learning-tickets/{key}/acknowledge")
def acknowledge_ticket(key: str, user=Depends(actor), session=Depends(db)):
    allow(user, LEARNING_TEAM)
    ticket = lookup(session, LearningTicket, key)
    if ticket.acknowledged_at is None:
        ticket.acknowledged_at = now()
        commit(session)
    return ticket_summary(ticket)


@app.get("/api/opportunities/{key}/matches")
def matches(key: str, user=Depends(actor), session=Depends(db)):
    allow(user, RECEIVING)
    item = lookup(session, Opportunity, key)
    return sorted((matching(item, employee) for employee in PROFILES),
                  key=lambda match: -(match["score"] if match["score"] is not None else -1))


@app.get("/api/me")
def me(response: Response, user=Depends(actor), session=Depends(db)):
    response.headers["Cache-Control"] = "no-store"
    return account_profile(session, user)


@app.get("/api/me/career-history")
def career_history(response: Response, user=Depends(actor), session=Depends(db)):
    allow(user, EMPLOYEE)
    response.headers["Cache-Control"] = "no-store"
    career = CAREER_HISTORY[user]
    projects = list(career["projects"])
    query = (select(Application, Opportunity).join(Opportunity, Opportunity.id == Application.opportunity_id)
             .where(Application.employee == user))
    for application, opportunity in session.execute(query):
        record = application.record
        if record["state"] not in {"activated", "allocated"}:
            continue
        details = opportunity.details
        projects.append({
            "id": application.id, "transition_id": application.id, "name": details["project"],
            "role": details["title"], "started_on": record["allocation"]["at"][:10],
            "summary": details.get("growth"), "role_skills": list(details.get("criteria", {})),
        })
    return {
        "name": ACCOUNT_NAMES[user], "role": PROFILES[user]["role"],
        "joined_on": career["joined_on"], "entry_role": career["entry_role"],
        "role_changes": career["role_changes"],
        "projects": sorted(projects, key=lambda project: project["started_on"], reverse=True),
    }


def resume_status(user, resume, today):
    baseline = date.fromisoformat(resume.updated_at[:10] if resume else CAREER_HISTORY[user]["joined_on"])
    due = baseline + timedelta(days=RESUME_INTERVAL_DAYS)
    return {
        "filename": resume.filename if resume else None,
        "updated_at": resume.updated_at if resume else None,
        "due_on": due.isoformat(),
        "days_until_due": (due - today).days,
        "interval_days": RESUME_INTERVAL_DAYS,
        "max_bytes": RESUME_MAX_BYTES,
    }


async def resume_file(request: Request, filename: str = Query(min_length=1, max_length=180), user=Depends(actor)):
    allow(user, EMPLOYEE)
    filename = filename.strip()
    extension = Path(filename).suffix.lower()
    if extension not in RESUME_TYPES or any(ch in "/\\" or not ch.isprintable() for ch in filename):
        raise HTTPException(422, "Choose a PDF or DOCX resume with a valid file name.")

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > RESUME_MAX_BYTES:
            raise HTTPException(413, "Resume files must be 5 MB or smaller.")
        body.extend(chunk)
    if extension == ".pdf":
        valid = body.startswith(b"%PDF-")
    else:
        try:
            with ZipFile(BytesIO(body)) as document:
                valid = {"[Content_Types].xml", "word/document.xml"}.issubset(document.namelist())
        except BadZipFile:
            valid = False
    if not valid:
        raise HTTPException(422, "The file does not match its PDF or DOCX extension.")
    return filename, RESUME_TYPES[extension], bytes(body)


@app.get("/api/me/resume")
def get_resume(response: Response, user=Depends(actor), session=Depends(db)):
    allow(user, EMPLOYEE)
    response.headers["Cache-Control"] = "no-store"
    return resume_status(user, session.get(EmployeeResume, user), datetime.now(timezone.utc).date())


@app.put("/api/me/resume")
def update_resume(response: Response, file=Depends(resume_file), user=Depends(actor), session=Depends(db)):
    filename, media_type, content = file
    updated = datetime.now(timezone.utc)
    resume = session.merge(EmployeeResume(employee=user, filename=filename, media_type=media_type,
                                          updated_at=updated.isoformat(), content=content))
    session.merge(ResumeMatchText(employee=user, resume_updated_at=resume.updated_at,
                                  text=extract_resume_text(content, media_type)))
    status = resume_status(user, resume, updated.date())
    commit(session)
    response.headers["Cache-Control"] = "no-store"
    return status


@app.get("/api/me/resume/download")
def download_resume(user=Depends(actor), session=Depends(db)):
    allow(user, EMPLOYEE)
    resume = lookup(session, EmployeeResume, user)
    return Response(resume.content, media_type=resume.media_type, headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(resume.filename, safe=""),
    })


@app.patch("/api/me/aspirations")
def save_aspiration(payload: GoalInput, user=Depends(actor), session=Depends(db)):
    allow(user, EMPLOYEE)
    session.merge(Aspiration(employee=user, goal=payload.goal))
    commit(session)
    return {"goal": payload.goal}


@app.post("/api/opportunities/{key}/applications")
def interest(key: str, payload: Interest, user=Depends(actor), session=Depends(db)):
    allow(user, EMPLOYEE)
    opportunity = opening(session, key, user)
    goal = session.get(Aspiration, user)
    if payload.interested and goal is None:
        raise HTTPException(422, "Save a career goal before expressing interest.")
    identifier = f"{key}:{user}"
    row = session.get(Application, identifier)
    state = "interested" if payload.interested else "declined"
    if row:
        if row.record["state"] == state:
            return serialize(row, user)
        if row.record["state"] != "declined":
            raise HTTPException(409, "This opportunity already has an active application.")
    else:
        row = Application(id=identifier, employee=user, opportunity_id=key,
                          record={"history": [], "readiness": "not_assessed", "attempts": []})
        session.add(row)
    event(row, user, state, "Employee applied for the opportunity." if payload.interested else "Employee declined the opportunity.",
          goal=goal.goal if goal else "", match=matching(opportunity, user),
          preparation_due=(datetime.now(timezone.utc) + timedelta(hours=48)).isoformat() if payload.interested else None)
    commit(session)
    return serialize(row, user)


@app.get("/api/applications")
def applications(user=Depends(actor), session=Depends(db)):
    query = select(Application, Opportunity).outerjoin(Opportunity, Opportunity.id == Application.opportunity_id)
    if ACCOUNT_ROLES[user] == EMPLOYEE:
        query = query.where(Application.employee == user)
    return [
        {**serialize(row, user), **({"project": opportunity.details["project"],
                                   "opportunity_title": opportunity.details["title"]} if opportunity else {})}
        for row, opportunity in session.execute(query.order_by(Application.id)) if can_view(row, user)
    ]


@app.post("/api/applications/{key}/plan-drafts")
def draft(key: str, payload: Change, user=Depends(actor), session=Depends(db)):
    row = accessible(session, key, user)
    require(row, user, payload.revision, "draft_plan")
    opportunity = lookup(session, Opportunity, row.opportunity_id)
    job = enqueue(session, row, "plan", str(row.revision), {
        "growth": opportunity.details["growth"], "role_title": opportunity.details["title"],
        "project": opportunity.details["project"], "topics": list(opportunity.details["criteria"]),
        "questions": opportunity.details.get("interview_questions") or [SCENARIO],
        "learning": learning_paths(row.record["match"]["evidence"]),
    })
    event(row, user, "drafting", "Preparation draft queued.", job_id=job.id)
    commit(session)
    return serialize(row, user)


@app.patch("/api/applications/{key}/plan")
def confirm_plan(key: str, payload: PlanInput, user=Depends(actor), session=Depends(db)):
    row = accessible(session, key, user)
    require(row, user, payload.revision, "confirm_plan")
    event(row, user, "practice", "Employee confirmed the preparation plan.", alignment=payload.alignment)
    commit(session)
    return serialize(row, user)


@app.post("/api/applications/{key}/attempts")
def attempt(key: str, payload: AttemptInput, user=Depends(actor), session=Depends(db)):
    row = accessible(session, key, user)
    require(row, user, payload.revision, "submit_attempt")
    questions = row.record.get("interview_questions", [SCENARIO])
    answers = payload.answers or ([payload.answer.strip()] if payload.answer is not None else [])
    if len(questions) != len(answers) or any(len(answer) < 12 for answer in answers):
        raise HTTPException(422, "Provide a response of at least 12 characters for each question.")
    job = enqueue(session, row, "feedback", str(row.revision), {"answers": answers, "questions": questions})
    event(row, user, "assessing", "Interview responses submitted.", job_id=job.id)
    commit(session)
    return serialize(row, user)


@app.get("/api/jobs/{key}")
def job_status(key: str, user=Depends(actor), session=Depends(db)):
    job = lookup(session, Job, key)
    accessible(session, job.application_id, user)
    return {"id": job.id, "status": job.status}


@app.post("/api/applications/{key}/decisions")
def decide(key: str, payload: Decision, user=Depends(actor), session=Depends(db)):
    row = accessible(session, key, user)
    require(row, user, payload.revision, "decide")
    state = row.record["state"]
    approved, held = STAGES[state]
    updates = {}
    if state == "sme_review":
        updates["readiness"] = "verified" if payload.approved else "needs_practice"
    if state == "fitment" and payload.approved:
        opportunity = lookup(session, Opportunity, row.opportunity_id)
        if opportunity.details.get("client_interview_required", False):
            approved = "client_interview"
    if state in {"fitment", "client_interview"}:
        interviews = row.record["interviews"]
        updates["interviews"] = {**interviews, state: {
            **interviews[state], "passed": payload.approved, "reason": payload.reason,
        }}
    if state == "release_review" and payload.approved:
        updates["selected_at"] = now()
    if state == "activation_review":
        if payload.approved:
            updates["allocation"] = {"at": now(), "onboarding": list(ONBOARDING_CHECKS.values())}
        else:
            updates["readiness_return_reason"] = payload.reason
    event(row, user, approved if payload.approved else held, payload.reason, **updates)
    commit(session)
    return serialize(row, user)


@app.post("/api/applications/{key}/interview-schedule")
def schedule_interview(key: str, payload: ScheduleInput, user=Depends(actor), session=Depends(db)):
    row = accessible(session, key, user)
    require(row, user, payload.revision, "schedule_interview")
    if payload.scheduled_at.tzinfo is None or payload.scheduled_at <= datetime.now(timezone.utc):
        raise HTTPException(422, "Choose a future interview date and time.")
    state = row.record["state"]
    interviews = {**row.record.get("interviews", {}), state: {
        "at": payload.scheduled_at.isoformat(), "details": payload.details,
    }}
    event(row, user, state, "Interview scheduled.", interviews=interviews)
    commit(session)
    return serialize(row, user)


@app.post("/api/applications/{key}/resume")
def resume(key: str, payload: Change, user=Depends(actor), session=Depends(db)):
    row = accessible(session, key, user)
    require(row, user, payload.revision, "resume")
    event(row, user, row.record["state"].replace("_hold", "_review"), "Reviewer reopened the decision.")
    commit(session)
    return serialize(row, user)


@app.post("/api/applications/{key}/allocation")
def provision_access(key: str, payload: Change, user=Depends(actor), session=Depends(db)):
    allow(user, RECEIVING)
    row = accessible(session, key, user)
    if row.record.get("onboarding") or row.record["state"] == "allocated":
        return serialize(row, user)
    require(row, user, payload.revision, "provision_access")
    event(row, user, "onboarding", "Engagement Manager confirmed project access and opened onboarding.",
          onboarding={"access_at": now(), "completed": [], "checks": ONBOARDING_CHECKS, "sources": KNOWLEDGE})
    commit(session)
    return serialize(row, user)


@app.post("/api/applications/{key}/onboarding-tasks")
def complete_task(key: str, payload: TaskInput, user=Depends(actor), session=Depends(db)):
    row = accessible(session, key, user)
    require(row, user, payload.revision, "complete_task")
    onboarding = row.record["onboarding"]
    if payload.task not in onboarding["checks"]:
        raise HTTPException(422, "Choose an onboarding task from this transition.")
    if payload.task in onboarding["completed"]:
        return serialize(row, user)
    completed = [*onboarding["completed"], payload.task]
    state = "readiness_assessment" if len(completed) == len(onboarding["checks"]) else "onboarding"
    event(row, user, state, f'Completed: {onboarding["checks"][payload.task]}.',
          onboarding={**onboarding, "completed": completed})
    commit(session)
    return serialize(row, user)


@app.get("/api/readiness-check")
def readiness_check(user=Depends(actor)):
    allow(user, EMPLOYEE)
    return {"threshold": TRS_THRESHOLD, "questions": [
        {key: question[key] for key in ("prompt", "options")} for question in READINESS_QUESTIONS
    ]}


@app.post("/api/applications/{key}/readiness-assessments")
def assess_readiness(key: str, payload: ReadinessInput, user=Depends(actor), session=Depends(db)):
    row = accessible(session, key, user)
    require(row, user, payload.revision, "assess_readiness")
    if any(not 0 <= answer < len(question["options"])
           for answer, question in zip(payload.responses, READINESS_QUESTIONS, strict=True)):
        raise HTTPException(422, "Select a valid response to each readiness question.")
    score, results = evaluate_readiness(payload.responses)
    state = "activation_review" if score >= TRS_THRESHOLD else "readiness_assessment"
    event(row, user, state, f"Transition Readiness Score recorded at {score}%.",
          trs={"score": score, "threshold": TRS_THRESHOLD, "results": results, "at": now()},
          readiness_return_reason="")
    commit(session)
    return serialize(row, user)


@app.get("/api/support")
def support(user=Depends(actor), session=Depends(db)):
    records = applications(user, session)
    counts = {}
    updates = []
    for record in records:
        counts[record["state"]] = counts.get(record["state"], 0) + 1
        latest = record["history"][-1]
        updates.append({"id": record["id"], "name": record["name"], **latest})
    openings = []
    if has_access(user, EMPLOYEE):
        openings = [
            {"id": item.id, "title": item.details["title"], "project": item.details["project"],
             "at": item.details.get("published_at")}
            for item in session.scalars(select(Opportunity)) if published(item)
        ]
    learning_requests = []
    if has_access(user, RECEIVING):
        query = (select(LearningRequest, Opportunity)
                 .join(Opportunity, Opportunity.id == LearningRequest.opportunity_id)
                 .order_by(LearningRequest.requested_at.desc()).limit(20))
        learning_requests = [
            {"id": f"{request.opportunity_id}:{request.employee}", "name": ACCOUNT_NAMES[request.employee],
             "opportunity_id": request.opportunity_id, "title": opportunity.details["title"],
             "project": opportunity.details["project"], "at": request.requested_at}
            for request, opportunity in session.execute(query)
        ]
    return {"knowledge": KNOWLEDGE, "counts": counts, "learning_requests": learning_requests,
            "updates": sorted(updates, key=lambda item: item["at"], reverse=True)[:10],
            "openings": sorted(openings, key=lambda item: item["at"] or "", reverse=True)[:10]}


@app.post("/api/support/ask")
def ask_support(payload: SupportInput, user=Depends(actor)):
    terms = set(re.findall(r"[a-z]{3,}", payload.question.casefold()))
    topics = [
        ({"rollback", "recovery", "metrics", "error", "latency"}, "KT-01"),
        ({"client", "customer", "communication", "stakeholder", "impact"}, "KT-02"),
        ({"training", "learning", "courses", "mentoring", "certification"}, "KT-03"),
        ({"onboarding", "readiness", "activation", "access", "trs"}, "KT-04"),
    ]
    matched = {source for keywords, source in topics if terms & keywords}
    sources = [source for source in KNOWLEDGE if source["id"] in matched]
    return {"answer": " ".join(source["text"] for source in sources) or
            "Ask about release recovery, client communication, learning support, or onboarding readiness.",
            "sources": [{"id": source["id"], "title": source["title"]} for source in sources]}


def process_job(session, job):
    row = lookup(session, Application, job.application_id)
    if job.kind == "plan":
        tasks = [{"title": source["title"], "owner": ACCOUNT_NAMES[row.employee], "source": source["id"]} for source in KNOWLEDGE]
        event(row, "Preparation coach", "planning", "Preparation plan is ready.",
              plan=tasks, scenario=SCENARIO, sources=KNOWLEDGE,
              preparation={key: job.details[key] for key in ("growth", "role_title", "project", "topics", "learning") if key in job.details},
              interview_questions=job.details.get("questions", [SCENARIO]))
    else:
        answers = job.details.get("answers") or [job.details["answer"]]
        questions = job.details.get("questions", [SCENARIO])
        feedback, score = evaluate_interview(questions, answers)
        attempt_record = {"answer": "\n\n".join(answers),
                          "responses": [{"question": q, "answer": a} for q, a in zip(questions, answers, strict=True)],
                          "feedback": feedback, "score": score, "at": now(), "rubric": "structured-v2"}
        event(row, "Assessment coach", "sme_review", "Interview feedback ready for Transition Partner review.",
              readiness="awaiting_review", failed_answer="", failed_answers=[],
              attempts=[*row.record["attempts"], attempt_record])
    job.status = "succeeded"


def work():
    while True:
        with Session(engine) as session:
            query = select(Job).where(Job.status == "queued", Job.available <= int(time.time())).limit(1)
            query = query.with_for_update(skip_locked=True)
            job = session.scalar(query)
            if job:
                try:
                    with session.begin_nested():
                        process_job(session, job)
                except Exception:
                    logger.exception("Failed to process job %s", job.id)
                    attempts = job.details.get("retries", 0) + 1
                    job.details = {**job.details, "retries": attempts}
                    job.available = int(time.time()) + 5
                    if attempts >= 3:
                        job.status = "failed"
                        row = lookup(session, Application, job.application_id)
                        event(row, "Workflow", "interested" if job.kind == "plan" else "practice",
                              "Processing failed. Try again.", failed_answer=job.details.get("answer", ""),
                              failed_answers=job.details.get("answers", []))
                commit(session)
                continue
        time.sleep(0.6)


def initialize():
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        if not session.get(Opportunity, "atlas"):
            session.add(Opportunity(id="atlas", details={
                "title": "Backend Engineer", "project": "Atlas Payments",
                "growth": "Own API reliability and pair with the platform lead. Architecture ownership needs discussion.",
                "needed_by": "Next sprint", "criteria": {"Python": 5, "APIs": 5, "Reliability": 4},
            }))
        if not session.get(Aspiration, "vikram"):
            session.add(Aspiration(employee="vikram", goal="Grow into architecture ownership through design reviews."))
        commit(session)


def set_password(username):
    from getpass import getpass

    password = getpass("New password: ")
    if not 12 <= len(password) <= 128:
        raise SystemExit("Use a password between 12 and 128 characters.")
    if password != getpass("Confirm password: "):
        raise SystemExit("Passwords did not match.")

    Base.metadata.create_all(engine, tables=[Credential.__table__, LoginSession.__table__])
    salt = secrets.token_hex(16)
    with Session(engine) as session:
        session.merge(Credential(username=username, salt=salt, password_hash=password_hash(password, salt)))
        session.execute(delete(LoginSession).where(LoginSession.username == username))
        commit(session)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    commands.add_parser("worker")
    password_command = commands.add_parser("set-password")
    password_command.add_argument("username", choices=ACCOUNT_ROLES)
    options = parser.parse_args()
    if options.command == "init":
        initialize()
    elif options.command == "set-password":
        set_password(options.username)
    else:
        work()
