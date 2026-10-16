"""Web search and research module for Jarvis."""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from .logging import get_logger

logger = get_logger(__name__)


@dataclass
class SearchResult:
    """A single search result."""
    title: str
    url: str
    snippet: str
    source: str
    published_date: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResponse:
    """Response from a search provider."""
    query: str
    results: List[SearchResult]
    provider: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    error: Optional[str] = None


class SearchProvider(ABC):
    """Abstract base class for search providers."""

    def __init__(self, timeout: int = 10, max_results: int = 10):
        self.timeout = timeout
        self.max_results = max_results

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier."""
        pass

    @abstractmethod
    def search(self, query: str, max_results: Optional[int] = None) -> "SearchResponse":
        """Execute a search query and return results."""
        pass


class MockSearchProvider:
    """Mock search provider for testing (deterministic results)."""

    @property
    def name(self) -> str:
        return "mock"

    def search(self, query: str, max_results: Optional[int] = None) -> "SearchResponse":
        """Return deterministic mock results for testing."""
        mock_results = [
            {
                "title": f"Result 1 for {query}",
                "url": "https://example.com/mock/result1",
                "snippet": f"This is a mock result for query: {query}",
            },
            {
                "title": f"Result 2 for {query}",
                "url": "https://example.com/mock/result2",
                "snippet": f"Another mock result for: {query}",
            },
            {
                "title": f"Official Documentation for {query}",
                "url": "https://docs.example.com/mock/docs",
                "snippet": f"Official docs and guides for {query}",
            },
        ]
        results = []
        for item in mock_results[:max_results or 10]:
            results.append(SearchResult(
                title=item["title"],
                url=item["url"],
                snippet=item["snippet"],
                source="mock",
                metadata={"is_mock": True},
            ))
        return SearchResponse(
            query=query,
            results=results,
            provider="mock",
        )


class SearchProviderBase:
    """Base class for search providers with common functionality."""

    def __init__(self, timeout: int = 10, max_results: int = 10):
        self.timeout = timeout
        self.max_results = max_results

    @property
    def name(self) -> str:
        return "base"

    def search(self, query: str, max_results: Optional[int] = None) -> "SearchResponse":
        """Base search method - to be overridden."""
        return SearchResponse(
            query=query,
            results=[],
            provider=self.name,
            error="Not implemented",
        )


class SearchManager:
    """Manages multiple search providers and executes searches."""

    def __init__(self, use_mock: bool = False):
        self.providers: List = []
        self._init_providers(use_mock)

    def _init_providers(self, use_mock: bool = False):
        """Initialize available search providers."""
        if use_mock:
            self.providers.append(MockSearchProvider())
        else:
            # Real providers would be initialized here
            # For now, add mock for testing
            self.providers.append(MockSearchProvider())

    def search(self, query: str, max_results: int = 10) -> "SearchResponse":
        """Search using the first available provider."""
        if not self.providers:
            return SearchResponse(
                query=query,
                results=[],
                provider="none",
                error="No search providers available",
            )

        # Try providers in order until one succeeds
        for provider in self.providers:
            try:
                response = provider.search(query, max_results=max_results)
                if response.results:
                    return response
                if response.error:
                    logger.warning(f"Provider {provider.name} error: {response.error}")
            except Exception as e:
                logger.warning(f"Provider {provider.name} failed: {e}")

        return SearchResponse(
            query=query,
            results=[],
            provider="none",
            error="All search providers failed",
        )

    def multi_search(self, queries: List[str], max_results: int = 10) -> List["SearchResponse"]:
        """Execute multiple search queries."""
        return [self.search(q, max_results) for q in queries]


@dataclass
class ResearchJob:
    """A research job tracking state."""
    question: str
    sub_queries: List[str] = field(default_factory=list)
    search_results: List["SearchResponse"] = field(default_factory=list)
    fetched_pages: List[Dict] = field(default_factory=list)
    evidence: List[Dict] = field(default_factory=list)
    report: str = ""
    status: str = "pending"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    error: Optional[str] = None


class ResearchPipeline:
    """End-to-end research pipeline."""

    def __init__(self, search_manager: Optional[SearchManager] = None, use_mock: bool = False):
        self.search_manager = search_manager or SearchManager(use_mock=use_mock)
        self.max_sub_queries = 5
        self.max_results_per_query = 10
        self.max_pages_to_fetch = 5
        self.page_timeout = 15

    def research(self, question: str) -> ResearchJob:
        """Execute full research pipeline."""
        job = ResearchJob(question=question)

        # Step 1: Generate sub-queries
        job.sub_queries = self._generate_sub_queries(question)
        job.updated_at = datetime.utcnow().isoformat()

        # Step 2: Execute searches
        job.search_results = self.search_manager.multi_search(
            job.sub_queries,
            max_results=self.max_results_per_query,
        )
        job.updated_at = datetime.utcnow().isoformat()

        # Step 3: Fetch and extract content from top results
        job.fetched_pages = self._fetch_top_pages(job.search_results)
        job.updated_at = datetime.utcnow().isoformat()

        # Step 4: Extract evidence
        job.evidence = self._extract_evidence(job.fetched_pages, question)
        job.updated_at = datetime.utcnow().isoformat()

        # Step 5: Generate report
        job.report = self._generate_report(job)
        job.status = "completed"
        job.updated_at = datetime.utcnow().isoformat()

        return job

    def _generate_sub_queries(self, question: str) -> List[str]:
        """Generate focused search sub-queries from the research question."""
        base_queries = [question]

        # Add specific search modifiers for better results
        modifiers = [
            "official documentation",
            "tutorial",
            "guide",
            "comparison",
            "review",
            "best practices",
        ]

        for mod in modifiers[:3]:  # Limit to avoid too many queries
            base_queries.append(f"{question} {mod}")

        return base_queries[:self.max_sub_queries]

    def _fetch_top_pages(self, search_results: List["SearchResponse"]) -> List[Dict]:
        """Fetch and extract content from top search results."""
        pages = []
        fetched = 0

        for response in search_results:
            for result in response.results:
                if fetched >= self.max_pages_to_fetch:
                    break

                # Skip mock results - they have fake URLs
                if result.metadata.get("is_mock"):
                    # For mock results, use the snippet as content directly
                    pages.append({
                        "url": result.url,
                        "title": result.title,
                        "snippet": result.snippet,
                        "content": result.snippet,
                        "source": result.source,
                        "fetched_at": datetime.utcnow().isoformat(),
                    })
                    fetched += 1
                    continue

                try:
                    content = self._fetch_page(result.url)
                    if content:
                        pages.append({
                            "url": result.url,
                            "title": result.title,
                            "snippet": result.snippet,
                            "content": content,
                            "source": result.source,
                            "fetched_at": datetime.utcnow().isoformat(),
                        })
                        fetched += 1
                except Exception as e:
                    logger.warning(f"Failed to fetch {result.url}: {e}")

        return pages

    def _fetch_page(self, url: str) -> Optional[str]:
        """Fetch and extract text content from a URL."""
        try:
            # Validate URL for safety
            if not self._is_safe_url(url):
                return None

            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Jarvis/1.0 Research Bot"}
            )
            with urllib.request.urlopen(req, timeout=self.page_timeout) as response:
                content_type = response.headers.get("Content-Type", "")
                if "text/html" not in content_type and "text/" not in content_type:
                    return None

                html = response.read().decode("utf-8", errors="replace")
                return self._extract_text(html)
        except Exception as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            return None

    def _is_safe_url(self, url: str) -> bool:
        """Check if URL is safe to fetch."""
        try:
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return False

            hostname = parsed.hostname or ""
            if hostname in ("localhost", "127.0.0.1", "0.0.0.0"):
                return False

            if hostname.startswith("10.") or hostname.startswith("192.168.") or hostname.startswith("172."):
                return False

            if "metadata.google.internal" in hostname or "169.254.169.254" in hostname:
                return False

            return True
        except Exception:
            return False

    def _extract_text(self, html: str) -> str:
        """Extract readable text from HTML."""
        parser = TextExtractor()
        parser.feed(html)
        text = parser.get_text()

        max_len = 10000
        if len(text) > max_len:
            text = text[:max_len] + "... [truncated]"
        return text

    def _extract_evidence(self, pages: List[Dict], question: str) -> List[Dict]:
        """Extract relevant evidence from fetched pages."""
        evidence = []
        for page in pages:
            if not page.get("content"):
                continue

            question_words = set(question.lower().split())
            content_words = set(page["content"].lower().split())
            overlap = len(question_words & content_words)

            if overlap > 0:
                evidence.append({
                    "url": page["url"],
                    "title": page["title"],
                    "source": page["source"],
                    "snippet": page["snippet"],
                    "excerpt": page["content"][:500],
                    "relevance_score": overlap,
                })

        evidence.sort(key=lambda x: x["relevance_score"], reverse=True)
        return evidence[:10]

    def _generate_report(self, job: ResearchJob) -> str:
        """Generate a research report from evidence."""
        if not job.evidence:
            return f"Research Question: {job.question}\n\nNo relevant evidence found."

        lines = [
            f"# Research Report: {job.question}",
            "",
            f"*Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC*",
            "",
            "## Summary",
            "",
            f"Researched {len(job.sub_queries)} sub-queries, found {len(job.evidence)} relevant sources.",
            "",
            "## Key Findings",
            "",
        ]

        for i, evidence in enumerate(job.evidence, 1):
            lines.extend([
                f"### {i}. {evidence['title']}",
                f"**Source:** {evidence['source']} | **URL:** {evidence['url']}",
                f"**Relevance:** {evidence['relevance_score']} keyword matches",
                "",
                evidence["excerpt"],
                "",
            ])

        lines.extend([
            "## Sources",
            "",
        ])

        for i, evidence in enumerate(job.evidence, 1):
            lines.append(f"{i}. [{evidence['title']}]({evidence['url']}) - {evidence['source']}")

        lines.extend([
            "",
            "## Limitations",
            "- Results based on search engine snippets and page content extraction",
            "- Publication dates may not be available for all sources",
            "- Some sources may be outdated or conflicting",
            "- Full page content may not be accessible due to restrictions",
        ])

        return "\n".join(lines)


class TextExtractor(HTMLParser):
    """Extract readable text from HTML."""

    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.ignore = False
        self.ignore_tags = {"script", "style", "noscript", "iframe", "svg"}

    def handle_starttag(self, tag, attrs):
        if tag in self.ignore_tags:
            self.ignore = True

    def handle_endtag(self, tag):
        if tag in self.ignore_tags:
            self.ignore = False

    def handle_data(self, data):
        if not self.ignore and data.strip():
            self.text_parts.append(data.strip())

    def get_text(self) -> str:
        return " ".join(self.text_parts)


# Convenience function for easy use
def research(question: str, max_results: int = 10, use_mock: bool = False) -> str:
    """Quick research function."""
    pipeline = ResearchPipeline(SearchManager(use_mock=use_mock))
    job = pipeline.research(question)
    return job.report
