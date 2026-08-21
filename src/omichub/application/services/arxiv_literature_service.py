"""arXiv retrieval for non-biomedical research evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from xml.etree import ElementTree

import httpx


class ArxivLiteratureService:
    """Query arXiv Atom feeds and normalize results to the research evidence shape."""

    ENDPOINT = "https://export.arxiv.org/api/query"
    _ATOM_NAMESPACE = {"atom": "http://www.w3.org/2005/Atom"}

    def __init__(self, *, timeout_seconds: float = 10) -> None:
        self._timeout = max(1.0, min(float(timeout_seconds), 20.0))

    async def search(self, query: str, max_results: int = 8) -> list[dict[str, Any]]:
        normalized_query = " ".join(query.split())
        if not normalized_query:
            return []
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            response = await client.get(
                self.ENDPOINT,
                params={
                    "search_query": f'all:"{normalized_query}"',
                    "start": 0,
                    "max_results": max(1, min(int(max_results), 20)),
                    "sortBy": "relevance",
                    "sortOrder": "descending",
                },
                headers={"User-Agent": "OmicHub research assistant"},
            )
            response.raise_for_status()
        root = ElementTree.fromstring(response.content)
        return [
            item
            for entry in root.findall("atom:entry", self._ATOM_NAMESPACE)
            if (item := self._normalize(entry)) is not None
        ]

    @classmethod
    def _normalize(cls, entry: ElementTree.Element) -> dict[str, Any] | None:
        title = cls._text(entry, "atom:title")
        identifier = cls._text(entry, "atom:id")
        if not title or not identifier:
            return None
        authors = ", ".join(
            name
            for author in entry.findall("atom:author", cls._ATOM_NAMESPACE)
            if (name := cls._text(author, "atom:name"))
        )
        published = cls._text(entry, "atom:published")
        try:
            year = str(datetime.fromisoformat(published.replace("Z", "+00:00")).year)
        except ValueError:
            year = published[:4] if len(published) >= 4 else ""
        summary = cls._text(entry, "atom:summary")
        categories = [
            category.get("term", "")
            for category in entry.findall("atom:category", cls._ATOM_NAMESPACE)
            if category.get("term")
        ]
        return {
            "title": " ".join(title.split()),
            "url": identifier,
            "link": identifier,
            "abstract": " ".join(summary.split()),
            "snippet": " ".join(summary.split())[:1200],
            "claim": " ".join(summary.split())[:1200],
            "authors": authors,
            "publication_year": year,
            "year": year,
            "journal": "arXiv",
            "categories": categories,
            "provider": "arxiv",
            "source": "arXiv",
            "confidence": "high",
        }

    @classmethod
    def _text(cls, element: ElementTree.Element, path: str) -> str:
        return str(element.findtext(path, default="", namespaces=cls._ATOM_NAMESPACE)).strip()
