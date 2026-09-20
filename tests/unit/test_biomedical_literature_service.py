from cygnusx.application.services.biomedical_literature_service import (
    BiomedicalLiteratureService,
)


def test_europe_pmc_result_is_normalized_to_authoritative_locator() -> None:
    item = BiomedicalLiteratureService._normalize({
        "title": "Single-cell transcriptomics of human and mouse lung cancers",
        "pmid": "30979687",
        "pmcid": "PMC6620049",
        "doi": "10.1016/j.immuni.2019.03.009",
        "authorString": "Zilionis R, et al.",
        "journalTitle": "Immunity",
        "pubYear": "2019",
        "abstractText": "Conserved myeloid populations were identified across lung cancers.",
    })

    assert item is not None
    assert item["url"] == "https://pubmed.ncbi.nlm.nih.gov/30979687/"
    assert item["provider"] == "europe_pmc"
    assert "myeloid populations" in item["snippet"]
