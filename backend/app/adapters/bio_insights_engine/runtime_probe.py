"""Actual synthetic aggregation, model, local GSEA and kernel isolation gate."""
import os
for _name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMBA_NUM_THREADS',
              'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'BLIS_NUM_THREADS', 'RAYON_NUM_THREADS'):
    os.environ[_name] = '1'
os.environ.update(MPLBACKEND='Agg', MPLCONFIGDIR='/tmp/b04-mpl', XDG_CACHE_HOME='/tmp/b04-cache',
                  HDF5_PLUGIN_PATH='/nonexistent', HDF5_PLUGIN_PRELOAD='::')
from app.adapters.single_cell_r.bootstrap import preload_runtime_libraries
preload_runtime_libraries()
import hashlib
import importlib.metadata
import json
import resource
import signal
import socket
import subprocess
import sys
import tempfile
from pathlib import Path


def exercise(output):
    """Only trusted reproducible fixtures; also warms code used after isolation."""
    import numpy as np
    import pandas as pd
    from scipy import sparse
    from pydeseq2.dds import DeseqDataSet
    from pydeseq2.ds import DeseqStats
    from pydeseq2.default_inference import DefaultInference
    import gseapy
    from matplotlib import pyplot as plt
    from matplotlib.font_manager import FontProperties
    from tqdm import tqdm
    tqdm.monitor_interval = 0
    rng = np.random.default_rng(745)
    counts = rng.negative_binomial(12, .35, size=(24, 80)).astype('int64') + 1
    counts[12:, :10] *= 4
    aggregation = sparse.csr_matrix((np.ones(24, dtype='int64'),
                                    (np.repeat(np.arange(12), 2), np.arange(24))), shape=(12, 24))
    grouped = (aggregation @ sparse.csr_matrix(counts)).toarray()
    assert grouped.sum() == counts.sum()
    index = [f'donor{i}' for i in range(12)]
    frame = pd.DataFrame(grouped, index=index, columns=[f'g{i}' for i in range(80)])
    metadata = pd.DataFrame({'condition': ['A'] * 6 + ['B'] * 6}, index=index)
    inference = DefaultInference(n_cpus=1)
    dds = DeseqDataSet(counts=frame, metadata=metadata, design='~condition',
                       size_factors_fit_type='poscounts', refit_cooks=False,
                       low_memory=True, n_cpus=1, inference=inference, quiet=True)
    dds.deseq2()
    stats = DeseqStats(dds, contrast=['condition', 'B', 'A'], n_cpus=1,
                      cooks_filter=True, independent_filter=False, inference=inference, quiet=True)
    stats.summary()
    assert np.isfinite(stats.results_df['log2FoldChange']).all()
    assert stats.results_df.loc['g0':'g9', 'log2FoldChange'].median() > 0
    ranking = pd.Series(np.linspace(5, -5, 80), index=frame.columns)
    result = gseapy.prerank(rnk=ranking, gene_sets={'positive': list(frame.columns[:12]),
                            'negative': list(frame.columns[-12:])}, threads=1, permutation_num=100,
                            min_size=5, max_size=70, seed=0, outdir=None, no_plot=True, verbose=False)
    assert result.results['positive']['es'] > 0 and result.results['negative']['es'] < 0
    fig, ax = plt.subplots()
    ax.plot(ranking.to_numpy())
    ax.set_title('差异富集环境验证', fontproperties=FontProperties(fname='/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'))
    fig.savefig(output / 'probe.png', dpi=100)
    plt.close(fig)
    return {'aggregation': True, 'deseq2_fit': True, 'gsea': True,
            'fit_shape': list(frame.shape), 'gsea_permutations': 100,
            'png_bytes': (output / 'probe.png').stat().st_size,
            'render_formats': ['png']}


def exercise_propeller():
    from app.adapters.single_cell_r.bridge import get_bridge
    counts=[[20,80],[30,70],[25,75],[50,50],[60,40],[55,45]]
    result=get_bridge().propeller(counts,['u'+str(i) for i in range(6)],['T','other'],['A']*3+['B']*3,
        ['d'+str(i) for i in range(6)],['']*6,'donor_unpaired',numerator='B',denominator='A')
    assert result['status']=='completed' and result['rows'][0]['proportion_difference']>0
    assert 0<=result['rows'][0]['p_value']<=1
    return True


def warm_bulk_model():
    """Load the same modules in the probe and in the isolated task."""
    import codecs
    import importlib
    codecs.lookup('utf-8-sig')
    for name in ('pipeline','quantitative','counts_model'):
        importlib.import_module('app.adapters.bio_insights_engine.'+name)
    import app.domain.bio_insights.bulk_model_design
    import pydeseq2.dds
    import pydeseq2.ds
    import pydeseq2.default_inference


def exercise_bulk_model():
    import numpy as np
    from app.adapters.bio_insights_engine.counts_model import fit_reviewed_counts
    from app.domain.bio_insights.quantitative_contracts import QuantitativeComparisonConfig
    from app.domain.bio_insights.quantitative_design import validate_quantitative_design

    rows = [dict(processed_version_id='probe',sample_id=label+str(i),condition=label,retained=True,
                 biological_unit_id=label+str(i)) for label in 'ABC' for i in range(3)]
    keys = {(row['processed_version_id'],row['sample_id']):i for i,row in enumerate(rows)}
    contrasts = [dict(contrast_id=left+right,name=left+right,groups=[
        dict(label=label,sample_keys=[dict(processed_version_id='probe',sample_id=row['sample_id'])
                                    for row in rows if row['condition']==label]) for label in (left,right)])
        for left,right in [('A','B'),('B','A'),('C','A')]]
    config = QuantitativeComparisonConfig(mode='bulk_counts',bulk_model='shared_wald_v1',design='multiple',
        method='deseq2_wald',analysis_layer='raw_counts',contrasts=contrasts,family_contrast_ids=['AB','BA','CA'],
        inference_unit='biological',inference_goal='exploratory',independence_confirmed=True,
        independence_basis='synthetic runtime gate',design_basis='fixed synthetic runtime gate',data_driven_grouping=False,
        namespace='synthetic',reference_version='fixed')
    features = [f'g{i}' for i in range(80)]
    sources = [dict(source_kind='bio_processed_dataset_version',metadata=dict(
        canonical_dataset_id='probe',assay='bulk_rna_counts',observation_level='sample',namespace=config.namespace,
        reference_version=config.reference_version,observations=rows,feature_ids=features))]
    preview = validate_quantitative_design(config,sources)
    assert preview.executable, preview.blocking_reasons
    rng = np.random.default_rng(745)
    counts = rng.negative_binomial(12,.25,size=(len(rows),len(features))).astype('int64')+1
    counts[:3,:8] *= 4
    fitted, model = fit_reviewed_counts(counts,features,keys,preview.bulk_model,config)
    forward, reverse = fitted['AB'][0], fitted['BA'][0]
    assert forward['test_status']==reverse['test_status']=='tested'
    assert forward['effect_value']>0 and np.isclose(forward['effect_value'],-reverse['effect_value'])
    assert model['diagnostics']['contrast_ids']==['AB','BA','CA'] and len(model['size_factors'])==9
    return {'bulk_shared_wald':True,'bulk_model_shape':list(counts.shape),'bulk_model_contrasts':3}


def warm_plot_formats(output):
    from matplotlib import pyplot as plt
    from matplotlib.font_manager import FontProperties

    fig, ax = plt.subplots()
    try:
        ax.plot([0, 1], [0, 1])
        ax.set_title('图形环境验证', fontproperties=FontProperties(fname='/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'))
        for fmt in ('png', 'svg', 'tiff'):
            fig.savefig(output / ('warm.' + fmt), format=fmt)
    finally:
        plt.close(fig)


def warm_bulk_display(output):
    import codecs
    from PIL import Image
    # Attest the native OpenMP library shared with the fitted Bulk packages.
    import sklearn.utils._openmp_helpers

    Image.init()
    codecs.lookup('utf-8-sig')
    for name in ('pipeline', 'tables', 'bulk_figures', 'figures', 'candidates', 'resources', 'enrichment'):
        importlib.import_module('app.adapters.bio_insights_engine.' + name)
    importlib.import_module('gseapy.gse')
    warm_plot_formats(output)


def exercise_bulk_display(output):
    from app.adapters.bio_engine.manifest import Writer
    from app.adapters.bio_insights_engine.pipeline import run

    common = dict(contrast_id='A_B', numerator='A', denominator='B', tested=True, test_status='tested')
    saved = Writer(output).table('comparison_results', [
        dict(common, row_key='row-a', feature_id='a', effect_value=2.0, base_mean=20.0, q_within_contrast=0.0),
        dict(common, row_key='row-b', feature_id='b', effect_value=-1.0, base_mean=5.0, q_within_contrast=None),
    ])
    source = dict(source_id='probe', source_kind='bio_insight_result_version', sha256=saved['sha256'],
        metadata=dict(kind='comparison', plan_config=dict(mode='bulk_counts', bulk_model='shared_wald_v1',
            contrasts=[dict(contrast_id='A_B', groups=[dict(label='A'), dict(label='B')])])),
        members={'comparison_results': saved})
    result = run(dict(schema_version=1, kind='bio_insight_figure', sources=[source], identity={'purpose': 'bulk-display-probe'},
        config=dict(kind='figure', result_source_id='probe', figure_type='bulk_volcano',
                    bulk_selection=dict(contrast_id='A_B'), top_n=1, width_inches=4.0, height_inches=3.0, dpi=72),
        output_directory=str(output)))
    data = json.loads((output / 'plot_data.json').read_bytes())
    assert data['selected_deg_count'] == 1 and data['displayed_count'] == 1
    assert data['rows'][0]['q_value'] == 0 and data['rows'][1]['q_value'] is None
    assert result['methods']['analysis_recomputed'] is False
    rendered = {member['format'] for member in result['outputs'] if member['key'] == 'figure_' + member['format']
                and Path(member['path']).stat().st_size > 0}
    assert rendered == {'png', 'svg', 'tiff'}
    return {'bulk_saved_values_render': True, 'bulk_display_formats': ['png', 'svg', 'tiff']}


def exercise_bulk_enrichment(output):
    from app.adapters.bio_engine.manifest import Writer
    from app.adapters.bio_insights_engine.pipeline import run
    from app.domain.bio_insights.contracts import ResourceImportRequest

    def execute(kind, config, sources, name):
        directory = output / name
        result = run(dict(schema_version=1, kind=kind, config=config, sources=sources,
                          identity={'purpose': name}, output_directory=str(directory)))
        return result, {item['key']: item for item in result['outputs']}

    genes = [f'g{i:02}' for i in range(40)]
    resource_file = Writer(output).add('probe_gene_sets', (
        'positive\tpositive term\t' + '\t'.join(genes[:10]) + '\nnegative\tnegative term\t'
        + '\t'.join(genes[-10:]) + '\n'
    ).encode(), 'gmt')
    original = dict(source_kind='original_file', source_id='local-gmt', role='gmt', sha256=resource_file['sha256'],
                    metadata={}, members={'original_file': resource_file})
    resource_config = ResourceImportRequest(kind='gene_sets', title='Probe local sets', species_taxon_id=9606,
        namespace='ensembl_gene_id', release='probe', offline_enrichment=True,
        source={'name': 'Probe', 'institution': 'PaperAssist', 'description': 'Synthetic runtime fixture'},
        usage={'basis': 'Synthetic fixture', 'redistribution_allowed': True, 'scope': 'redistributable'},
        files=[{'file_id': 'local-gmt', 'role': 'gmt', 'format': 'gmt', 'sha256': resource_file['sha256']}])
    _, resource_members = execute('bio_resource_import', resource_config.model_dump(mode='json'), [original], 'local-sets')
    resource = dict(source_kind='bio_resource_version', source_id='sets', role='gene_sets', metadata={},
                    sha256=resource_members['manifest']['sha256'], members={'resource': resource_members['resource']})
    assert json.loads(Path(resource_members['resource']['path']).read_bytes())['stats']['term_count'] == 2

    table = Writer(output).table('probe_bulk_stats', [
        dict(row_key='r'+gene, feature_id=gene, contrast_id='A_B', numerator='A', denominator='B',
             tested=True, test_status='tested', inference_scope='sample_inference',
             wald_statistic=20.5-i, effect_value=2 if i < 10 else -0.5,
             q_within_contrast=.001 if i < 10 else .8, q_global_family=.002 if i < 10 else .9,
             original_method_adjustment=.003 if i < 10 else None)
        for i, gene in enumerate(genes)
    ])
    metadata = dict(kind='comparison', species_taxon_id=9606, namespace='ensembl_gene_id', reference_version='probe',
        inference_scope='sample_inference', summary_json={'tested_universe_complete': True},
        plan_config=dict(mode='bulk_counts', bulk_model='shared_wald_v1',
                         contrasts=[dict(contrast_id='A_B', groups=[dict(label='A'), dict(label='B')])]))
    comparison = dict(source_kind='bio_insight_result_version', source_id='comparison', role='result',
                      sha256=table['sha256'], metadata=metadata, members={'comparison_results': table})
    shared = dict(resource_source_ids=['sets'], bulk_enrichment={}, min_size=5, max_size=30)
    ora_config = dict(shared, kind='ora', result_source_ids=['comparison'], contrast_ids=['A_B'], direction='up')
    ora, _ = execute('bio_enrichment', ora_config, [comparison, resource], 'offline-ora')
    assert ora['summary']['enrichment_status'] == 'completed'
    assert ora['summary']['row_count'] == 2 and ora['summary']['significant_terms'] == 1

    gsea_config = dict(shared, kind='gsea_prerank', result_source_id='comparison', contrast_id='A_B',
                       ranking_column='wald_statistic', permutation_num=100)
    gsea, gsea_members = execute('bio_enrichment', gsea_config, [comparison, resource], 'offline-gsea')
    curves = json.loads(Path(gsea_members['gsea_curves']['path']).read_bytes())
    terms = {row['term_id']: row for row in curves['terms']}
    assert gsea['summary']['ranking_size'] == 40 and len(terms) == 2
    assert terms['positive']['es'] > 0 > terms['negative']['es']
    assert terms['positive']['leading_edge'] and terms['negative']['leading_edge']
    published = dict(source_kind='bio_insight_result_version', source_id='gsea', role='result',
                     sha256=gsea_members['manifest']['sha256'],
                     metadata={'kind': 'gsea_prerank', 'plan_config': gsea_config},
                     members={key: gsea_members[key] for key in ('gsea_curves', 'gsea_ranking', 'enrichment_results')})
    figure_config = dict(kind='figure', figure_type='gsea', result_source_id='gsea',
                         term_row_key=terms['positive']['row_key'], bulk_enrichment_render=True,
                         formats=['png'], dpi=72)
    figure, figure_members = execute('bio_insight_figure', figure_config, [published], 'offline-gsea-figure')
    assert figure['summary']['figure_type'] == 'gsea' and figure_members['figure_png']['size_bytes'] > 0
    return {'bulk_offline_resource_import': True, 'bulk_offline_enrichment': True,
            'bulk_offline_enrichment_render': True, 'bulk_enrichment_probe_ranks': 40,
            'bulk_enrichment_probe_permutations': 100}


def probe(*, bulk_model=False, bulk_display=False):
    from app.domain.bio_insights.settings import BioInsightsLimits, engine_code_digest
    from app.domain.bioinformatics.settings import BioLimits
    from app.adapters.bio_insights_engine.sandbox import enter
    from PIL import Image
    from threadpoolctl import threadpool_info
    limits = BioInsightsLimits()
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError('bio_insights_deadline')))
    signal.alarm(limits.warmup_seconds)
    Image.init()
    output = Path(tempfile.mkdtemp(prefix='bio-insights-probe-'))
    r_scratch = None
    if bulk_model:
        warm_bulk_model()
    elif bulk_display:
        # The confined child writes into pre-existing output directories.
        for name in ('local-sets', 'offline-ora', 'offline-gsea', 'offline-gsea-figure'):
            (output / name).mkdir()
        with tempfile.TemporaryDirectory(prefix='bulk-display-warm-') as warm:
            warm_bulk_display(Path(warm))
    else:
        # Match production import order before measuring loaded native libraries.
        for name in ('comparison','result_import','resources','enrichment','candidates','figures'):
            importlib.import_module('app.adapters.bio_insights_engine.'+name)
        exercise(output)
        from app.adapters.single_cell_r.bridge import initialize_propeller,get_bridge
        r_scratch=Path(tempfile.mkdtemp(prefix='b04-propeller-',dir='/tmp'))
        from contextlib import redirect_stdout
        with redirect_stdout(sys.stderr):initialize_propeller(r_scratch)
        exercise_propeller()
        from app.adapters.single_cell_r.topics import initialize_topics,exercise_topics
        with redirect_stdout(sys.stderr):
            for method in ('slingshot','genie3','cellchat'):initialize_topics(r_scratch,method)
    # Match actual_identity() in the normal Worker; scikit-bio owns an
    # additional OpenMP library even when this task does not use beta analysis.
    import skbio.stats.distance
    packages = {dist.metadata['Name'].lower().replace('_', '-'): dist.version
                for dist in importlib.metadata.distributions()}
    libraries = sorted(threadpool_info(), key=lambda library: library['filepath'])
    for library in libraries:
        library['sha256'] = hashlib.sha256(Path(library['filepath']).read_bytes()).hexdigest()
        assert library['num_threads'] == 1
    report = {'schema_version': 1, 'engine_version': 'bio_insights_v1.0.0',
              'interpreter': sys.executable, 'python': sys.version, 'packages': packages,
              'native_libraries': libraries, 'numeric_threads': 1,
              'warm_threads': len(os.listdir('/proc/self/task')), 'limits': limits.model_dump(),
              'bulk_limits': BioLimits().model_dump(),
              'code_digest': engine_code_digest(),
              'lock_sha256': hashlib.sha256(Path('/app/requirements-bio-insights.lock.txt').read_bytes()).hexdigest()}
    if bulk_model:
        report['profile']='bulk_model'
    elif bulk_display:
        report['profile'] = 'bulk_display'
    else:
        report['propeller_versions']=dict(get_bridge().versions)
    report['container_memory_limit_bytes'] = int(Path('/sys/fs/cgroup/memory.max').read_text())
    report['container_cpu_max'] = Path('/sys/fs/cgroup/cpu.max').read_text().strip()
    report['docker_mem_available_bytes'] = next(int(line.split()[1]) * 1024 for line in
        Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
    assert report['container_memory_limit_bytes'] <= 4 * 1024**3
    assert report['docker_mem_available_bytes'] >= 4 * 1024**3
    # Open only these non-secret counter files before isolation. Retained FDs
    # permit final accounting without granting customer code a cgroup directory.
    memory_counter = os.open('/sys/fs/cgroup/memory.peak', os.O_RDONLY | os.O_CLOEXEC)
    task_counter = os.open('/sys/fs/cgroup/pids.peak', os.O_RDONLY | os.O_CLOEXEC)
    assert report['warm_threads'] == 1, report['warm_threads']
    signal.alarm(limits.compute_wall_seconds)
    pinned = enter([], output, parent_pid=os.getppid(),r_scratch=r_scratch)
    isolation = {}
    for name, action in [('network', lambda: socket.socket()), ('file', lambda: Path('/etc/passwd').read_bytes()),
                         ('fork', os.fork), ('subprocess', lambda: subprocess.run(['/bin/true'], check=True))]:
        try:
            action()
        except PermissionError:
            isolation[name] = 'denied'
        else:
            raise AssertionError(f'{name} unexpectedly permitted')
    if bulk_model:
        report['checks'] = exercise_bulk_model()
    elif bulk_display:
        report['checks'] = exercise_bulk_display(output)
        report['checks'].update(exercise_bulk_enrichment(output))
    else:
        report['checks'] = exercise(output)
        report['checks']['single_cell_propeller']=exercise_propeller()
        topic_checks=exercise_topics()
        report['topic_versions']=topic_checks.pop('topic_versions')
        report['checks'].update(topic_checks)
    report.update(status='passed', isolation=isolation,
                  peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  address_space_limit=list(resource.getrlimit(resource.RLIMIT_AS)),
                  shared_uid_process_limit=list(resource.getrlimit(resource.RLIMIT_NPROC)))
    report['container_peak_memory_bytes'] = int(os.read(memory_counter, 128))
    report['container_peak_tasks'] = int(os.read(task_counter, 128))
    os.close(memory_counter); os.close(task_counter)
    assert report['peak_rss_kib'] < limits.memory_bytes // 1024
    for descriptor in pinned:
        os.close(descriptor)
    signal.alarm(0)
    return report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    profile = parser.add_mutually_exclusive_group()
    profile.add_argument('--bulk-model', action='store_true')
    profile.add_argument('--bulk-display', action='store_true')
    print(json.dumps(probe(**vars(parser.parse_args())), sort_keys=True, allow_nan=False))
