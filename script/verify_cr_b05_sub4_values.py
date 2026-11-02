"""Independent standard-library checks of the two authorized real result chains.

Run once in the final isolated image with materials and delivery mounted read-only.
This checks the selected real outputs; it does not rerun any previous subpackage.
"""
import argparse
from collections import Counter
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import shlex


def table(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream, delimiter='\t'))


def close(actual, expected):
    if not math.isclose(float(actual), expected, rel_tol=1e-6, abs_tol=1e-8):
        raise AssertionError((actual, expected))


def features(materials, delivery):
    rows = table(delivery / 'sequence-structure-features/feature_results.tsv')
    assert len(rows) == 3
    by_kind = {row['feature_kind']: row for row in rows}
    for kind, filename in [('rna', 'UBB_NM_018955.4.fasta'), ('protein', 'UBB_NP_061828.1.fasta')]:
        raw = (materials / filename).read_bytes()
        lines = raw.decode('utf-8').splitlines()
        assert len([line for line in lines if line.startswith('>')]) == 1
        sequence = ''.join(lines[1:])
        row = by_kind[kind]
        assert row['input_sha256'] == hashlib.sha256(raw).hexdigest()
        assert row['original_id'] == lines[0][1:].split()[0]
        assert int(row['length']) == len(sequence)
        counts = Counter(sequence)
        if kind == 'rna':
            assert set(sequence) <= set('ACGT') and row['nucleotide_encoding'] == 'T'
            assert len(sequence) == 933 and counts['T'] == 204 and counts['U'] == 0
            assert int(row['valid_count']) == len(sequence) and int(row['ambiguous_count']) == 0
            close(row['gc_fraction'], (counts['C'] + counts['G']) / len(sequence))
            for base in 'ACGT':
                assert int(row['base_counts_' + base]) == counts[base]
            assert row['selected'].lower() == 'false'
        else:
            assert set(sequence) <= set('ACDEFGHIKLMNPQRSTVWY') and len(sequence) == 229
            assert int(row['standard_count']) == 229 and int(row['stop_count']) == 0
            for residue in 'ACDEFGHIKLMNPQRSTVWY':
                assert int(row['amino_acid_counts_' + residue]) == counts[residue]
                close(row['composition_' + residue], counts[residue] / 229)
            assert row['selected'].lower() == 'true'
    raw = (materials / 'pdb_00001ubq_xyz_v1-3.cif.gz').read_bytes()
    lines = gzip.decompress(raw).decode('utf-8').splitlines()
    start = next(index for index, line in enumerate(lines) if line.strip().startswith('_atom_site.'))
    columns = []
    while lines[start].strip().startswith('_atom_site.'):
        columns.append(lines[start].strip().split()[0].removeprefix('_atom_site.'))
        start += 1
    atoms = []
    for line in lines[start:]:
        if line.strip() == '#':
            break
        values = shlex.split(line)
        assert len(values) == len(columns)
        atoms.append(dict(zip(columns, values)))
    assert len(atoms) == 660
    selected = [atom for atom in atoms if atom['pdbx_PDB_model_num'] == '1' and atom['auth_asym_id'] == 'A'
        and atom['group_PDB'] == 'ATOM' and atom['auth_atom_id'] == 'CA']
    assert len(selected) == 76 and all(atom['label_alt_id'] in ('.', '?') for atom in selected)
    # The fixed original has partial occupancies in residues 73-76. They are
    # valid observed CA coordinates; the declared geometry remains equal-weight.
    assert {atom['auth_seq_id']: float(atom['occupancy']) for atom in selected} == {
        str(residue): .45 if residue in (73, 74) else .25 if residue in (75, 76) else 1.0
        for residue in range(1, 77)
    }
    xyz = [[float(atom['Cartn_' + axis]) for axis in 'xyz'] for atom in selected]
    centroid = [math.fsum(point[axis] for point in xyz) / 76 for axis in range(3)]
    radius = math.sqrt(math.fsum(math.fsum((point[axis] - centroid[axis]) ** 2 for axis in range(3)) for point in xyz) / 76)
    row = by_kind['structure']
    assert row['input_sha256'] == hashlib.sha256(raw).hexdigest()
    assert int(row['observed_residue_count']) == 76 and int(row['ca_count']) == 76
    assert int(row['atom_count']) == 602 and int(row['water_atom_count']) == 58
    for axis, expected in zip('xyz', centroid):
        close(row['centroid_' + axis], expected)
    close(row['radius_of_gyration'], radius)
    assert row['selected'].lower() == 'true'
    return dict(rna_length=933, protein_precursor_length=229, observed_structure_residues=76,
        structure_atoms=660, ca_count=76, ca_occupancies=dict(Counter(float(atom['occupancy']) for atom in selected)),
        centroid_angstrom=centroid, ca_radius_of_gyration_angstrom=radius,
        formula='independent standard-library equal-weight sums; no production parser/kernel imports')


def integration(materials, delivery):
    left = {row['observation_id']: row for row in table(materials / 'derived/mrna-training-source.tsv')}
    right = {row['observation_id']: row for row in table(materials / 'derived/protein-training-source.tsv')}
    declared = json.loads((materials / 'derived/candidate-pairs-frozen.json').read_bytes())
    pairs = declared['pairs']
    assert len(pairs) == 1 and pairs[0]['pair_id'] == 'STAT5A__STAT5-alpha'
    matching = json.loads((materials / 'derived/sample-correspondence-frozen.json').read_bytes())
    assert len(matching) == 150 and len(left) == len(right) == 150
    points = {row['sample_pair_id']: (float(left[row['mrna_observation_id']]['STAT5A']),
        float(right[row['protein_observation_id']]['STAT5-alpha'])) for row in matching}
    mx = math.fsum(point[0] for point in points.values()) / 150
    my = math.fsum(point[1] for point in points.values()) / 150
    numerator = math.fsum((x - mx) * (y - my) for x, y in points.values())
    denominator = math.sqrt(math.fsum((x - mx) ** 2 for x, _ in points.values()) * math.fsum((y - my) ** 2 for _, y in points.values()))
    expected = numerator / denominator
    data = json.loads((delivery / 'matched-omics-integration/integration_data.json').read_bytes())
    assert len(data['correlations']) == 1
    result = data['correlations'][0]
    assert result['pair_id'] == pairs[0]['pair_id'] and result['matched_observation_count'] == 150
    assert result['independent_n'] is None and result['p_value'] is None and result['q_value'] is None
    assert result['reason'] == 'descriptive_independent_units_unverified'
    close(result['coefficient'], expected)
    rows = data['input_rows']
    assert len(rows) == 150 and {row['match_group'] for row in rows} == set(points)
    for row in rows:
        assert row['included'] is True and row['donor_id'] is None
        assert (row['left_value'], row['right_value']) == points[row['match_group']]
    edges = [edge for edge in data['edges'] if edge['edge_type'] == 'correlation']
    assert len(edges) == 1 and edges[0]['directed'] is False
    close(edges[0]['weight'], expected)
    return dict(pair_id=pairs[0]['pair_id'], matched_observations=150, independent_donors=None,
        descriptive_pearson=expected, p_value=None, bh=None,
        formula='independent centered cross-product and sums of squares; no production correlation imports')


def evidence(delivery):
    data = json.loads((delivery / 'matched-omics-evidence/evidence_data.json').read_bytes())
    rows = data['matrix']
    assert len(rows) == 6 and len(data['dependency_groups']) == 2
    assert {row['feature_id'] for row in rows} == {'ERBB2', 'STAT5A'}
    assert all(row['independent_data_support'] is False and row['system_verified'] is False for row in rows)
    assert all(row['human_review_status'] == 'not_reviewed' and row['locator_verified'] is True for row in rows)
    selected = {row['evidence_type']: row for row in rows if row['feature_id'] == 'ERBB2'}
    assert set(selected) == {'disease_literature', 'mutation_literature', 'expression_atlas'}
    assert all(row['status'] == 'context' and row['biological_claim_status'] == 'source_reported' for row in selected.values())
    assert sum(len(row['locators']) for row in selected.values()) == 15
    assert selected['disease_literature']['source_group'] == selected['mutation_literature']['source_group']
    assert selected['expression_atlas']['source_group'] != selected['disease_literature']['source_group']
    assert all(row['status'] == 'missing' and row['source_statement'] is None for row in rows if row['feature_id'] == 'STAT5A')
    candidates = {row['feature_id']: row for row in data['candidates']}
    assert candidates['ERBB2']['original_feature_id'] == 'HER2'
    assert candidates['STAT5A']['missing_count'] == 3
    assert all(row['reference_version'] == 'unknown' and row['reference_verified'] is False
        and row['score'] is None and row['independent_support_count'] == 0 for row in candidates.values())
    integrated = json.loads((delivery / 'matched-omics-integration/integration_data.json').read_bytes())
    assert len(data['integration_results']) == 1 and data['integration_results'][0]['data'] == integrated
    return dict(candidate_count=2, evidence_count=3, full_cross_product_rows=6, dependency_groups=2,
        original_locator_matches=15, context_rows=3, missing_rows=3, independent_support=0,
        real_knockout_records=0, saved_integration_data_reused_exactly=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('materials', type=Path)
    parser.add_argument('delivery', type=Path)
    args = parser.parse_args()
    print(json.dumps(dict(status='passed', features=features(args.materials, args.delivery),
        integration=integration(args.materials, args.delivery), evidence=evidence(args.delivery), atol=1e-8, rtol=1e-6), ensure_ascii=False))
