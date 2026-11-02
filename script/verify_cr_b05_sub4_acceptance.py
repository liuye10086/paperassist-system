"""Resumable subpackage-four tasks; reuse saved responses and frozen inputs."""
import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
os.environ['PAPERASSIST_CR_B05_SUBPACKAGE'] = '4'
sys.path[:0] = [str(ROOT / 'script'), str(ROOT / 'script/dev'), str(ROOT / 'backend')]
import cr_b05_runner as control
from cr_b04_downstream import Ledger
from verify_cr_b05_acceptance import Acceptance as PreviousAcceptance
from verify_cr_b04_acceptance import Acceptance as ResourceAcceptance
from verify_cr_b05_sub3_acceptance import Acceptance as TabularAcceptance
# The previous script declares its own CLI default during import. Our already
# loaded control module and every child process remain explicitly subpackage 4.
os.environ['PAPERASSIST_CR_B05_SUBPACKAGE'] = '4'


class Acceptance(PreviousAcceptance):
    upload_resource = ResourceAcceptance.upload
    import_source = TabularAcceptance.import_source
    process_raw = TabularAcceptance.process_raw

    def __init__(self):
        import httpx
        self.state = control.read_state()
        control.configure(self.state)
        self.output = control.RUNTIME / 'acceptance'
        self.output.mkdir(exist_ok=True)
        self.ledger = Ledger(self.output / 'receipt.json', dict(schema=self.state['schema'], batch='CR-B05', subpackage=4))
        self.record = self.ledger.record
        self.client = httpx.Client(base_url=self.state['url'], timeout=httpx.Timeout(1200, connect=30), trust_env=False,
            headers={'Origin': self.state['url'], 'X-PaperAssist-Client': 'web'})
        credential = json.loads((Path(self.state['assets']).parent / 'credentials.json').read_text(encoding='utf-8-sig'))['review']
        response = self.check(self.client.post('/api/v1/auth/login', json={key: credential[key] for key in ('email', 'password')}))
        self.client.headers['X-CSRF-Token'] = response.json()['csrf_token']
        self.owner = credential['id']

    def resource(self, label, project, config):
        value = self.post(label + '-resource', self.base(project) + '/bio-resources', config, project, 'resource')
        self.wait(value['task_id'])
        value = self.get(self.base(project) + '/bio-resources/' + value['id'])
        self.record.setdefault('resources', {})[label] = dict(id=value['id'], project_id=project,
            manifest_sha256=value['manifest_sha256'], task_id=value['task_id'])
        self.save()
        self.download(value, label)
        return value

    def material(self, filename):
        folder = control.RUNTIME / 'materials'
        manifest = json.loads((folder / 'download-manifest.json').read_bytes())
        source = next(value for value in manifest['files'] if value['filename'] == filename)
        path = folder / filename
        if hashlib.sha256(path.read_bytes()).hexdigest() != source['sha256']:
            raise ValueError('Authorized original material SHA differs')
        return path, source

    def features(self):
        project = self.project('sequence-structure')
        specifications = [
            ('ubb-rna', 'UBB_NM_018955.4.fasta', 'sequence', 'fasta', 'RefSeq_transcript',
             dict(sequence_type='rna', nucleotide_encoding='T'), 'UBB mRNA（原件T编码）'),
            ('ubb-protein', 'UBB_NP_061828.1.fasta', 'sequence', 'fasta', 'RefSeq_protein',
             dict(sequence_type='protein'), 'UBB蛋白前体（不与1UBQ认作全长对应）'),
            ('ubq-structure', 'pdb_00001ubq_xyz_v1-3.cif.gz', 'structure', 'mmcif.gz', 'PDB_author_chain',
             dict(structure_origin='experimental'), '1UBQ v1.3 实验结构；model1/author chain A'),
        ]
        sources = []
        resources = {}
        for label, filename, kind, fmt, namespace, explicit, title in specifications:
            path, original = self.material(filename)
            uploaded = self.upload_resource(label + '-file', project, path)
            config = dict(kind=kind, title=title, species_taxon_id=9606, namespace=namespace,
                release=original['version'].replace(' ', '_'), **explicit,
                source=dict(institution='wwPDB' if kind == 'structure' else 'NCBI RefSeq', name=original['version'],
                    description=title + '；来源版本和原件SHA固定。核酸编码不转换，蛋白前体与实验结构不自动建立对应。', url=original['url']),
                usage=dict(basis=original['license'], redistribution_allowed=True, scope='project'),
                files=[dict(file_id=uploaded['file_id'], sha256=uploaded['sha256'], role=fmt.removesuffix('.gz'),
                    format=fmt, max_uncompressed_bytes=1048576)])
            resource = self.resource(label, project, config)
            resources[label] = resource['id']
            sources.append(dict(source_kind='bio_resource_version', source_id=resource['id'],
                sha256=resource['manifest_sha256'], role='feature_input', locator=dict(kind='object')))
        config = dict(kind='feature_extract', resource_source_ids=list(resources.values()),
            structure_selections=[dict(resource_source_id=resources['ubq-structure'], model_id=1, chain_id='A')],
            steps=[dict(operation='exclude', feature_ids=[resources['ubb-rna'] + ':1'])], output_language='zh-CN')
        result = self.analyze('sequence-structure-features', project, config, sources)
        self.record.setdefault('paths', {})['sequence-structure'] = dict(project_id=project,
            resource_ids=resources, result_id=result['id'], candidate_rule='仅按预声明ID将RNA保留于完整结果、排除出蛋白/结构候选；不比较跨类型长度，不建立序列结构对应。')
        self.save()
        return dict(project_id=project, result_id=result['id'])

    def feature_figure(self):
        entry = self.record['results']['sequence-structure-features']
        source = dict(source_kind='bio_insight_result_version', source_id=entry['id'],
            sha256=entry['manifest_sha256'], role='result', locator=dict(kind='object'))
        result = self.analyze('sequence-structure-figure', entry['project_id'],
            dict(kind='figure', result_source_id=entry['id'], figure_type='feature_scatter',
                x_column='ca_count', y_column='radius_of_gyration',
                title='1UBQ 单条链的 Cα 几何特征（描述性；非对象间推断）',
                formats=['png', 'tiff', 'svg', 'pdf'], output_language='zh-CN', width_inches=8.0, height_inches=5.0), [source])
        return dict(id=result['id'], project_id=entry['project_id'])

    def quantitative_layers(self):
        project = self.project('matched-omics')
        folder = control.RUNTIME / 'materials'
        proof = json.loads((folder / 'import-orientation-audit.json').read_bytes())
        paths = {}
        for layer, assay, count, namespace in [('mrna', 'normalized_expression', 200, 'author_gene_symbol'),
                                               ('protein', 'proteomics', 142, 'author_protein_label')]:
            label = 'matched-' + layer
            inputs = {role: folder / 'derived' / (layer + suffix) for role, suffix in [
                ('quantitative_matrix', '-feature-by-sample.tsv'), ('sample_metadata', '-samples.tsv'),
                ('feature_metadata', '-features.tsv')]}
            for path in inputs.values():
                expected = proof['files'][str(path.relative_to(folder))]
                if hashlib.sha256(path.read_bytes()).hexdigest() != expected['sha256']:
                    raise ValueError('Frozen orientation adapter output differs')
            files = {role: self.upload(label + '-' + role, project, path) for role, path in inputs.items()}
            with inputs['quantitative_matrix'].open(encoding='utf-8', newline='') as stream:
                samples = next(csv.reader(stream, delimiter='\t'))[1:]
            config = dict(workflow_version='bio_import_v3', file_ids=list(files.values()), assay=assay,
                name='breast.TCGA 作者预处理 ' + layer + ' 完整训练层', expected_dataset_revision=0,
                tables=[dict(file_id=value, role=role, format='tsv') for role, value in files.items()],
                feature_id_column='feature_id', sample_columns=samples, na_values=['', 'NA', 'N/A'],
                scale=dict(kind='normalized', unit='author_provided_unit_unknown',
                    upstream_method='mixOmics 1c7f420460df6354f9764f48f79c06ff69e461a6 breast.TCGA data.train；作者 normalized/preprocessed/drastically filtered；精确归一化、变换底数与实验单位未提供。仅转置原字符串。',
                    upstream_transforms=['unknown_in_author_source'], namespace=namespace,
                    reference_version='unknown', species_taxon_id=9606, zero_meaning='unknown'))
            raw = self.import_source(label, project, config, dict(features=count, observations=150), count * 150)
            paths[layer] = self.process_raw(label, project, raw,
                dict(recipe_code='tabular_quantitative_v1', name='作者预处理尺度保留：' + layer,
                    raw_source=raw, expected_revision=0, params=dict(normalization='already_normalized',
                        transform='none', scaling='none', pca_components=10, seed=0, output_language='zh-CN')), assay)
        self.record.setdefault('paths', {})['matched-omics'] = dict(project_id=project,
            layers=paths, donor_independence='unknown', statistical_scope='descriptive_only')
        self.save()
        return dict(project_id=project, processed_ids={name: value['processed_id'] for name, value in paths.items()})

    def fixed_table(self, name, columns, rows):
        folder = self.output / 'inputs'
        folder.mkdir(exist_ok=True)
        stream = io.StringIO(newline='')
        writer = csv.DictWriter(stream, fieldnames=columns, delimiter='\t', lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
        raw = stream.getvalue().encode('utf-8')
        path = folder / name
        if path.exists():
            if path.read_bytes() != raw:
                raise ValueError('Existing frozen input table differs; keep its original request identity')
        else:
            path.write_bytes(raw)
        return path

    def integration(self):
        from app.domain.bio_insights.integration_contracts import SAMPLE_COLUMNS, OBJECT_COLUMNS, IntegrationConfig
        record = self.record['paths']['matched-omics']
        project = record['project_id']
        layers = record['layers']
        folder = control.RUNTIME / 'materials'
        sample_declaration = json.loads((folder / 'derived/sample-correspondence-frozen.json').read_bytes())
        pair_declaration = json.loads((folder / 'derived/candidate-pairs-frozen.json').read_bytes())
        sample_rows = []
        for sample in sample_declaration:
            for layer in ('mrna', 'protein'):
                sample_rows.append(dict(dataset_version=layers[layer]['processed_id'], observation_id=sample[layer + '_observation_id'],
                    donor_id='', tissue='', time='', match_group=sample['sample_pair_id'], relationship=sample['relationship'],
                    basis=sample['source_locator'] + '；作者声明匹配，完整参与者/aliquot标识未提供；仅用于描述性系数。', independent_unit_verified='false'))
        object_rows = []
        pairs = []
        for pair in pair_declaration['pairs']:
            left = layers[pair['source_layer']]['processed_id']
            right = layers[pair['target_layer']]['processed_id']
            object_rows.append(dict(source_dataset_version=left, source_id=pair['source_feature_id'],
                source_namespace=pair['namespace_source'], source_species='9606', source_version='unknown',
                target_dataset_version=right, target_id=pair['target_feature_id'], target_namespace=pair['namespace_target'],
                target_species='9606', target_version='unknown', relationship=pair['relationship'], basis=pair['mapping_basis'],
                ambiguity='none', decision='include'))
            pairs.append(dict(pair_id=pair['pair_id'], left_source_id=left, left_feature_id=pair['source_feature_id'],
                right_source_id=right, right_feature_id=pair['target_feature_id']))
        source_rda = next(value for value in json.loads((folder / 'download-manifest.json').read_bytes())['files'] if value['filename'] == 'breast.TCGA.rda')
        selected = []
        resource_ids = {}
        for kind, columns, rows, role in [('sample_correspondence', SAMPLE_COLUMNS, sample_rows, 'sample_mapping'),
                                         ('object_correspondence', OBJECT_COLUMNS, object_rows, 'object_mapping')]:
            path = self.fixed_table('matched-' + kind + '.tsv', columns, rows)
            uploaded = self.upload_resource('matched-' + kind + '-file', project, path)
            value = self.resource('matched-' + kind, project,
                dict(kind=kind, title='breast.TCGA 冻结' + ('样本对应' if kind == 'sample_correspondence' else '对象标签对应'),
                    species_taxon_id=9606, namespace='author_sample_label' if kind == 'sample_correspondence' else 'author_label_correspondence',
                    release='breast_TCGA_training_mapping_v1',
                    source=dict(institution='mixOmics / TCGA', name=source_rda['version'], url=source_rda['url'],
                        description='由获批原件和计算前冻结声明建立；RDA SHA256=' + source_rda['sha256'] + '。标签对应不证明抗体特异性或供体独立性。'),
                    usage=dict(basis=source_rda['license'] + '；本项目内部派生对应表，保留原作者/TCGA来源。', redistribution_allowed=True, scope='project'),
                    files=[dict(file_id=uploaded['file_id'], sha256=uploaded['sha256'], parse_version_id=uploaded['parse_version_id'], role=kind, format='tsv', columns={})]))
            resource_ids[kind] = value['id']
            selected.append(dict(source_kind='bio_resource_version', source_id=value['id'], sha256=value['manifest_sha256'],
                role=role, locator=dict(kind='object')))
        for layer in ('mrna', 'protein'):
            value = layers[layer]
            selected.append(dict(source_kind='bio_processed_dataset_version', source_id=value['processed_id'],
                sha256=value['processed_source']['manifest_sha256'], role='processed', locator=dict(kind='object')))
        config = IntegrationConfig(processed_source_ids=[layers[name]['processed_id'] for name in ('mrna', 'protein')],
            sample_mapping_source_id=resource_ids['sample_correspondence'], object_mapping_source_id=resource_ids['object_correspondence'],
            pairs=pairs, mode='descriptive', method='pearson', mapping_confirmed=True,
            partial_subset_confirmed=False, independence_confirmed=False, independence_basis='', output_language='zh-CN')
        result = self.analyze('matched-omics-integration', project, config.model_dump(mode='json'), selected)
        self.record['paths']['matched-omics'].update(integration_result_id=result['id'], correspondence_resources=resource_ids,
            frozen_pair_declaration_sha256=hashlib.sha256((folder / 'derived/candidate-pairs-frozen.json').read_bytes()).hexdigest())
        self.save()
        return dict(id=result['id'], project_id=project)

    def integration_figures(self):
        entry = self.record['results']['matched-omics-integration']
        source = dict(source_kind='bio_insight_result_version', source_id=entry['id'], sha256=entry['manifest_sha256'],
            role='result', locator=dict(kind='object'))
        results = {}
        for kind, title in [('network', '匹配样本的描述性相关与对象对应（无因果箭头）'), ('flow', '固定输入与实际整合处理来源流程')]:
            result = self.analyze('matched-omics-' + kind, entry['project_id'],
                dict(kind='figure', result_source_id=entry['id'], figure_type='integration_' + kind,
                    title=title, formats=['png', 'tiff', 'svg', 'pdf'], output_language='zh-CN',
                    width_inches=10.0, height_inches=6.0), [source])
            results[kind] = result['id']
        return dict(ids=results, project_id=entry['project_id'])

    def external_evidence(self):
        from app.domain.external_evidence.contracts import EvidenceRequest
        from verify_cr_b05_sub4_evidence_inputs import prepared_records
        project = self.record['paths']['matched-omics']['project_id']
        records = prepared_records(control.RUNTIME / 'materials')
        files = {}
        for name in dict.fromkeys(row['filename'] for row in records):
            path, source = self.material(name)
            files[name] = (self.upload_resource('evidence-original-' + path.stem, project, path), source)
        evidence = self.record.setdefault('external_evidence', {})
        for row in records:
            uploaded, original = files[row['filename']]
            config = EvidenceRequest(file_id=uploaded['file_id'], source_kind='original', title=row['title'],
                source_description=original['url'] + '；版本：' + original['version'] + '；原件SHA256：' + original['sha256'],
                intended_use='background', original_data='unknown',
                user_note='本轮只保存原件及精确来源陈述；未取得患者级/供体级数据，不进行原始数据重算。',
                limitations='定位匹配不等于生物学核验；人工核对未由用户确认；无真实KO或独立队列支持。',
                typed_evidence=row['typed_evidence']).model_dump(mode='json')

            def recover(entry):
                response = self.client.get(self.base(project) + '/external-evidence/requests/' + entry['key'])
                return None if response.status_code == 404 else self.check(response).json()

            value = self.post(row['label'] + '-evidence', self.base(project) + '/external-evidence', config, recover=recover)
            if (value['source']['source_sha256'] != original['sha256'] or value['computed_by_system'] is not False
                    or value['verification_status'] != 'external_not_recomputed'
                    or value['locator_verification']['locator_verified'] is not True):
                raise ValueError('Published original evidence status or locator differs')
            evidence[row['label']] = dict(id=value['id'], sha256=value['sha256'], project_id=project,
                source_sha256=original['sha256'], source_filename=row['filename'])
            directory = self.output / 'evidence'
            directory.mkdir(exist_ok=True)
            control.worker_stack.private_write(directory / (row['label'] + '.json'), json.dumps(value, ensure_ascii=False, indent=2))
            self.save()
        return dict(project_id=project, evidence_ids={name: value['id'] for name, value in evidence.items()})

    def evidence_matrix(self):
        from app.domain.bio_insights.evidence_contracts import EvidenceMatrixConfig
        from verify_cr_b05_sub4_evidence_inputs import ALIAS_LOCATOR, ALIAS_QUOTE, TCGA_CONDITION
        record = self.record['paths']['matched-omics']
        project = record['project_id']
        layers = record['layers']
        evidence = self.record['external_evidence']
        integrated = self.record['results']['matched-omics-integration']
        config = EvidenceMatrixConfig(candidates=[
            dict(object_id='ERBB2', source_id=layers['protein']['processed_id'], feature_id='HER2',
                namespace='author_protein_label', species_taxon_id=9606, reference_version='unknown',
                condition=TCGA_CONDITION, mapping_evidence_source_id=evidence['erbb2-disease']['id'],
                mapping_locator=ALIAS_LOCATOR, mapping_quote=ALIAS_QUOTE),
            dict(object_id='STAT5A', source_id=layers['mrna']['processed_id'], feature_id='STAT5A',
                namespace='author_gene_symbol', species_taxon_id=9606, reference_version='unknown', condition=TCGA_CONDITION),
        ], evidence_source_ids=[evidence[name]['id'] for name in ('erbb2-disease', 'erbb2-v777l', 'erbb2-hpa')],
            integration_result_source_ids=[integrated['id']], independent_support_requests=[], output_language='zh-CN')
        sources = [dict(source_kind='external_evidence_version', source_id=value['id'], sha256=value['sha256'],
            role='external_evidence', locator=dict(kind='object')) for value in evidence.values()]
        sources += [dict(source_kind='bio_processed_dataset_version', source_id=value['processed_id'],
            sha256=value['processed_source']['manifest_sha256'], role='processed', locator=dict(kind='object')) for value in layers.values()]
        sources.append(dict(source_kind='bio_insight_result_version', source_id=integrated['id'],
            sha256=integrated['manifest_sha256'], role='result', locator=dict(kind='object')))
        result = self.analyze('matched-omics-evidence', project, config.model_dump(mode='json'), sources)
        self.record.setdefault('report_sources', {})['matched-omics'] = ['matched-omics-integration', 'matched-omics-evidence']
        self.save()
        return dict(id=result['id'], project_id=project)

    def evidence_figures(self):
        entry = self.record['results']['matched-omics-evidence']
        source = dict(source_kind='bio_insight_result_version', source_id=entry['id'], sha256=entry['manifest_sha256'],
            role='result', locator=dict(kind='object'))
        results = {}
        names = []
        for kind, label, title in [
            ('evidence_matrix', 'matched-omics-evidence-figure', '候选×外部证据：条件差异、缺失与来源层级'),
            ('evidence_network', 'matched-omics-evidence-network', '外部证据来源关系（同论文记录合并依赖组）'),
            ('evidence_flow', 'matched-omics-evidence-flow', '原件、固定候选与证据矩阵的处理来源'),
        ]:
            result = self.analyze(label, entry['project_id'],
                dict(kind='figure', result_source_id=entry['id'], figure_type=kind, title=title,
                    formats=['png', 'tiff', 'svg', 'pdf'], output_language='zh-CN', width_inches=10.0, height_inches=6.0), [source])
            results[kind] = result['id']
            names.append(label)
        self.record.setdefault('report_figures', {})['matched-omics'] = ['matched-omics-network', 'matched-omics-flow', *names]
        self.save()
        return dict(ids=results, project_id=entry['project_id'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['features', 'feature_figure', 'quantitative_layers', 'integration', 'integration_figures',
        'external_evidence', 'evidence_matrix', 'evidence_figures'])
    args = parser.parse_args()
    acceptance = Acceptance()
    try:
        print(json.dumps(getattr(acceptance, args.action)(), ensure_ascii=False))
    finally:
        acceptance.client.close()
