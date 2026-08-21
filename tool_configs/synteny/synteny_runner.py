#!/usr/bin/env python3
"""Small MCScanX-style anchor/block parser used by the isolated synteny image."""
from __future__ import annotations
import argparse, json
from collections import defaultdict


def parse_gff(path: str) -> dict[str, tuple[str, int]]:
    genes = {}
    for line in open(path, encoding='utf-8'):
        if not line.strip() or line.startswith('#'): continue
        fields = line.rstrip('\n').split('\t')
        if len(fields) < 9 or fields[2].lower() not in {'gene', 'mrna'}: continue
        attrs = dict(part.split('=', 1) for part in fields[8].split(';') if '=' in part)
        gene_id = attrs.get('ID') or attrs.get('Parent')
        if gene_id: genes[gene_id] = (fields[0], int(fields[3]))
    return genes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--gff3', required=True)
    parser.add_argument('--blastp', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    genes = parse_gff(args.gff3)
    grouped: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    points = []
    for line in open(args.blastp, encoding='utf-8'):
        fields = line.rstrip('\n').split('\t')
        if len(fields) >= 2 and fields[0] in genes and fields[1] in genes:
            query, subject = fields[0], fields[1]
            grouped[(genes[query][0], genes[subject][0])].add((query, subject))
            points.append({'query_gene': query, 'subject_gene': subject, 'chromosome_a': genes[query][0], 'chromosome_b': genes[subject][0], 'x': genes[query][1], 'y': genes[subject][1]})
    blocks = [
        {'block_id': f'block-{index}', 'chromosome_a': pair[0], 'chromosome_b': pair[1], 'gene_pairs': len(anchor_pairs)}
        for index, (pair, anchor_pairs) in enumerate(sorted(grouped.items()), 1)
    ]
    with open(args.output, 'w', encoding='utf-8') as handle:
        json.dump({'blocks': blocks, 'points': points, 'chromosome_pairs': [f'{a} ↔ {b}' for a, b in sorted(grouped)]}, handle, ensure_ascii=False)


if __name__ == '__main__':
    main()
