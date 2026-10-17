"""Phase 8 Resume/Career Tests"""

import os
import json
from pathlib import Path
import tempfile

from jarvis.career import (
    ResumeParser,
    ResumeStore,
    CareerProfileStore,
    Resume,
    ResumeSection,
    CareerProfile,
)


def test_resume_parser_basic():
    """Test basic resume parsing."""
    parser = ResumeParser()
    text = """John Doe
john.doe@example.com
(555) 123-4567
linkedin.com/in/johndoe

Summary
Experienced software engineer with 5 years experience.

Experience
Senior Developer at TechCorp (2020-2023)
- Built scalable web applications using Python and React
- Led team of 5 engineers

Education
BS Computer Science, University of Tech (2018)

Skills
Python, JavaScript, React, Docker, AWS, PostgreSQL

Projects
Personal Portfolio Website
- Built with React and Node.js"""
    
    resume = parser.parse(text, resume_id="test_1", filename="resume.txt")
    
    assert resume.id == "test_1"
    assert resume.filename == "resume.txt"
    assert "john.doe@example.com" in resume.contact.get("email", "")
    assert len(resume.sections) >= 3  # summary, experience, education, skills, projects
    assert any("python" in s.lower() for s in resume.skills)
    assert any("javascript" in s.lower() for s in resume.skills)
    assert len(resume.experience) >= 1
    assert len(resume.education) >= 1
    assert len(resume.projects) >= 1
    print("✓ Test 1 PASSED: Basic resume parsing")


def test_resume_store_save_load():
    """Test saving and loading resumes."""
    parser = ResumeParser()
    store = ResumeStore()
    
    text = "Jane Smith\njane@example.com\n\nExperience\nDeveloper at Corp\nSkills\nPython, Django"
    resume = parser.parse(text, resume_id="test_2", filename="jane_resume.txt")
    resume_id = store.save(resume)
    
    loaded = store.load(resume_id)
    assert loaded is not None
    assert loaded.id == "test_2"
    assert loaded.filename == "jane_resume.txt"
    assert "Jane Smith" in loaded.raw_text
    print("✓ Test 2 PASSED: Resume save/load")


def test_resume_list():
    """Test listing resumes."""
    store = ResumeStore()
    resumes = store.list()
    assert isinstance(resumes, list)
    for r in resumes:
        assert "id" in r
        assert "filename" in r
    print("✓ Test 3 PASSED: Resume list")


def test_resume_delete():
    """Test deleting a resume."""
    store = ResumeStore()
    parser = ResumeParser()
    
    text = "Test User\ntest@example.com\nExperience\nTest role"
    resume = parser.parse(text, resume_id="delete_test", filename="delete_me.txt")
    store.save(resume)
    
    # Verify it exists
    assert store.load("delete_test") is not None
    
    # Delete it
    success = store.delete("delete_test")
    assert success is True
    
    # Verify it's gone
    assert store.load("delete_test") is None
    print("✓ Test 4 PASSED: Resume delete")


def test_resume_search():
    """Test searching resumes by keyword."""
    from jarvis.career import ResumeSearchTool
    
    store = ResumeStore()
    parser = ResumeParser()
    
    # Create a few test resumes
    r1 = parser.parse("Python Developer\nPython, Django, AWS\nExperience\nBackend dev", 
                       resume_id="search_1", filename="py_dev.txt")
    store.save(r1)
    
    r2 = parser.parse("Frontend Developer\nReact, TypeScript, CSS\nExperience\nFrontend dev",
                     resume_id="search_2", filename="fe_dev.txt")
    store.save(r2)
    
    # Search for Python
    tool = ResumeSearchTool()
    r = tool.run(query="Python")
    assert r.success
    matches = r.result.get("matches", [])
    assert len(matches) >= 1
    assert any("python" in str(m.get("skills", [])).lower() for m in matches)
    print("✓ Test 5 PASSED: Resume search by keyword")


def test_career_profile():
    """Test career profile management."""
    career = CareerProfileStore()
    profile = career.load()
    
    # Initially empty
    assert isinstance(profile, CareerProfile)
    
    # Add target role
    career.set_target_role("Senior Backend Engineer")
    profile = career.load()
    assert "Senior Backend Engineer" in profile.target_roles
    
    # Add skill
    career.update_skills(["Kubernetes", "Terraform"])
    profile = career.load()
    assert "Kubernetes" in profile.skills
    assert "Terraform" in profile.skills
    
    # Add note
    profile = career.load()
    profile.notes.append({
        "note": "Interview scheduled for next week",
        "timestamp": "2026-01-15T10:00:00"
    })
    # Save manually since we modified directly
    # The CareerProfileStore.save handles this
    # Actually let's test the tool
    from jarvis.career import CareerProfileTool
    tool = CareerProfileTool()
    r = tool.run(action="add_note", notes="Test note")
    assert r.success
    
    print("✓ Test 6 PASSED: Career profile management")


def test_resume_tools_via_registry():
    """Test that tools are accessible via registry."""
    from jarvis.tools import get_enhanced_registry
    reg = __import__('jarvis.tools').tools.get_enhanced_registry()
    
    resume_tools = ['resume.parse', 'resume.list', 'resume.get', 'resume.delete', 
                    'career.profile', 'resume.search']
    names = [t['name'] for t in reg.list_tools()]
    
    for name in resume_tools:
        assert name in names, f"Missing tool: {name}"
    
    print("✓ Test 7 PASSED: All resume tools in registry")


def test_resume_parse_tool():
    """Test ResumeParseTool directly."""
    from jarvis.career import ResumeParseTool
    
    tool = ResumeParseTool()
    text = "Test User\ntest@example.com\n\nExperience\nSoftware Engineer at TestCo\nSkills\nPython, JavaScript, React"
    r = tool.run(text=text, filename="test_resume.txt")
    
    assert r.success
    assert r.result.get("resume_id") is not None
    assert r.result.get("skills_found", 0) > 0
    assert r.result.get("experience_entries", 0) >= 1
    print("✓ Test 8 PASSED: ResumeParseTool")


def test_resume_list_tool():
    """Test ResumeListTool."""
    from jarvis.career import ResumeListTool
    
    tool = ResumeListTool()
    r = tool.run()
    
    assert r.success
    assert "count" in r.result
    assert "resumes" in r.result
    assert isinstance(r.result["resumes"], list)
    print("✓ Test 9 PASSED: ResumeListTool")


def test_resume_get_tool():
    """Test ResumeGetTool."""
    from jarvis.career import ResumeGetTool

    # Seed our own fixture: this test must not depend on execution order.
    store = ResumeStore()
    if store.load("test_2") is None:
        parser = ResumeParser()
        store.save(
            parser.parse(
                "Jane Smith\njane@example.com\n\nExperience\nDeveloper at Corp"
                "\nSkills\nPython",
                resume_id="test_2",
                filename="jane_resume.txt",
            )
        )

    tool = ResumeGetTool()
    r = tool.run(resume_id="test_2")

    assert r.success
    assert r.result.get("id") == "test_2"
    print("✓ Test 10 PASSED: ResumeGetTool")


def test_career_profile_tool():
    """Test CareerProfileTool."""
    from jarvis.career import CareerProfileTool
    
    tool = CareerProfileTool()
    
    # View
    r = tool.run(action="view")
    assert r.success
    assert "target_roles" in r.result
    assert "skills" in r.result
    
    # Add target role
    r = tool.run(action="add_target_role", target_role="Senior Engineer")
    assert r.success
    assert "Senior Engineer" in r.result.get("target_roles", [])
    
    # Add skill
    r = tool.run(action="add_skill", skill="GraphQL")
    assert r.success
    assert "GraphQL" in r.result.get("skills", [])
    
    # Add note
    r = tool.run(action="add_note", notes="Applied to Company X")
    assert r.success
    
    print("✓ Test 11 PASSED: CareerProfileTool")


def test_resume_search_tool():
    """Test ResumeSearchTool."""
    from jarvis.career import ResumeSearchTool
    
    tool = ResumeSearchTool()
    r = tool.run(query="Python")
    
    assert r.success
    assert "query" in r.result
    assert "matches" in r.result
    print("✓ Test 12 PASSED: ResumeSearchTool")


def test_resume_delete_tool():
    """Test ResumeDeleteTool."""
    from jarvis.career import ResumeDeleteTool, ResumeStore, ResumeParser
    
    parser = ResumeParser()
    store = ResumeStore()
    
    # Create a resume to delete
    text = "Delete Me\nme@test.com\nExperience\nTest role"
    resume = parser.parse(text, resume_id="to_delete", filename="delete.txt")
    store.save(resume)
    
    tool = ResumeDeleteTool()
    r = tool.run(resume_id="to_delete")
    
    assert r.success
    assert r.result.get("deleted") == "to_delete"
    
    # Verify deleted
    assert store.load("to_delete") is None
    print("✓ Test 13 PASSED: ResumeDeleteTool")


def test_career_profile_with_resumes():
    """Test career profile links to resumes."""
    career = CareerProfileStore()
    store = ResumeStore()
    parser = ResumeParser()
    
    # Parse a resume
    text = "Test User\nuser@test.com\nExperience\nDev at Corp\nSkills\nPython, Go"
    resume = parser.parse(text, resume_id="profile_test_1", filename="profile_test.txt")
    store.save(resume)
    
    # Add to career profile
    career.add_resume(resume.id)
    career.update_skills(resume.skills)
    
    profile = career.load()
    assert resume.id in profile.resume_ids
    assert any("python" in s.lower() or "go" in s.lower() for s in profile.skills)
    print("✓ Test 14 PASSED: Career profile links to resumes")


def test_resume_section_extraction():
    """Test section extraction handles various formats."""
    parser = ResumeParser()
    
    # Test with different header styles
    text = """Name
Email

SUMMARY
This is a summary.

EXPERIENCE
Role at Company

Education
BS Degree

SKILLS
Python, Java"""
    
    resume = parser.parse(text)
    section_titles = [s.title for s in resume.sections]
    assert "Summary" in section_titles
    assert "Experience" in section_titles
    assert "Education" in section_titles
    assert "Skills" in section_titles
    print("✓ Test 15 PASSED: Section extraction handles various header styles")


def test_skill_extraction_case_insensitive():
    """Test skill extraction is case insensitive."""
    parser = ResumeParser()
    text = "Skills: PYTHON, javascript, TypeScript, Go, DOCKER"
    skills = parser._extract_skills(text)
    assert any("python" in s.lower() for s in skills)
    assert any("javascript" in s.lower() for s in skills)
    assert any("typescript" in s.lower() for s in skills)
    assert any("go" in s.lower() for s in skills)
    assert any("docker" in s.lower() for s in skills)
    print("✓ Test 16 PASSED: Case-insensitive skill extraction")


def run_all():
    test_resume_parser_basic()
    test_resume_store_save_load()
    test_resume_list()
    test_resume_delete()
    test_resume_search()
    test_career_profile()
    test_resume_tools_via_registry()
    test_resume_parse_tool()
    test_resume_list_tool()
    test_resume_get_tool()
    test_career_profile_tool()
    test_resume_search_tool()
    test_resume_delete_tool()
    test_career_profile_with_resumes()
    test_resume_section_extraction()
    test_skill_extraction_case_insensitive()
    print("\n=== ALL PHASE 8 CAREER TESTS PASSED ===")


if __name__ == "__main__":
    run_all()
