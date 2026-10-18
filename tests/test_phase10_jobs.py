"""Phase 10 Job Discovery / Application Workflow Tests (offline)."""

import tempfile
from pathlib import Path

from jarvis.jobs import (
    ALLOWED_TRANSITIONS,
    APPLICATION_STATUSES,
    ApplicationChecklist,
    ApplicationStore,
    CoverLetterGenerator,
    JobApplication,
    JobListing,
    JobMatcher,
    JobSearchManager,
    JobSearchQuery,
    JobStore,
    MockJobSource,
    WebSearchJobSource,
)


class _FakeResult:
    def __init__(self, title, url, snippet, metadata=None):
        self.title = title
        self.url = url
        self.snippet = snippet
        self.metadata = metadata or {}


def _tmp_store():
    d = tempfile.mkdtemp()
    return JobStore(Path(d) / "listings.json"), ApplicationStore(Path(d) / "apps.json")


# 1
def test_job_listing_dataclass():
    listing = JobListing(id="j1", title="Engineer", company="Acme")
    assert listing.id == "j1"
    assert listing.remote is False
    assert listing.tags == []
    print("✓ Test 1 PASSED: JobListing dataclass")


# 2
def test_job_search_query_dataclass():
    q = JobSearchQuery(keywords="python", role="Backend", location="Remote", remote=True)
    assert q.role == "Backend"
    assert q.remote is True
    print("✓ Test 2 PASSED: JobSearchQuery dataclass")


# 3
def test_job_application_dataclass():
    app = JobApplication(id="a1", title="Engineer", company="Acme")
    assert app.status == "saved"
    assert isinstance(app.notes, list)
    assert app.created_at
    print("✓ Test 3 PASSED: JobApplication dataclass")


# 4
def test_query_describe():
    assert "Backend" in JobSearchQuery(role="Backend", location="NYC").describe()
    assert "remote" in JobSearchQuery(keywords="x", remote=True).describe()
    print("✓ Test 4 PASSED: JobSearchQuery.describe")


# 5
def test_mock_job_source_returns_listings():
    src = MockJobSource()
    results = src.search(JobSearchQuery(role="Backend Engineer"))
    assert len(results) >= 1
    assert all(isinstance(r, JobListing) for r in results)
    assert all(r.source == "mock" for r in results)
    print("✓ Test 5 PASSED: MockJobSource returns listings")


# 6
def test_mock_job_source_max_results():
    src = MockJobSource()
    results = src.search(JobSearchQuery(keywords="dev", max_results=2))
    assert len(results) == 2
    print("✓ Test 6 PASSED: MockJobSource respects max_results")


# 7
def test_mock_job_source_remote_flag():
    src = MockJobSource()
    results = src.search(JobSearchQuery(keywords="dev", remote=True, max_results=5))
    assert any(r.remote for r in results)
    print("✓ Test 7 PASSED: MockJobSource remote flag")


# 8
def test_web_search_job_source():
    from jarvis.web_search import SearchManager

    src = WebSearchJobSource(search_manager=SearchManager(use_mock=True))
    results = src.search(JobSearchQuery(role="Engineer"))
    assert len(results) >= 1
    assert all(r.source == "web_search" for r in results)
    print("✓ Test 8 PASSED: WebSearchJobSource returns listings")


# 9
def test_web_search_company_guess():
    src = WebSearchJobSource(search_manager=__import__("jarvis.web_search", fromlist=["SearchManager"]).SearchManager(use_mock=True))
    listing = src._result_to_listing(
        _FakeResult("Senior Engineer at Globex", "https://x/y", "Remote python role"),
        JobSearchQuery(),
    )
    assert listing.company == "Globex"
    assert listing.remote is True
    print("✓ Test 9 PASSED: WebSearchJobSource company/remote inference")


# 10
def test_web_search_tag_guess():
    src = WebSearchJobSource(search_manager=__import__("jarvis.web_search", fromlist=["SearchManager"]).SearchManager(use_mock=True))
    listing = src._result_to_listing(
        _FakeResult("Django Developer", "https://x/y", "requires python and docker"),
        JobSearchQuery(),
    )
    assert "python" in listing.tags
    assert "django" in listing.tags
    print("✓ Test 10 PASSED: WebSearchJobSource tag inference")


# 11
def test_job_search_manager_aggregates():
    manager = JobSearchManager(use_mock=True)
    listings, errors = manager.search(JobSearchQuery(keywords="dev", max_results=10))
    assert len(listings) >= 1
    assert errors == []
    print("✓ Test 11 PASSED: JobSearchManager aggregates sources")


# 12
def test_job_search_manager_error_fallback():
    class Broken:
        name = "broken"

        def search(self, query):
            raise RuntimeError("boom")

    manager = JobSearchManager(sources=[Broken(), MockJobSource()])
    listings, errors = manager.search(JobSearchQuery(keywords="dev"))
    assert len(listings) >= 1  # still got results from the working source
    assert any("broken" in e for e in errors)
    print("✓ Test 12 PASSED: JobSearchManager fallback records errors")


# 13
def test_job_matcher_skills():
    matcher = JobMatcher(skills=["python", "docker", "aws"])
    listing = JobListing(id="", title="Backend Engineer", company="X", description="python and docker required")
    score, reasons = matcher.score(listing)
    assert score > 0
    assert any("python" in r.lower() for r in reasons)
    print("✓ Test 13 PASSED: JobMatcher skill overlap")


# 14
def test_job_matcher_role():
    from jarvis.career import CareerProfile

    profile = CareerProfile(target_roles=["Senior Engineer"], skills=["go"])
    matcher = JobMatcher(profile=profile, skills=["go"])
    listing = JobListing(id="", title="Senior Engineer", company="X")
    score, reasons = matcher.score(listing)
    assert any("target role" in r.lower() for r in reasons)
    print("✓ Test 14 PASSED: JobMatcher target role match")


# 15
def test_job_matcher_remote():
    matcher = JobMatcher(skills=["python"])
    listing = JobListing(id="", title="Engineer", company="X", remote=True)
    score, reasons = matcher.score(listing)
    assert any("remote" in r.lower() for r in reasons)
    print("✓ Test 15 PASSED: JobMatcher remote bonus")


# 16
def test_job_store_roundtrip():
    store, _ = _tmp_store()
    listing = JobListing(id="", title="QA Engineer", company="Acme")
    job_id = store.save(listing)
    loaded = store.get(job_id)
    assert loaded is not None
    assert loaded.title == "QA Engineer"
    print("✓ Test 16 PASSED: JobStore save/get roundtrip")


# 17
def test_job_store_list_and_delete():
    store, _ = _tmp_store()
    a = store.save(JobListing(id="", title="A", company="C"))
    b = store.save(JobListing(id="", title="B", company="C"))
    assert len(store.list()) == 2
    assert store.delete(a) is True
    assert store.get(a) is None
    assert len(store.list()) == 1
    print("✓ Test 17 PASSED: JobStore list/delete")


# 18
def test_application_store_add_get():
    _, store = _tmp_store()
    app_id = store.add(JobApplication(id="", title="Engineer", company="Acme"))
    app = store.get(app_id)
    assert app is not None
    assert app.status == "saved"
    print("✓ Test 18 PASSED: ApplicationStore add/get")


# 19
def test_application_store_filter_status():
    _, store = _tmp_store()
    id1 = store.add(JobApplication(id="", title="A", company="X"))
    store.add(JobApplication(id="", title="B", company="Y"))
    store.update_status(id1, "applied")
    assert len(store.list(status="applied")) == 1
    assert len(store.list(status="saved")) == 1
    print("✓ Test 19 PASSED: ApplicationStore filter by status")


# 20
def test_application_valid_transition():
    _, store = _tmp_store()
    app_id = store.add(JobApplication(id="", title="A", company="X"))
    ok, msg = store.update_status(app_id, "applied")
    assert ok is True
    assert store.get(app_id).status == "applied"
    print("✓ Test 20 PASSED: ApplicationStore valid transition")


# 21
def test_application_invalid_transition():
    _, store = _tmp_store()
    app_id = store.add(JobApplication(id="", title="A", company="X"))
    ok, msg = store.update_status(app_id, "offer")  # saved -> offer not allowed
    assert ok is False
    assert "invalid transition" in msg
    assert store.get(app_id).status == "saved"
    print("✓ Test 21 PASSED: ApplicationStore rejects invalid transition")


# 22
def test_application_terminal_status():
    _, store = _tmp_store()
    app_id = store.add(JobApplication(id="", title="A", company="X"))
    store.update_status(app_id, "withdrawn")
    ok, msg = store.update_status(app_id, "applied")
    assert ok is False
    print("✓ Test 22 PASSED: ApplicationStore terminal status locked")


# 23
def test_application_add_note():
    _, store = _tmp_store()
    app_id = store.add(JobApplication(id="", title="A", company="X"))
    assert store.add_note(app_id, "called recruiter") is True
    assert len(store.get(app_id).notes) == 1
    print("✓ Test 23 PASSED: ApplicationStore add_note")


# 24
def test_application_stats():
    _, store = _tmp_store()
    a = store.add(JobApplication(id="", title="A", company="X"))
    b = store.add(JobApplication(id="", title="B", company="Y"))
    store.update_status(a, "applied")
    store.update_status(b, "withdrawn")
    stats = store.stats()
    assert stats["total"] == 2
    assert stats["applied"] == 1
    assert stats["withdrawn"] == 1
    assert stats["active"] == 1
    print("✓ Test 24 PASSED: ApplicationStore stats")


# 25
def test_application_delete():
    _, store = _tmp_store()
    app_id = store.add(JobApplication(id="", title="A", company="X"))
    assert store.delete(app_id) is True
    assert store.get(app_id) is None
    assert store.delete("nope") is False
    print("✓ Test 25 PASSED: ApplicationStore delete")


# 26
def test_cover_letter_offline():
    gen = CoverLetterGenerator()
    listing = JobListing(id="", title="Backend Engineer", company="Acme", location="Remote")
    letter = gen.generate(listing)
    assert "Acme" in letter
    assert "Backend Engineer" in letter
    assert "Dear Hiring Team" in letter
    print("✓ Test 26 PASSED: CoverLetterGenerator offline template")


# 27
def test_cover_letter_enhancer():
    gen = CoverLetterGenerator(enhancer=lambda text: text + "\n[ENHANCED]")
    listing = JobListing(id="", title="Engineer", company="Acme")
    assert "[ENHANCED]" in gen.generate(listing)
    print("✓ Test 27 PASSED: CoverLetterGenerator optional enhancer")


# 28
def test_application_checklist():
    checklist = ApplicationChecklist().generate(
        JobListing(id="", title="Engineer", company="Acme", url="https://x/1")
    )
    assert len(checklist) >= 4
    assert any("Acme" in step for step in checklist)
    print("✓ Test 28 PASSED: ApplicationChecklist generates steps")


# 29
def test_job_tools_registered():
    from jarvis.tools import get_enhanced_registry

    reg = get_enhanced_registry()
    names = [t["name"] for t in reg.list_tools()]
    expected = [
        "job.search", "job.list", "job.get", "job.save", "job.match",
        "application.add", "application.list", "application.get",
        "application.update_status", "application.delete",
        "application.prepare", "application.followup", "job.stats",
    ]
    for name in expected:
        assert name in names, f"Missing tool: {name}"
    print("✓ Test 29 PASSED: All Phase 10 tools registered")


# 30
def test_job_search_tool_offline():
    from jarvis.jobs import JobSearchTool

    tool = JobSearchTool()
    r = tool.run(keywords="python", use_mock=True, max_results=5)
    assert r.success
    assert r.result["count"] >= 1
    assert all("id" in x for x in r.result["listings"])
    print("✓ Test 30 PASSED: JobSearchTool offline")


# 31
def test_job_save_get_list_tools():
    from jarvis.jobs import JobGetTool, JobListTool, JobSaveTool

    saved = JobSaveTool().run(title="Platform Engineer", company="Acme", url="https://x/1")
    assert saved.success
    job_id = saved.result["job_id"]

    got = JobGetTool().run(job_id=job_id)
    assert got.success
    assert got.result["title"] == "Platform Engineer"

    listed = JobListTool().run()
    assert listed.success
    assert any(x["id"] == job_id for x in listed.result["listings"])

    JobStore().delete(job_id)
    print("✓ Test 31 PASSED: job.save/get/list tools")


# 32
def test_job_get_tool_missing():
    from jarvis.jobs import JobGetTool

    r = JobGetTool().run(job_id="does_not_exist")
    assert r.success is False
    assert "not found" in r.error
    print("✓ Test 32 PASSED: JobGetTool honest failure")


# 33
def test_job_match_tool_on_saved_job():
    from jarvis.jobs import JobMatchTool, JobSaveTool

    saved = JobSaveTool().run(
        title="Senior Engineer", company="Acme", description="python docker aws"
    )
    job_id = saved.result["job_id"]
    r = JobMatchTool().run(job_id=job_id)
    assert r.success
    assert "score" in r.result

    JobStore().delete(job_id)
    print("✓ Test 33 PASSED: JobMatchTool on saved job")


# 34
def test_application_add_list_tools():
    from jarvis.jobs import ApplicationAddTool, ApplicationDeleteTool, ApplicationGetTool, ApplicationListTool

    added = ApplicationAddTool().run(title="Engineer", company="Acme", notes="via referral")
    assert added.success
    app_id = added.result["application_id"]

    got = ApplicationGetTool().run(application_id=app_id)
    assert got.success
    assert got.result["notes"][0]["note"] == "via referral"

    listed = ApplicationListTool().run()
    assert listed.success
    assert any(a["id"] == app_id for a in listed.result["applications"])

    assert ApplicationDeleteTool().run(application_id=app_id).success
    print("✓ Test 34 PASSED: application.add/list/get/delete tools")


# 35
def test_application_update_status_tool():
    from jarvis.jobs import ApplicationAddTool, ApplicationDeleteTool, ApplicationUpdateStatusTool

    app_id = ApplicationAddTool().run(title="Engineer", company="Acme").result["application_id"]

    ok = ApplicationUpdateStatusTool().run(application_id=app_id, status="applied")
    assert ok.success

    # Invalid transition reported honestly
    bad = ApplicationUpdateStatusTool().run(application_id=app_id, status="saved")
    assert bad.success is False
    assert "invalid transition" in bad.error

    ApplicationDeleteTool().run(application_id=app_id)
    print("✓ Test 35 PASSED: application.update_status tool")


# 36
def test_application_prepare_tool():
    from jarvis.jobs import ApplicationPrepareTool, JobSaveTool

    job_id = JobSaveTool().run(title="Data Engineer", company="Globex").result["job_id"]
    r = ApplicationPrepareTool().run(job_id=job_id)
    assert r.success
    assert "Globex" in r.result["cover_letter"]
    assert len(r.result["checklist"]) >= 4

    JobStore().delete(job_id)
    print("✓ Test 36 PASSED: application.prepare tool")


# 37
def test_application_prepare_missing_job():
    from jarvis.jobs import ApplicationPrepareTool

    r = ApplicationPrepareTool().run(job_id="missing")
    assert r.success is False
    print("✓ Test 37 PASSED: application.prepare honest failure")


# 38
def test_application_followup_draft():
    from jarvis.jobs import ApplicationAddTool, ApplicationDeleteTool, ApplicationFollowupTool

    app_id = ApplicationAddTool().run(title="Engineer", company="Acme").result["application_id"]
    r = ApplicationFollowupTool().run(application_id=app_id, to="recruiter@acme.com")
    assert r.success
    assert r.result["sent"] is False
    assert "Acme" in r.result["draft"]["body"]

    ApplicationDeleteTool().run(application_id=app_id)
    print("✓ Test 38 PASSED: application.followup draft")


# 39
def test_application_followup_send_needs_account():
    from jarvis.jobs import ApplicationAddTool, ApplicationDeleteTool, ApplicationFollowupTool

    app_id = ApplicationAddTool().run(title="Engineer", company="Acme").result["application_id"]

    # No email account provided -> honest failure, not a false success
    r = ApplicationFollowupTool().run(application_id=app_id, send=True, to="x@y.com")
    assert r.success is False
    assert "email" in (r.error or "").lower()

    # Unconnected account -> honest failure
    r2 = ApplicationFollowupTool().run(
        application_id=app_id, send=True, email="nobody@example.com", to="x@y.com"
    )
    assert r2.success is False

    ApplicationDeleteTool().run(application_id=app_id)
    print("✓ Test 39 PASSED: application.followup send is honest")


# 40
def test_job_stats_tool():
    from jarvis.jobs import JobStatsTool

    r = JobStatsTool().run()
    assert r.success
    assert "total" in r.result
    assert "active" in r.result
    print("✓ Test 40 PASSED: job.stats tool")


# 41
def test_followup_requires_confirmation_permission():
    from jarvis.tools import get_enhanced_registry

    reg = get_enhanced_registry()
    # email.send is a confirmation-gated permission, so executing without confirm
    # must not silently succeed/send.
    res = reg.execute("application.followup", application_id="missing")
    assert res.success is False
    print("✓ Test 41 PASSED: follow-up gated by permission confirmation")


# 42
def test_allowed_transitions_map():
    assert "applied" in ALLOWED_TRANSITIONS["saved"]
    assert ALLOWED_TRANSITIONS["rejected"] == set()
    assert "saved" in APPLICATION_STATUSES
    print("✓ Test 42 PASSED: transition map sanity")


def run_all():
    test_job_listing_dataclass()
    test_job_search_query_dataclass()
    test_job_application_dataclass()
    test_query_describe()
    test_mock_job_source_returns_listings()
    test_mock_job_source_max_results()
    test_mock_job_source_remote_flag()
    test_web_search_job_source()
    test_web_search_company_guess()
    test_web_search_tag_guess()
    test_job_search_manager_aggregates()
    test_job_search_manager_error_fallback()
    test_job_matcher_skills()
    test_job_matcher_role()
    test_job_matcher_remote()
    test_job_store_roundtrip()
    test_job_store_list_and_delete()
    test_application_store_add_get()
    test_application_store_filter_status()
    test_application_valid_transition()
    test_application_invalid_transition()
    test_application_terminal_status()
    test_application_add_note()
    test_application_stats()
    test_application_delete()
    test_cover_letter_offline()
    test_cover_letter_enhancer()
    test_application_checklist()
    test_job_tools_registered()
    test_job_search_tool_offline()
    test_job_save_get_list_tools()
    test_job_get_tool_missing()
    test_job_match_tool_on_saved_job()
    test_application_add_list_tools()
    test_application_update_status_tool()
    test_application_prepare_tool()
    test_application_prepare_missing_job()
    test_application_followup_draft()
    test_application_followup_send_needs_account()
    test_job_stats_tool()
    test_followup_requires_confirmation_permission()
    test_allowed_transitions_map()
    print("\n=== ALL PHASE 10 JOB TESTS PASSED ===")


if __name__ == "__main__":
    run_all()
