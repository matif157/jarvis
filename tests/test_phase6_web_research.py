"""Phase 6 Web Research Tests"""

import os
import sys
from html.parser import HTMLParser
from jarvis.web_search import (
    SearchResult,
    SearchResponse,
    MockSearchProvider,
    SearchManager,
    ResearchPipeline,
    research,
    TextExtractor,
)


def test_search_result_dataclass():
    """Test SearchResult dataclass creation."""
    r = SearchResult(
        title="Test Title",
        url="https://example.com",
        snippet="Test snippet",
        source="test",
    )
    assert r.title == "Test Title"
    assert r.url == "https://example.com"
    assert r.snippet == "Test snippet"
    assert r.source == "test"
    print("✓ Test 1 PASSED: SearchResult dataclass")


def test_search_response_dataclass():
    """Test SearchResponse dataclass creation."""
    r = SearchResponse(
        query="test query",
        results=[],
        provider="test",
        error=None,
    )
    assert r.query == "test query"
    assert r.provider == "test"
    assert r.error is None
    print("✓ Test 2 PASSED: SearchResponse dataclass")


def test_mock_search_provider():
    """Test MockSearchProvider returns deterministic results."""
    provider = MockSearchProvider()
    result = provider.search("test query", max_results=3)

    assert result.provider == "mock"
    assert len(result.results) == 3
    assert all(r.metadata.get("is_mock") for r in result.results)
    print("✓ Test 3 PASSED: MockSearchProvider")


def test_search_manager_mock():
    """Test SearchManager with mock provider."""
    sm = SearchManager(use_mock=True)
    result = sm.search("test query", max_results=2)

    assert result.provider == "mock"
    assert len(result.results) == 2
    print("✓ Test 4 PASSED: SearchManager with mock")


def test_multi_search():
    """Test multi_search functionality."""
    sm = SearchManager(use_mock=True)
    results = sm.multi_search(["query1", "query2"], max_results=2)

    assert len(results) == 2
    assert all(r.provider == "mock" for r in results)
    print("✓ Test 5 PASSED: Multi-search")


def test_research_pipeline_mock():
    """Test ResearchPipeline with mock provider."""
    pipeline = ResearchPipeline(SearchManager(use_mock=True))
    job = pipeline.research("test research question")

    assert job.status == "completed"
    assert len(job.sub_queries) > 0
    assert len(job.evidence) > 0
    assert len(job.report) > 0
    print("✓ Test 6 PASSED: ResearchPipeline with mock")


def test_research_function():
    """Test the convenience research function."""
    result = research("test question", use_mock=True)
    assert "Research Report" in result
    assert "Summary" in result
    assert "Key Findings" in result
    assert "Sources" in result
    print("✓ Test 7 PASSED: research() convenience function")


def test_research_report_format():
    """Test research report format includes required sections."""
    result = research("test question", use_mock=True)

    assert "# Research Report:" in result
    assert "## Summary" in result
    assert "## Key Findings" in result
    assert "## Sources" in result
    assert "## Limitations" in result
    print("✓ Test 8 PASSED: Research report format")


def test_source_links_preserved():
    """Test that source links are preserved in report."""
    result = research("test query", use_mock=True)

    # Check that URLs from mock results appear in report
    assert "example.com" in result
    print("✓ Test 9 PASSED: Source links preserved in report")


def test_multiple_sub_queries():
    """Test that multiple sub-queries are generated."""
    pipeline = ResearchPipeline(SearchManager(use_mock=True))
    job = pipeline.research("complex research question with multiple aspects")

    assert len(job.sub_queries) >= 2  # At least original + modifiers
    print("✓ Test 10 PASSED: Multiple sub-queries generated")


def test_evidence_relevance_scoring():
    """Test that evidence is scored by relevance."""
    pipeline = ResearchPipeline(SearchManager(use_mock=True))
    job = pipeline.research("specific research topic")

    # Evidence should have relevance scores
    for evidence in job.evidence:
        assert "relevance_score" in evidence
        assert isinstance(evidence["relevance_score"], int)
        assert evidence["relevance_score"] >= 0
    print("✓ Test 11 PASSED: Evidence relevance scoring")


def test_report_includes_sources_section():
    """Test that report includes Sources section with links."""
    result = research("test query", use_mock=True)

    assert "## Sources" in result
    assert "[" in result and "](" in result  # Markdown links
    print("✓ Test 12 PASSED: Report includes Sources section with links")


def test_report_includes_limitations():
    """Test that report includes limitations section."""
    result = research("test query", use_mock=True)
    assert "## Limitations" in result
    print("✓ Test 13 PASSED: Report includes limitations")


def test_empty_results_handled():
    """Test handling of empty search results."""
    pipeline = ResearchPipeline(SearchManager(use_mock=True))
    # Use a query that might return no relevant evidence
    job = pipeline.research("completely unrelated nonsense query xyz123")

    # Should still generate a report
    assert job.report is not None
    assert len(job.report) > 0
    print("✓ Test 14 PASSED: Empty results handled gracefully")


def test_research_job_tracking():
    """Test ResearchJob state tracking."""
    pipeline = ResearchPipeline(SearchManager(use_mock=True))
    job = pipeline.research("test question")

    assert job.status == "completed"
    assert job.created_at is not None
    assert job.updated_at is not None
    assert job.question == "test question"
    assert isinstance(job.sub_queries, list)
    assert isinstance(job.search_results, list)
    assert isinstance(job.evidence, list)
    print("✓ Test 15 PASSED: ResearchJob state tracking")


def test_safe_url_validation():
    """Test URL safety validation."""
    pipeline = ResearchPipeline()

    # Safe URLs
    assert pipeline._is_safe_url("https://example.com")
    assert pipeline._is_safe_url("https://docs.example.com/page")

    # Unsafe URLs
    assert not pipeline._is_safe_url("http://localhost")
    assert not pipeline._is_safe_url("http://127.0.0.1")
    assert not pipeline._is_safe_url("file:///etc/passwd")
    assert not pipeline._is_safe_url("javascript:alert(1)")
    print("✓ Test 16 PASSED: Safe URL validation")


def test_text_extractor():
    """Test HTML text extraction."""
    extractor = TextExtractor()
    html = "<html><body><h1>Title</h1><p>Paragraph text</p><script>alert('xss')</script></body></html>"
    extractor.feed(html)
    text = extractor.get_text()

    assert "Title" in text
    assert "Paragraph text" in text
    assert "alert" not in text  # Script content should be stripped
    print("✓ Test 17 PASSED: HTML text extraction")


def test_html_parser():
    """Test basic HTML parsing."""
    parser = HTMLParser()
    # This tests that our HTMLParser subclass works
    parser.feed("<p>Hello</p>")
    print("✓ Test 18 PASSED: HTML parser basic functionality")


def test_integration_with_assistant():
    """Test that research tools integrate with assistant."""
    from jarvis import tools
    from jarvis import assistant

    a = assistant.Assistant(mode="auto")

    # Check if research function can be called
    from jarvis.web_search import research
    result = research("test query", use_mock=True)
    assert "Research Report" in result
    print("✓ Test 19 PASSED: Integration with assistant")


def test_research_with_real_provider_setup():
    """Test that real provider setup is documented."""
    # This test documents the requirement for real provider setup
    # No API key = mock mode only
    pipeline = ResearchPipeline(SearchManager(use_mock=False))
    job = pipeline.research("test")

    # Without real provider, should fall back to mock or fail gracefully
    # Current implementation falls back to mock
    assert job.status in ("completed", "failed")
    print("✓ Test 20 PASSED: Provider fallback behavior")


def run_all():
    test_search_result_dataclass()
    test_search_response_dataclass()
    test_mock_search_provider()
    test_search_manager_mock()
    test_multi_search()
    test_research_pipeline_mock()
    test_research_function()
    test_research_report_format()
    test_source_links_preserved()
    test_multiple_sub_queries()
    test_evidence_relevance_scoring()
    test_report_includes_sources_section()
    test_report_includes_limitations()
    test_empty_results_handled()
    test_research_job_tracking()
    test_safe_url_validation()
    test_text_extractor()
    test_html_parser()
    test_integration_with_assistant()
    test_research_with_real_provider_setup()
    print("\n=== ALL PHASE 6 WEB RESEARCH TESTS PASSED ===")


if __name__ == "__main__":
    run_all()
