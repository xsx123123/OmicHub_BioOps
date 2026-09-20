from __future__ import annotations

import pytest

from cygnusx.infrastructure.mcp.presets import PLATFORM_HANDLERS, PLATFORM_PRESET_TOOLS


def test_europe_pmc_tool_is_registered_as_read_only_platform_tool() -> None:
    tool = next(item for item in PLATFORM_PRESET_TOOLS if item["name"] == "europe_pmc_search")

    assert tool["inputSchema"]["required"] == ["query"]
    assert tool["annotations"]["readOnlyHint"] is True
    assert tool["annotations"]["openWorldHint"] is True
    assert "europe_pmc_search" in PLATFORM_HANDLERS


@pytest.mark.asyncio
async def test_europe_pmc_handler_normalizes_and_reranks(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_search(self: object, query: str, max_results: int, **kwargs: object):
        assert query == "TP53 AND lung cancer"
        assert max_results == 10
        assert kwargs["open_access_only"] is True
        return [
            {
                "title": "TP53 immune tolerance in lung cancer",
                "abstract": "Macrophage and T cell interactions.",
                "url": "https://pubmed.ncbi.nlm.nih.gov/1/",
                "provider": "europe_pmc",
            }
        ]

    monkeypatch.setattr(
        "cygnusx.application.services.biomedical_literature_service.BiomedicalLiteratureService.search",
        fake_search,
    )
    result = await PLATFORM_HANDLERS["europe_pmc_search"](
        {
            "query": "TP53 AND lung cancer",
            "max_results": 5,
            "open_access_only": True,
        }
    )

    assert result["success"] is True
    assert result["result"]["provider"] == "Europe PMC"
    assert result["result"]["result_count"] == 1
