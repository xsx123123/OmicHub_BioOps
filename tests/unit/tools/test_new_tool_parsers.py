from cygnusx.tools.gsea.service import GseaService
from cygnusx.tools.synteny.service import SyntenyService


def test_gsea_example_ranking_parser() -> None:
    rows = GseaService._parse_ranking("gene_id\tscore\nTP53\t2.4\nBRCA1\t-1.2")
    assert rows == [("TP53", 2.4), ("BRCA1", -1.2)]


def test_synteny_example_parser_extracts_gene_coordinates_and_pairs() -> None:
    genes = SyntenyService._parse_gff3(
        "##gff-version 3\nchr1\tx\tgene\t1\t5\t.\t+\t.\tID=a\nchr2\tx\tgene\t2\t8\t.\t+\t.\tID=b\n"
    )
    pairs = SyntenyService._parse_blast("a\tb\t99\t5\t0\t0\t1\t5\t1\t5\t1e-10\t20")
    assert genes["a"] == ("chr1", 1, 5)
    assert pairs == [("a", "b")]
