"""Biomedical literature retrieval for research-first planning."""

from __future__ import annotations

from typing import Any

import httpx


class BiomedicalLiteratureService:
    """Query Europe PMC and normalize results for the planning evidence ledger."""

    ENDPOINT = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    def __init__(self, *, timeout_seconds: float = 10) -> None:
        self._timeout = max(1.0, min(float(timeout_seconds), 20.0))

    async def search(
        self,
        query: str,
        max_results: int = 8,
        *,
        year_from: int | None = None,
        year_to: int | None = None,
        open_access_only: bool = False,
    ) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        clauses = [f"({query.strip()})"]
        if year_from is not None or year_to is not None:
            lower = int(year_from or 1800)
            upper = int(year_to or 2100)
            clauses.append(f"FIRST_PDATE:[{min(lower, upper)} TO {max(lower, upper)}]")
        if open_access_only:
            clauses.append("OPEN_ACCESS:Y")
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            response = await client.get(
                self.ENDPOINT,
                params={
                    "query": " AND ".join(clauses),
                    "format": "json",
                    "pageSize": max(1, min(int(max_results), 20)),
                    "resultType": "core",
                },
                headers={"User-Agent": "CygnusX research planner"},
            )
            response.raise_for_status()
        results = response.json().get("resultList", {}).get("result", [])
        return [item for raw in results if (item := self._normalize(raw)) is not None]

    @staticmethod
    def _normalize(raw: dict[str, Any]) -> dict[str, Any] | None:
        title = str(raw.get("title") or "").strip()
        pmid = str(raw.get("pmid") or "").strip()
        pmcid = str(raw.get("pmcid") or "").strip()
        doi = str(raw.get("doi") or "").strip()
        if not title or not (pmid or pmcid or doi):
            return None
        if pmid:
            url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        elif pmcid:
            url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
        else:
            url = f"https://doi.org/{doi}"
        abstract = str(raw.get("abstractText") or "").strip()
        bibliographic = " · ".join(
            value
            for value in (
                str(raw.get("authorString") or "").strip(),
                str(raw.get("journalTitle") or "").strip(),
                str(raw.get("pubYear") or "").strip(),
            )
            if value
        )
        return {
            "title": title,
            "url": url,
            "link": url,
            "abstract": abstract,
            "snippet": abstract[:1200] or bibliographic,
            "claim": abstract[:1200] or bibliographic,
            "authors": str(raw.get("authorString") or "").strip(),
            "journal": str(raw.get("journalTitle") or "").strip(),
            "publication_year": str(raw.get("pubYear") or "").strip(),
            "year": str(raw.get("pubYear") or "").strip(),
            "publication_type": str(raw.get("pubType") or "").strip(),
            "is_open_access": str(raw.get("isOpenAccess") or "").upper() == "Y",
            "cited_by_count": int(raw.get("citedByCount") or 0),
            "pmid": pmid,
            "pmcid": pmcid,
            "doi": doi,
            "provider": "europe_pmc",
            "source": "Europe PMC",
            "confidence": "high",
        }
