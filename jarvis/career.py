"""Resume and Career management for Jarvis."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import get_data_dir
from .logging import get_logger
from .tools import Tool, ToolResult

logger = get_logger(__name__)

# Resume data directory
RESUME_DIR = Path(get_data_dir()) / "resumes"
RESUME_DIR.mkdir(parents=True, exist_ok=True)

# Career profile file
CAREER_PROFILE_FILE = Path(get_data_dir()) / "career_profile.json"


@dataclass
class ResumeSection:
    """A section of a resume."""
    title: str
    content: str
    order: int = 0


@dataclass
class Resume:
    """Parsed resume data."""
    id: str
    filename: str
    source: str
    source_id: Optional[str] = None
    parsed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    raw_text: str = ""
    sections: List[ResumeSection] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)
    experience: List[Dict[str, Any]] = field(default_factory=list)
    education: List[Dict[str, Any]] = field(default_factory=list)
    projects: List[Dict[str, Any]] = field(default_factory=list)
    contact: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CareerProfile:
    """User's career profile built from resumes and interactions."""
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    current_role: str = ""
    target_roles: List[str] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)
    experience_years: Optional[int] = None
    preferred_locations: List[str] = field(default_factory=list)
    remote_preference: str = "any"
    salary_expectation: Optional[str] = None
    resume_ids: List[str] = field(default_factory=list)
    notes: List[Dict[str, Any]] = field(default_factory=list)


class ResumeParser:
    """Parse resume text into structured data."""

    SECTION_PATTERNS = {
        "summary": [r"summary", r"profile", r"objective", r"about"],
        "experience": [r"experience", r"employment", r"work history", r"professional experience"],
        "education": [r"education", r"academic", r"degrees", r"qualifications"],
        "skills": [r"skills", r"technologies", r"technical skills", r"competencies", r"tools"],
        "projects": [r"projects", r"portfolio", r"personal projects"],
        "certifications": [r"certifications?", r"licenses?", r"credentials?"],
        "languages": [r"languages?"],
        "awards": [r"awards?", r"honors?", r"achievements?"],
        "publications": [r"publications?", r"papers?"],
    }

    SKILL_KEYWORDS = [
        "python", "javascript", "typescript", "java", "c#", "c++", "go", "rust",
        "ruby", "php", "swift", "kotlin", "scala", "r", "matlab", "sql",
        "react", "vue", "angular", "django", "flask", "fastapi", "spring",
        "express", "next.js", "nuxt", "rails", "laravel", ".net", "node",
        "aws", "azure", "gcp", "docker", "kubernetes", "terraform", "ansible",
        "jenkins", "gitlab", "github actions", "ci/cd", "linux", "nginx",
        "postgresql", "mysql", "mongodb", "redis", "elasticsearch", "dynamodb",
        "sqlite", "cassandra", "snowflake", "bigquery",
        "machine learning", "deep learning", "tensorflow", "pytorch", "scikit-learn",
        "nlp", "computer vision", "llm", "transformers", "langchain",
        "git", "agile", "scrum", "jira", "rest", "graphql", "grpc", "microservices",
        "api", "testing", "tdd", "devops", "monitoring", "observability",
    ]

    def parse(self, text: str, resume_id: str = "", filename: str = "") -> Resume:
        resume = Resume(
            id=resume_id or f"resume_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
            filename=filename,
            source="manual",
            raw_text=text,
        )

        resume.contact = self._extract_contact(text)
        resume.sections = self._extract_sections(text)
        resume.skills = self._extract_skills(text)

        exp_section = next((s for s in resume.sections if s.title.lower() == "experience"), None)
        if exp_section:
            resume.experience = self._parse_experience(exp_section.content)

        edu_section = next((s for s in resume.sections if s.title.lower() == "education"), None)
        if edu_section:
            resume.education = self._parse_education(edu_section.content)

        proj_section = next((s for s in resume.sections if s.title.lower() == "projects"), None)
        if proj_section:
            resume.projects = self._parse_projects(proj_section.content)

        return resume

    def _extract_contact(self, text: str) -> Dict[str, str]:
        contact = {}
        lines = text.split("\n")[:20]

        email_match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)
        if email_match:
            contact["email"] = email_match.group()

        phone_match = re.search(r"[\+\(]?[0-9]{1,3}\)?[\s\-\.]?[0-9]{3}[\s\-\.]?[0-9]{4}", text)
        if phone_match:
            contact["phone"] = phone_match.group()

        linkedin_match = re.search(r"linkedin\.com/in/[a-zA-Z0-9\-]+", text, re.IGNORECASE)
        if linkedin_match:
            contact["linkedin"] = linkedin_match.group()

        github_match = re.search(r"github\.com/[a-zA-Z0-9\-]+", text, re.IGNORECASE)
        if github_match:
            contact["github"] = github_match.group()

        for line in lines[:5]:
            line = line.strip()
            if line and len(line.split()) >= 2 and not any(c in line for c in "@:/\\"):
                contact["name"] = line
                break

        return contact

    def _extract_sections(self, text: str) -> List[ResumeSection]:
        sections = []
        lines = text.split("\n")
        current_section = None
        current_content = []

        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                if current_section:
                    current_content.append("")
                continue

            is_header = False
            section_title = ""
            for section_key, patterns in self.SECTION_PATTERNS.items():
                for pattern in patterns:
                    if re.search(rf"^{pattern}[:]?\s*$", line_stripped, re.IGNORECASE):
                        is_header = True
                        section_title = section_key.capitalize()
                        break
            if is_header:
                if current_section and current_content:
                    sections.append(ResumeSection(
                        title=current_section,
                        content="\n".join(current_content).strip(),
                        order=len(sections),
                    ))
                current_section = section_title
                current_content = []
            elif current_section:
                current_content.append(line)

        if current_section and current_content:
            sections.append(ResumeSection(
                title=current_section,
                content="\n".join(current_content).strip(),
                order=len(sections),
            ))

        return sections

    def _extract_skills(self, text: str) -> List[str]:
        found_skills = []
        text_lower = text.lower()
        for skill in self.SKILL_KEYWORDS:
            if skill.lower() in text_lower:
                found_skills.append(skill)
        return sorted(set(found_skills))

    def _parse_experience(self, content: str) -> List[Dict[str, Any]]:
        experiences = []
        entries = re.split(r"\n\s*\n", content)
        for entry in entries:
            if len(entry.strip()) < 20:
                continue
            exp = {"raw": entry.strip()}
            lines = entry.strip().split("\n")
            if lines:
                exp["summary"] = lines[0]
            experiences.append(exp)
        return experiences

    def _parse_education(self, content: str) -> List[Dict[str, Any]]:
        education = []
        entries = re.split(r"\n\s*\n", content)
        for entry in entries:
            if len(entry.strip()) < 10:
                continue
            edu = {"raw": entry.strip()}
            lines = entry.strip().split("\n")
            if lines:
                edu["summary"] = lines[0]
            education.append(edu)
        return education

    def _parse_projects(self, content: str) -> List[Dict[str, Any]]:
        projects = []
        entries = re.split(r"\n\s*\n", content)
        for entry in entries:
            if len(entry.strip()) < 15:
                continue
            proj = {"raw": entry.strip()}
            lines = entry.strip().split("\n")
            if lines:
                proj["name"] = lines[0]
            projects.append(proj)
        return projects


class ResumeStore:
    """Store and retrieve resumes."""

    def __init__(self):
        self.resume_dir = RESUME_DIR
        self.resume_dir.mkdir(parents=True, exist_ok=True)

    def save(self, resume: Resume) -> str:
        filepath = self.resume_dir / f"{resume.id}.json"
        data = asdict(resume)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return resume.id

    def load(self, resume_id: str) -> Optional[Resume]:
        filepath = self.resume_dir / f"{resume_id}.json"
        if not filepath.exists():
            return None
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return self._dict_to_resume(data)

    def list(self) -> List[Dict[str, Any]]:
        resumes = []
        for filepath in self.resume_dir.glob("*.json"):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                resumes.append({
                    "id": data.get("id"),
                    "filename": data.get("filename"),
                    "source": data.get("source"),
                    "parsed_at": data.get("parsed_at"),
                    "skills_count": len(data.get("skills", [])),
                })
            except Exception:
                pass
        return sorted(resumes, key=lambda x: x.get("parsed_at", ""), reverse=True)

    def delete(self, resume_id: str) -> bool:
        filepath = self.resume_dir / f"{resume_id}.json"
        if filepath.exists():
            filepath.unlink()
            return True
        return False

    def _dict_to_resume(self, data: Dict) -> Resume:
        sections = [ResumeSection(**s) for s in data.get("sections", [])]
        resume = Resume(
            id=data.get("id", ""),
            filename=data.get("filename", ""),
            source=data.get("source", "manual"),
            source_id=data.get("source_id"),
            parsed_at=data.get("parsed_at", ""),
            raw_text=data.get("raw_text", ""),
            sections=sections,
            skills=data.get("skills", []),
            experience=data.get("experience", []),
            education=data.get("education", []),
            projects=data.get("projects", []),
            contact=data.get("contact", {}),
            metadata=data.get("metadata", {}),
        )
        return resume


class CareerProfileStore:
    """Store and manage career profile."""

    def __init__(self):
        self.profile_file = CAREER_PROFILE_FILE

    def load(self) -> CareerProfile:
        if self.profile_file.exists():
            with open(self.profile_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return CareerProfile(**data)
        return CareerProfile()

    def save(self, profile: CareerProfile) -> None:
        profile.updated_at = datetime.utcnow().isoformat()
        with open(self.profile_file, "w", encoding="utf-8") as f:
            json.dump(asdict(profile), f, indent=2, ensure_ascii=False)

    def add_resume(self, resume_id: str) -> None:
        profile = self.load()
        if resume_id not in profile.resume_ids:
            profile.resume_ids.append(resume_id)
            self.save(profile)

    def update_skills(self, skills: List[str]) -> None:
        profile = self.load()
        profile.skills = list(set(profile.skills + skills))
        self.save(profile)

    def set_target_role(self, role: str) -> None:
        profile = self.load()
        if role not in profile.target_roles:
            profile.target_roles.append(role)
        self.save(profile)


# Tool classes for the registry
class ResumeParseTool(Tool):
    name = "resume.parse"
    description = "Parse resume text into structured data"
    permissions = ["resume.parse"]

    def run(self, text: str, filename: str = "") -> ToolResult:
        parser = ResumeParser()
        resume_id = f"resume_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        resume = parser.parse(text, resume_id=resume_id, filename=filename)

        store = ResumeStore()
        store.save(resume)

        career = CareerProfileStore()
        career.add_resume(resume.id)
        if resume.skills:
            career.update_skills(resume.skills)

        return ToolResult(
            success=True,
            result={
                "resume_id": resume.id,
                "filename": filename,
                "skills_found": len(resume.skills),
                "experience_entries": len(resume.experience),
                "education_entries": len(resume.education),
                "projects_count": len(resume.projects),
            },
        )


class ResumeListTool(Tool):
    name = "resume.list"
    description = "List all stored resumes"
    permissions = ["resume.read"]

    def run(self) -> ToolResult:
        store = ResumeStore()
        resumes = store.list()
        return ToolResult(
            success=True,
            result={"count": len(resumes), "resumes": resumes},
        )


class ResumeGetTool(Tool):
    name = "resume.get"
    description = "Get a resume by ID"
    permissions = ["resume.read"]

    def run(self, resume_id: str) -> ToolResult:
        store = ResumeStore()
        resume = store.load(resume_id)
        if not resume:
            return ToolResult(success=False, error="Resume not found")
        return ToolResult(
            success=True,
            result=asdict(resume),
        )


class ResumeDeleteTool(Tool):
    name = "resume.delete"
    description = "Delete a stored resume"
    permissions = ["resume.write"]

    def run(self, resume_id: str) -> ToolResult:
        store = ResumeStore()
        success = store.delete(resume_id)
        if success:
            career = CareerProfileStore()
            profile = career.load()
            if resume_id in profile.resume_ids:
                profile.resume_ids.remove(resume_id)
                career.save(profile)
            return ToolResult(success=True, result={"deleted": resume_id})
        return ToolResult(success=False, error="Resume not found")


class CareerProfileTool(Tool):
    name = "career.profile"
    description = "View or update career profile"
    permissions = ["career.read", "career.write"]

    def run(
        self,
        action: str = "view",
        target_role: str = None,
        skill: str = None,
        notes: str = None,
    ) -> ToolResult:
        career = CareerProfileStore()
        profile = career.load()

        if action == "view":
            return ToolResult(success=True, result=asdict(profile))

        elif action == "add_target_role":
            if not target_role:
                return ToolResult(success=False, error="target_role required")
            career.set_target_role(target_role)
            return ToolResult(success=True, result={"target_roles": career.load().target_roles})

        elif action == "add_skill":
            if not skill:
                return ToolResult(success=False, error="skill required")
            career.update_skills([skill])
            return ToolResult(success=True, result={"skills": career.load().skills})

        elif action == "add_note":
            if not notes:
                return ToolResult(success=False, error="notes required")
            profile = career.load()
            profile.notes.append({
                "note": notes,
                "timestamp": datetime.utcnow().isoformat(),
            })
            career.save(profile)
            return ToolResult(success=True, result={"notes_count": len(profile.notes)})

        return ToolResult(success=False, error=f"Unknown action: {action}")


class ResumeSearchTool(Tool):
    name = "resume.search"
    description = "Search resumes by keyword"
    permissions = ["resume.read"]

    def run(self, query: str) -> ToolResult:
        store = ResumeStore()
        resumes = store.list()
        query_lower = query.lower()

        matches = []
        for r in resumes:
            resume = store.load(r["id"])
            if not resume:
                continue
            match_score = 0
            if query.lower() in resume.raw_text.lower():
                match_score += 3
            if any(query_lower in skill.lower() for skill in resume.skills):
                match_score += 2
            for exp in resume.experience:
                if query.lower() in exp.get("raw", "").lower():
                    match_score += 1
            if match_score > 0:
                matches.append({
                    "resume_id": resume.id,
                    "filename": resume.filename,
                    "match_score": match_score,
                    "skills": resume.skills[:5],
                })

        matches.sort(key=lambda x: x["match_score"], reverse=True)
        return ToolResult(
            success=True,
            result={"query": query, "matches": matches},
        )


def get_resume_tools() -> List[Tool]:
    return [
        ResumeParseTool(),
        ResumeListTool(),
        ResumeGetTool(),
        ResumeDeleteTool(),
        CareerProfileTool(),
        ResumeSearchTool(),
    ]


def get_resume_tools_for_registry() -> List[Tool]:
    return get_resume_tools()
