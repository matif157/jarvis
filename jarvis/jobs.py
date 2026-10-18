"""Job discovery and application workflow for Jarvis.

Local-first, consent-based job search and application tracking that builds on
existing phases:
  - discovery reuses Phase 6 search/research (``jarvis.web_search``)
  - matching reuses Phase 8 resume/career data (``jarvis.career``)
  - follow-up email reuses Phase 9 email (``jarvis.email``)

Everything works offline: discovery has a deterministic in-process source and
cover letters are template-based. Optional enhancements (LLM writing, real web
search) are used only when explicitly configured.
"""

from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config import get_data_dir
from .logging import get_logger
from .tools import Tool, ToolResult

logger = get_logger(__name__)

# Job data directory (JSON, consistent with Phases 7-9)
JOBS_DIR = Path(get_data_dir()) / "jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)
LISTINGS_FILE = JOBS_DIR / "listings.json"
APPLICATIONS_FILE = JOBS_DIR / "applications.json"

# Application lifecycle
APPLICATION_STATUSES = (
    "saved",
    "applied",
    "interviewing",
    "offer",
    "rejected",
    "withdrawn",
)

# Allowed status transitions (state machine)
ALLOWED_TRANSITIONS: Dict[str, set] = {
    "saved": {"applied", "withdrawn"},
    "applied": {"interviewing", "offer", "rejected", "withdrawn"},
    "interviewing": {"offer", "rejected", "withdrawn"},
    "offer": {"withdrawn", "rejected"},
    "rejected": set(),
    "withdrawn": set(),
}

MAX_LISTINGS = 200


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now() -> str:
    return datetime.utcnow().isoformat()


@dataclass
class JobListing:
    """A discovered job posting."""

    id: str
    title: str
    company: str
    location: str = ""
    remote: bool = False
    url: str = ""
    source: str = ""
    salary: str = ""
    posted_date: str = ""
    description: str = ""
    tags: List[str] = field(default_factory=list)
    match_score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class JobSearchQuery:
    """A job search request."""

    keywords: str = ""
    role: str = ""
    location: str = ""
    remote: bool = False
    salary_min: Optional[int] = None
    max_results: int = 20

    def describe(self) -> str:
        parts = [p for p in (self.role or self.keywords, self.location) if p]
        if self.remote:
            parts.append("remote")
        return " ".join(parts) if parts else "jobs"


@dataclass
class JobApplication:
    """A tracked job application."""

    id: str
    job_id: str = ""
    title: str = ""
    company: str = ""
    status: str = "saved"
    resume_id: str = ""
    cover_letter: str = ""
    notes: List[Dict[str, Any]] = field(default_factory=list)
    contacts: List[str] = field(default_factory=list)
    next_action: str = ""
    next_action_date: str = ""
    email_refs: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


# ---------------------------------------------------------------------------
# Discovery sources
# ---------------------------------------------------------------------------
class JobSource(ABC):
    """Abstract base class for job sources."""

    def __init__(self, max_results: int = 20):
        self.max_results = max_results

    @property
    @abstractmethod
    def name(self) -> str:
        """Source identifier."""

    @abstractmethod
    def search(self, query: JobSearchQuery) -> List[JobListing]:
        """Return job listings matching the query."""


class MockJobSource(JobSource):
    """Deterministic offline job source used for testing."""

    _TEMPLATES = [
        ("Senior Software Engineer", "Acme Corp", "San Francisco, CA"),
        ("Backend Engineer (Python)", "Globex", "Remote"),
        ("Full Stack Developer", "Initech", "Austin, TX"),
        ("Data Engineer", "Umbrella Health", "Remote"),
        ("Machine Learning Engineer", "Hooli", "New York, NY"),
    ]

    @property
    def name(self) -> str:
        return "mock"

    def search(self, query: JobSearchQuery) -> List[JobListing]:
        role = query.role or query.keywords or "Software Engineer"
        location = query.location or "Remote"
        limit = min(query.max_results or self.max_results, len(self._TEMPLATES))
        listings: List[JobListing] = []
        for i, (title, company, loc) in enumerate(self._TEMPLATES[:limit]):
            remote = query.remote or "remote" in loc.lower()
            listings.append(
                JobListing(
                    id=_new_id("job"),
                    title=f"{role} - {title}" if query.role else title,
                    company=company,
                    location=location if query.remote else loc,
                    remote=remote,
                    url=f"https://jobs.example.com/{company.lower().replace(' ', '-')}/{i}",
                    source="mock",
                    salary="$120,000 - $180,000",
                    posted_date="2026-01-15",
                    description=(
                        f"{company} is hiring a {title}. "
                        f"Location: {loc}. Requires strong engineering skills."
                    ),
                    tags=["python", "engineering", "full-time"],
                    metadata={"is_mock": True},
                )
            )
        return listings


class WebSearchJobSource(JobSource):
    """Job source backed by Phase 6 web search.

    Converts search results into normalized job listings. Uses whatever search
    provider the supplied ``SearchManager`` is configured with (mock or real).
    """

    def __init__(self, search_manager=None, max_results: int = 20):
        super().__init__(max_results=max_results)
        if search_manager is None:
            from .web_search import SearchManager

            search_manager = SearchManager()
        self.search_manager = search_manager

    @property
    def name(self) -> str:
        return "web_search"

    def search(self, query: JobSearchQuery) -> List[JobListing]:
        search_query = f"{query.describe()} job opening hiring"
        response = self.search_manager.search(search_query, max_results=query.max_results)
        listings: List[JobListing] = []
        for result in getattr(response, "results", []) or []:
            listings.append(self._result_to_listing(result, query))
        return listings

    def _result_to_listing(self, result, query: JobSearchQuery) -> JobListing:
        title = getattr(result, "title", "") or "Job opening"
        snippet = getattr(result, "snippet", "") or ""
        url = getattr(result, "url", "") or ""
        metadata = getattr(result, "metadata", {}) or {}
        company = self._guess_company(title)
        remote = "remote" in f"{title} {snippet}".lower() or query.remote
        return JobListing(
            id=_new_id("job"),
            title=title,
            company=company,
            location=query.location or ("Remote" if remote else ""),
            remote=remote,
            url=url,
            source="web_search",
            description=snippet,
            tags=self._guess_tags(f"{title} {snippet}"),
            metadata={"is_mock": metadata.get("is_mock", False)},
        )

    @staticmethod
    def _guess_company(title: str) -> str:
        for sep in (" at ", " - ", " | ", " @ "):
            if sep in title:
                return title.split(sep, 1)[1].strip()
        return ""

    @staticmethod
    def _guess_tags(text: str) -> List[str]:
        keywords = [
            "python", "javascript", "typescript", "java", "go", "rust", "react",
            "django", "flask", "aws", "docker", "kubernetes", "sql", "remote",
            "senior", "junior", "full-time", "contract", "machine learning",
            "data", "backend", "frontend", "devops",
        ]
        lowered = text.lower()
        return sorted({k for k in keywords if k in lowered})


class JobSearchManager:
    """Aggregate multiple job sources with graceful fallback."""

    def __init__(self, sources: Optional[List[JobSource]] = None, use_mock: bool = False):
        if sources is not None:
            self.sources = sources
        elif use_mock:
            self.sources = [MockJobSource()]
        else:
            self.sources = [WebSearchJobSource(), MockJobSource()]

    def search(self, query: JobSearchQuery) -> Tuple[List[JobListing], List[str]]:
        """Search all sources; return (listings, errors)."""
        listings: List[JobListing] = []
        errors: List[str] = []
        for source in self.sources:
            try:
                results = source.search(query)
                listings.extend(results or [])
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(f"Job source {source.name} failed: {exc}")
                errors.append(f"{source.name}: {exc}")
        return listings[: (query.max_results or MAX_LISTINGS)], errors


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
class JobMatcher:
    """Score a listing against the user's career profile and resumes."""

    def __init__(self, profile=None, skills: Optional[List[str]] = None, resumes=None):
        if skills is not None:
            self.skills = [s.lower() for s in skills]
        else:
            self.skills = self._load_skills(profile, resumes)
        self.target_roles = [
            r.lower() for r in getattr(profile, "target_roles", []) or []
        ]

    def _load_skills(self, profile, resumes) -> List[str]:
        skills: List[str] = []
        try:
            from .career import CareerProfileStore, ResumeStore

            if profile is None:
                profile = CareerProfileStore().load()
            skills.extend(getattr(profile, "skills", []) or [])

            if resumes is None:
                store = ResumeStore()
                for meta in store.list():
                    resume = store.load(meta.get("id"))
                    if resume:
                        skills.extend(resume.skills or [])
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug(f"Could not load career skills: {exc}")
        return sorted({s.lower() for s in skills if s})

    def score(self, listing: JobListing) -> Tuple[float, List[str]]:
        """Return (score 0-100, list of human-readable reasons)."""
        reasons: List[str] = []
        text = " ".join(
            [
                listing.title or "",
                listing.description or "",
                " ".join(listing.tags or []),
            ]
        ).lower()

        # Skill overlap (max 70)
        matched = [s for s in self.skills if s in text]
        if self.skills:
            skill_score = min(len(matched) / max(len(self.skills), 1), 1.0) * 70
        else:
            skill_score = 0.0
        if matched:
            reasons.append(f"Matched skills: {', '.join(sorted(set(matched))[:8])}")

        # Role match (max 20)
        role_score = 0.0
        for role in self.target_roles:
            if role and role in (listing.title or "").lower():
                role_score = 20.0
                reasons.append(f"Matches target role: {role}")
                break

        # Location / remote match (max 10)
        location_score = 0.0
        if listing.remote:
            location_score = 10.0
            reasons.append("Remote position")
        if not reasons:
            reasons.append("No strong overlap with your profile")

        total = round(min(skill_score + role_score + location_score, 100.0), 1)
        return total, reasons


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------
class JobStore:
    """Persist discovered/manual job listings as JSON."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else LISTINGS_FILE
        self._items: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._items = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning(f"Failed to load job listings: {exc}")
                self._items = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._items, indent=2), encoding="utf-8")

    def save(self, listing: JobListing) -> str:
        if not listing.id:
            listing.id = _new_id("job")
        self._items[listing.id] = asdict(listing)
        self._save()
        return listing.id

    def get(self, job_id: str) -> Optional[JobListing]:
        data = self._items.get(job_id)
        return JobListing(**data) if data else None

    def list(self) -> List[JobListing]:
        return [JobListing(**v) for v in self._items.values()]

    def delete(self, job_id: str) -> bool:
        if job_id in self._items:
            del self._items[job_id]
            self._save()
            return True
        return False


class ApplicationStore:
    """Persist and manage job applications as JSON."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else APPLICATIONS_FILE
        self._items: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._items = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning(f"Failed to load applications: {exc}")
                self._items = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._items, indent=2), encoding="utf-8")

    def add(self, application: JobApplication) -> str:
        if not application.id:
            application.id = _new_id("app")
        if application.status not in APPLICATION_STATUSES:
            application.status = "saved"
        application.updated_at = _now()
        self._items[application.id] = asdict(application)
        self._save()
        return application.id

    def get(self, app_id: str) -> Optional[JobApplication]:
        data = self._items.get(app_id)
        return JobApplication(**data) if data else None

    def list(self, status: Optional[str] = None) -> List[JobApplication]:
        apps = [JobApplication(**v) for v in self._items.values()]
        if status:
            apps = [a for a in apps if a.status == status]
        return sorted(apps, key=lambda a: a.updated_at, reverse=True)

    def update_status(self, app_id: str, new_status: str) -> Tuple[bool, str]:
        app = self.get(app_id)
        if not app:
            return False, "application not found"
        if new_status not in APPLICATION_STATUSES:
            return False, f"invalid status: {new_status}"
        if new_status == app.status:
            return True, "already in that status"
        allowed = ALLOWED_TRANSITIONS.get(app.status, set())
        if new_status not in allowed:
            return False, f"invalid transition: {app.status} -> {new_status}"
        data = self._items[app_id]
        data["status"] = new_status
        data["updated_at"] = _now()
        self._save()
        return True, "status updated"

    def add_note(self, app_id: str, note: str) -> bool:
        if app_id not in self._items:
            return False
        self._items[app_id].setdefault("notes", []).append(
            {"note": note, "timestamp": _now()}
        )
        self._items[app_id]["updated_at"] = _now()
        self._save()
        return True

    def delete(self, app_id: str) -> bool:
        if app_id in self._items:
            del self._items[app_id]
            self._save()
            return True
        return False

    def stats(self) -> Dict[str, int]:
        counts = {status: 0 for status in APPLICATION_STATUSES}
        for app in self._items.values():
            status = app.get("status", "saved")
            counts[status] = counts.get(status, 0) + 1
        counts["total"] = len(self._items)
        active = counts["saved"] + counts["applied"] + counts["interviewing"] + counts["offer"]
        counts["active"] = active
        return counts


# ---------------------------------------------------------------------------
# Preparation helpers
# ---------------------------------------------------------------------------
class CoverLetterGenerator:
    """Generate a cover letter from resume + career profile + listing.

    Offline-first: uses deterministic templates. An optional ``enhancer``
    callable may be supplied to rewrite/polish the text (e.g. via an LLM);
    when omitted, the template output is returned unchanged.
    """

    def __init__(self, enhancer: Optional[Callable[[str], str]] = None):
        self.enhancer = enhancer

    def generate(
        self,
        listing: JobListing,
        profile=None,
        resume=None,
    ) -> str:
        name = "Applicant"
        contact_bits: List[str] = []
        skills: List[str] = []

        try:
            from .career import CareerProfileStore, ResumeStore

            if profile is None:
                profile = CareerProfileStore().load()
            skills = list(getattr(profile, "skills", []) or [])
            if resume is None:
                resume_ids = getattr(profile, "resume_ids", []) or []
                if resume_ids:
                    resume = ResumeStore().load(resume_ids[0])
        except Exception:
            pass

        if resume is not None:
            contact = getattr(resume, "contact", {}) or {}
            name = contact.get("name", name)
            for key in ("email", "phone"):
                if contact.get(key):
                    contact_bits.append(contact[key])
            if resume.skills:
                skills = list({*skills, *resume.skills})

        skills_text = ", ".join(skills[:6]) if skills else "relevant technical skills"
        company = listing.company or "your company"
        title = listing.title or "the role"

        lines = [
            f"Dear Hiring Team at {company},",
            "",
            f"I am writing to express my interest in the {title} position"
            + (f" located in {listing.location}." if listing.location else "."),
            "",
            f"My background includes experience with {skills_text}. "
            f"I am confident these skills would let me contribute effectively "
            f"to {company}.",
            "",
            "I would welcome the opportunity to discuss how my experience aligns "
            "with your team's goals. Thank you for your consideration.",
            "",
            "Sincerely,",
            name,
        ]
        if contact_bits:
            lines.append(" | ".join(contact_bits))

        letter = "\n".join(lines)
        if self.enhancer:
            try:
                letter = self.enhancer(letter)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(f"Cover letter enhancer failed, using template: {exc}")
        return letter


class ApplicationChecklist:
    """Generate a tailored application preparation checklist."""

    def generate(self, listing: JobListing) -> List[str]:
        steps = [
            "Tailor resume to the job description",
            f"Write cover letter for {listing.title or 'the role'}",
        ]
        if listing.company:
            steps.append(f"Research {listing.company} (mission, products, recent news)")
        if listing.url:
            steps.append("Save the original job posting link")
        steps.extend(
            [
                "Prepare answers to common interview questions",
                "Gather references or portfolio links",
                "Review and submit application",
            ]
        )
        return steps


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
class JobSearchTool(Tool):
    name = "job.search"
    description = "Search for jobs across configured sources"
    permissions = ["job.read"]

    def run(
        self,
        keywords: str = "",
        role: str = "",
        location: str = "",
        remote: bool = False,
        max_results: int = 20,
        use_mock: bool = False,
    ) -> ToolResult:
        query = JobSearchQuery(
            keywords=keywords,
            role=role,
            location=location,
            remote=remote,
            max_results=max_results,
        )
        manager = JobSearchManager(use_mock=use_mock)
        listings, errors = manager.search(query)
        return ToolResult(
            success=True,
            result={
                "query": query.describe(),
                "count": len(listings),
                "listings": [asdict(listing) for listing in listings],
                "errors": errors,
            },
            tool=self.name,
        )


class JobListTool(Tool):
    name = "job.list"
    description = "List saved job listings"
    permissions = ["job.read"]

    def run(self) -> ToolResult:
        listings = JobStore().list()
        return ToolResult(
            success=True,
            result={"count": len(listings), "listings": [asdict(x) for x in listings]},
            tool=self.name,
        )


class JobGetTool(Tool):
    name = "job.get"
    description = "Get a saved job listing by ID"
    permissions = ["job.read"]

    def run(self, job_id: str) -> ToolResult:
        listing = JobStore().get(job_id)
        if not listing:
            return ToolResult(success=False, error="job not found", tool=self.name)
        return ToolResult(success=True, result=asdict(listing), tool=self.name)


class JobSaveTool(Tool):
    name = "job.save"
    description = "Save a job listing locally"
    permissions = ["job.write"]

    def run(
        self,
        title: str,
        company: str = "",
        location: str = "",
        remote: bool = False,
        url: str = "",
        source: str = "manual",
        salary: str = "",
        description: str = "",
        tags: Optional[List[str]] = None,
    ) -> ToolResult:
        if not title:
            return ToolResult(success=False, error="title is required", tool=self.name)
        listing = JobListing(
            id=_new_id("job"),
            title=title,
            company=company,
            location=location,
            remote=remote,
            url=url,
            source=source,
            salary=salary,
            description=description,
            tags=tags or [],
        )
        job_id = JobStore().save(listing)
        return ToolResult(success=True, result={"job_id": job_id}, tool=self.name)


class JobMatchTool(Tool):
    name = "job.match"
    description = "Score a job listing against the career profile"
    permissions = ["job.read"]

    def run(
        self,
        job_id: str = "",
        title: str = "",
        description: str = "",
        tags: Optional[List[str]] = None,
    ) -> ToolResult:
        if job_id:
            listing = JobStore().get(job_id)
            if not listing:
                return ToolResult(success=False, error="job not found", tool=self.name)
        elif title:
            listing = JobListing(
                id="",
                title=title,
                company="",
                description=description,
                tags=tags or [],
            )
        else:
            return ToolResult(
                success=False, error="job_id or title is required", tool=self.name
            )

        score, reasons = JobMatcher().score(listing)
        return ToolResult(
            success=True,
            result={"job_id": listing.id, "title": listing.title, "score": score, "reasons": reasons},
            tool=self.name,
        )


class ApplicationAddTool(Tool):
    name = "application.add"
    description = "Track a new job application"
    permissions = ["job.write"]

    def run(
        self,
        job_id: str = "",
        title: str = "",
        company: str = "",
        resume_id: str = "",
        notes: str = "",
    ) -> ToolResult:
        listing = JobStore().get(job_id) if job_id else None
        if listing:
            title = title or listing.title
            company = company or listing.company
        if not title and not company:
            return ToolResult(
                success=False, error="title or job_id is required", tool=self.name
            )
        application = JobApplication(
            id=_new_id("app"),
            job_id=job_id,
            title=title,
            company=company,
            resume_id=resume_id,
            status="saved",
        )
        if notes:
            application.notes.append({"note": notes, "timestamp": _now()})
        app_id = ApplicationStore().add(application)
        return ToolResult(success=True, result={"application_id": app_id}, tool=self.name)


class ApplicationListTool(Tool):
    name = "application.list"
    description = "List tracked job applications, optionally filtered by status"
    permissions = ["job.read"]

    def run(self, status: str = "") -> ToolResult:
        apps = ApplicationStore().list(status=status or None)
        return ToolResult(
            success=True,
            result={"count": len(apps), "applications": [asdict(a) for a in apps]},
            tool=self.name,
        )


class ApplicationGetTool(Tool):
    name = "application.get"
    description = "Get a job application by ID"
    permissions = ["job.read"]

    def run(self, application_id: str) -> ToolResult:
        app = ApplicationStore().get(application_id)
        if not app:
            return ToolResult(success=False, error="application not found", tool=self.name)
        return ToolResult(success=True, result=asdict(app), tool=self.name)


class ApplicationUpdateStatusTool(Tool):
    name = "application.update_status"
    description = "Update the status of a job application"
    permissions = ["job.write"]

    def run(self, application_id: str, status: str, note: str = "") -> ToolResult:
        success, message = ApplicationStore().update_status(application_id, status)
        if not success:
            return ToolResult(success=False, error=message, tool=self.name)
        if note:
            ApplicationStore().add_note(application_id, note)
        return ToolResult(
            success=True, result={"application_id": application_id, "status": status}, tool=self.name
        )


class ApplicationDeleteTool(Tool):
    name = "application.delete"
    description = "Delete a tracked job application"
    permissions = ["job.write"]

    def run(self, application_id: str) -> ToolResult:
        if ApplicationStore().delete(application_id):
            return ToolResult(success=True, result={"deleted": application_id}, tool=self.name)
        return ToolResult(success=False, error="application not found", tool=self.name)


class ApplicationPrepareTool(Tool):
    name = "application.prepare"
    description = "Generate a cover letter and prep checklist for a job"
    permissions = ["job.read"]

    def run(self, job_id: str = "") -> ToolResult:
        listing = JobStore().get(job_id) if job_id else None
        if not listing:
            return ToolResult(success=False, error="job not found", tool=self.name)
        letter = CoverLetterGenerator().generate(listing)
        checklist = ApplicationChecklist().generate(listing)
        return ToolResult(
            success=True,
            result={
                "job_id": listing.id,
                "title": listing.title,
                "company": listing.company,
                "cover_letter": letter,
                "checklist": checklist,
            },
            tool=self.name,
        )


class ApplicationFollowupTool(Tool):
    name = "application.followup"
    description = "Draft or send a follow-up email for an application"
    permissions = ["job.write", "email.send"]

    def run(
        self,
        application_id: str,
        email: str = "",
        to: str = "",
        send: bool = False,
        body: str = "",
    ) -> ToolResult:
        app = ApplicationStore().get(application_id)
        if not app:
            return ToolResult(success=False, error="application not found", tool=self.name)

        if not body:
            company = app.company or "your company"
            title = app.title or "the role"
            body = (
                f"Dear Hiring Team at {company},\n\n"
                f"I wanted to follow up on my application for the {title} position. "
                f"I remain very interested and would be glad to provide any additional "
                f"information.\n\nBest regards"
            )

        draft = {
            "application_id": application_id,
            "to": to,
            "subject": f"Follow-up: {app.title or 'Application'}"
            + (f" at {app.company}" if app.company else ""),
            "body": body,
        }

        if not send:
            return ToolResult(success=True, result={"draft": draft, "sent": False}, tool=self.name)

        # Send path: requires a connected account and recipient
        if not email:
            return ToolResult(
                success=False, error="email account required to send", tool=self.name
            )
        if not to:
            return ToolResult(success=False, error="recipient 'to' required", tool=self.name)

        try:
            from .email import EmailAccountManager

            manager = EmailAccountManager()
            if not manager.auth.get_account(email):
                return ToolResult(
                    success=False, error="email account not connected", tool=self.name
                )
            success, message = manager.send_email(
                email, [to], draft["subject"], body
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc), tool=self.name)

        if not success:
            return ToolResult(success=False, error=message, tool=self.name)

        ApplicationStore().add_note(application_id, f"Follow-up email sent to {to}")
        return ToolResult(
            success=True, result={"draft": draft, "sent": True}, tool=self.name
        )


class JobStatsTool(Tool):
    name = "job.stats"
    description = "Show application funnel stats"
    permissions = ["job.read"]

    def run(self) -> ToolResult:
        return ToolResult(success=True, result=ApplicationStore().stats(), tool=self.name)


def get_job_tools() -> List[Tool]:
    """Return all Phase 10 job/application tools."""
    return [
        JobSearchTool(),
        JobListTool(),
        JobGetTool(),
        JobSaveTool(),
        JobMatchTool(),
        ApplicationAddTool(),
        ApplicationListTool(),
        ApplicationGetTool(),
        ApplicationUpdateStatusTool(),
        ApplicationDeleteTool(),
        ApplicationPrepareTool(),
        ApplicationFollowupTool(),
        JobStatsTool(),
    ]


def get_job_tools_for_registry() -> List[Tool]:
    return get_job_tools()
