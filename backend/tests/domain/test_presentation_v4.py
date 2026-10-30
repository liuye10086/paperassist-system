"""Pure v4 contracts; historical bundles are captured real pre-repair inputs."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from app.core.exceptions import StorageError
from app.domain.external_processing import digest
from app.domain.figure_workbench import material, presentation, prompts
from app.domain.figure_workbench.contracts import FigureConfig


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None  # These tests never enter persistence or the numeric worker.


GOLDEN_DIR = Path(__file__).resolve().parents[1] / 'fixtures/figure_b07/old-v4-bundles-native-order'
assert len(list(GOLDEN_DIR.glob('*.json')))==17, 'All captured historical fixtures must be present.'
# GOLDEN_BASELINE is inserted before any production edit from captured real files.
GOLDEN_BASELINE = {'010cd2e0-ef35-407c-a1aa-ed21d3902591.json': ('affd4f0814fc15f1bd9c7f52e851d9a4bbc3d75d21f52caaf5d97217e7b2c256',
                                               '22cfd2a8db45468e6d40e94f5bde9b9619ec94776a795d4eddb3281e0835d501',
                                               'ac12a07544933b53bf7100e9623742d7394471bb4fe488ae1d983cec784532e6',
                                               '64f7f980f24fa9e5c2200d92e2890cbdbe621e6e24d21cbcefc38dbe5ed86503'),
 '12b65c96-ab37-44aa-b49c-4a97057b9415.json': ('375acc5f998154bdb731937174dab6dfa5575d7bb13b341011ff41e77f2d2512',
                                               '30039417492ae70637422cf5946fffa6e9e186d67b487324cb0c7f63068f0e92',
                                               '7e7491a6302aa0463a7305ee6bd301283d47818550d33ed42b12c9d06a1ce573',
                                               '64f7f980f24fa9e5c2200d92e2890cbdbe621e6e24d21cbcefc38dbe5ed86503'),
 '3346a5a1-f6e1-40ce-9008-184c532212f8.json': ('a03b7ffb239d55b5b877023e42fc4109867e2dfca780401270befa14e8c39264',
                                               'a1750034228fb1986c3637a85c03f8cdc3c81682963956a7b48f68253600c7a7',
                                               '1076269842d20b03b8bd223b26e58a969126ddb28c5aeabd4be4ec8446a453c1',
                                               '3008f3d6531f664b2c88a3a260bfe7bf39707c2b2ee3f8d17731b44add77092e'),
 '3be278aa-3ea5-4af9-b98e-4257c30f15fd.json': ('26d8ca9367c904ffafa7418f35750e73fc701414ee182aedfad6237a84e021db',
                                               'aff9d26699e86188311009a1c76104bbdfcebd2f3b9f45d477cfd02920723873',
                                               '2486d28631aa3c261d372cbf6a77ddc85d8d47eae7b2a85ced856d1ab19a224d',
                                               '07fecbd98224b1554d752c50c3fed3e61db85736300638de42df81cb71cc5981'),
 '3c2419ee-89e1-43c1-85f0-4f629c397b78.json': ('b6a694d361c3e76923aa06a87d956426321fcb656f9bd46ec1d672266db83d96',
                                               '59c9ef54d5d5976c7ab1464223bf9011c8e343cb10673617ad492ad4643eaf09',
                                               '99a13679bbfefa6bada8a0ec863ce9fd61e2c1a7c6fc007420bd1196ecee1a60',
                                               '07fecbd98224b1554d752c50c3fed3e61db85736300638de42df81cb71cc5981'),
 '3f971f2c-b255-4b21-b4ce-8cf08209c520.json': ('2f97e0248b6b91b3bab39089420aa55d29cea09d622c316b4293c5a6334bc778',
                                               '481d6d731f1b3151ac2fb9316e782f7897aaa32db2a12d7a1b72825064eda4c5',
                                               'cc5d09574550adfe0403c08065b85fe23488f75c27e7007bdc0772ff4b6038dc',
                                               '07fecbd98224b1554d752c50c3fed3e61db85736300638de42df81cb71cc5981'),
 '43e7a550-46f9-4091-b709-a45ce50e51b0.json': ('6cd37b9220ff7ca80f28aa38cd43a68679d1e55eb7c40ca306595d06a2ad913b',
                                               'ed00484ea18e234e88df8a82894fa7fe7a2086bffa9efd73f6b9a64f7d4391be',
                                               '4b42cdc80befaf6a865f2bbf335b38b933cc609bc248e653a2ed9bc380167a3c',
                                               '07fecbd98224b1554d752c50c3fed3e61db85736300638de42df81cb71cc5981'),
 '72c48a9c-4c17-4290-aa4d-f280412a7de1.json': ('e96efdbaa5ae6862050957c58cd8a5ef6015d7872c469e130890b44e3cfebf30',
                                               '00787c829a8e3ab6a37b66c5fbdea3fe1450fe315a52b63a8cfd050006c30cdb',
                                               '51dc2380497296418be0529f1f29e523b1fd00d17f84b823d978d247d5324b32',
                                               '07fecbd98224b1554d752c50c3fed3e61db85736300638de42df81cb71cc5981'),
 '7991caf8-33de-4e90-a9da-0ace3df6f2a7.json': ('3874271a7fc00e0963c81868417e65867ebe4e55ffb963f2326f7430e5205ad2',
                                               'c3cf37d600fd04f2654ba4125c55c2e7e778f04985f2abbda1f65b0cc9d3aa74',
                                               '6f1f78f532a96056ae3f637c3db950114367c61c2dd911ece4c350b2a0a8658c',
                                               '21121362669a45af83b1788f46a634c39e7fd66f8a524236059247da4e22923f'),
 '828b02fb-ec71-41ed-a75f-cab93b092529.json': ('33f63d862b74cf1ca7f0439fd3ceabee79f982e1b872288fb0d649dfd5a14967',
                                               'c356e7ffeb215eb13e15d5fd1e1611a7ce00fadda44a42763cee07c7ab84d619',
                                               '3d3b93b6aa7a54d2aad77e68dcc42badf9dc190b8536c82fa03d5f26d81ee92f',
                                               '21121362669a45af83b1788f46a634c39e7fd66f8a524236059247da4e22923f'),
 '85468335-c1ae-4375-b44b-1926faae24bf.json': ('d2ed8843660487db4868e95de6b8f6d2677018452691f9515c0e0c4a8da701e8',
                                               '41e9dbdba9d3b5016cf982ef8b9fd8a86a463e724c248a51dfd8a879b26e8cb1',
                                               '7d70b2d3ea2ec1e6f0220b9d36b28c45d8f5191975c5d5a18c22cf5885dec9d4',
                                               '07fecbd98224b1554d752c50c3fed3e61db85736300638de42df81cb71cc5981'),
 '8813fd0c-22ba-4146-8115-c1a8370abf6b.json': ('c0581d5f58cdada49e7c325d2a9dad53f066e16216baca9bb0eb735048393583',
                                               '4e6fef6c86e349761b1ddcfbd9b74f7a56ebbc55adc9b5336d39f5dab1aa28f7',
                                               '241fa5dcf22d4a259c22fae928e8b9c50c08654e637350e2dc688a50e7337e12',
                                               '3008f3d6531f664b2c88a3a260bfe7bf39707c2b2ee3f8d17731b44add77092e'),
 'a07372c8-318d-4fe2-8c8d-ce7db6b53189.json': ('4b4710ca9085457fa169f2fc56e3bedea1eb11c4f8e0bf29daa48f7dd76577a9',
                                               '7c06f8a2ffc88aea76849d08e8d991dcfe5a10e6c41435a8e29dafc4d8e6b8b9',
                                               'ce7eb032a240082428146cbc8e7f27512924dc28ec2a5fa7533f3ead70812183',
                                               '540af9447b0e20fc334cc8d0ff88eed88119968488d12f1dd44f47d8375efdc5'),
 'a4efd6b2-4a02-4c54-88da-18649ab2e697.json': ('f94f7dd625dff0bb4069658f76abb0a0159cc7b8356f014516cc41b51d340a7c',
                                               '9b1edf1b5c915fd80d460e455c2db3af7cfbfbfae206710f5ed193f62cf636fd',
                                               'e9b730e689d6dfc5e76fe554b13d751dfe02a473e62e789253ca3b53a7a385a7',
                                               '3008f3d6531f664b2c88a3a260bfe7bf39707c2b2ee3f8d17731b44add77092e'),
 'd3153a8f-532f-4953-bb35-d88f2cbe07de.json': ('2cdab333e47b652a1c6bee7ed51847b904ed7a6862a5faf451f9c642e38da0b5',
                                               'bd8f2c33807468217993dfc2c539c9da9ed58305636d52e7da6733e77d55be97',
                                               '3adea97ba0e29a26f1c3c5947f45741afef746e3c7d6df8889e0898ac742d296',
                                               '7439a3148377b9fc8ccdafa772c0c7bae4c48da1c28f131ee1d1f8abde76026e'),
 'eef88982-0bb3-4e04-a4af-e48c219d5425.json': ('4f4e793f8a8f54e78e2fac55a85f30729574871f10d731d1e87a6099fcd1f693',
                                               '7197c3f0bea97f46049abe2eb421dfcad74a427be84f5adcda47bda2b81373e0',
                                               'f64a0b081ce99ef4d8a51d43fe27333fdbfa0a2adf3a76901c092b57e71e6bbb',
                                               '3008f3d6531f664b2c88a3a260bfe7bf39707c2b2ee3f8d17731b44add77092e'),
 'ef3611e3-298d-48a7-92fc-cf41045a58dc.json': ('f5ad86130b6dffca39a39790e8d6a5e3ac27d497cb13cb348effd694860cd02d',
                                               'b18802a7b4b4d30d606456ccebd8024e0fd4de89d0d610d8d552b4dfb501c228',
                                               '4db3c9b50426711c83f92e7d6346f6112333cf8becf990b28f34a8e4df849a05',
                                               '540af9447b0e20fc334cc8d0ff88eed88119968488d12f1dd44f47d8375efdc5')}


def historical():
    return [json.loads(path.read_text(encoding='utf-8')) for path in sorted(GOLDEN_DIR.glob('*.json'))]


def frozen_fields(bundle):
    fields = {v['column']: deepcopy(v) for v in bundle['result'].get('variables', [])}
    config = bundle['configuration']['config']
    axes = bundle['projection']['result']['_material']['payload']['presentation']['axes']
    for axis, roles in [('x', ('x_column', 'category_column', 'group_column')), ('y', ('y_column',))]:
        column = next(((config.get('projection') or {}).get(role) for role in roles if (config.get('projection') or {}).get(role)), None)
        if column and column not in fields:
            info = axes[axis]
            suffix = ' (' + info['unit'] + ')' if info['unit'] else ''
            fields[column] = {'name': info['label'][:-len(suffix)] if suffix else info['label'], 'unit': info['unit']}
    return fields


@pytest.mark.parametrize('entry', historical(), ids=lambda e: e['key'])
def test_actual_historical_payload_expected_presentation_prompt_and_source_stay_frozen(entry):
    bundle = entry['bundle']; frozen = bundle['projection']['result']['_material']
    config = bundle['configuration']['config']; contract = bundle['configuration'].get('figure_contract', 1)
    filename = entry['task_id'] + '.json'
    raw_sha, payload_sha, expected_sha, prompt_sha = GOLDEN_BASELINE[filename]
    assert sha256((GOLDEN_DIR / filename).read_bytes()).hexdigest() == raw_sha
    assert digest(frozen['payload']) == payload_sha
    assert digest(frozen['expected']) == expected_sha
    assert presentation.renderer_for({'figure_contract': contract}) == bundle['figure']['engine']['id']
    if config['figure_kind'] in ('line', 'bar', 'violin'):
        payload, expected = material.projection_material(config, frozen['payload']['observations'], bundle['projection']['result'], frozen_fields(bundle))
    else:
        payload, expected = deepcopy(frozen['payload']), deepcopy(frozen['expected'])
        notes = payload.pop('presentation')['statistical_notes']; expected.pop('presentation')
        suffix = ' '.join(notes)
        assert payload['labels']['caption'].endswith(suffix)
        payload['labels']['caption'] = payload['labels']['caption'][:-len(suffix)].rstrip() if suffix else payload['labels']['caption']
        expected['caption'] = payload['labels']['caption']
    payload, expected = presentation.enrich_material(payload, expected, config=config, result=bundle['result'], projection=bundle['projection']['result'], fields=frozen_fields(bundle), contract=contract)
    assert payload == frozen['payload']
    assert expected == frozen['expected']
    assert digest(payload) == payload_sha and digest(expected) == expected_sha
    assert sha256(prompts.instructions_for(payload).encode()).hexdigest() == prompt_sha


def bar(stat='count', *, language='en', error_bars='none', n=2, author=''):
    config = FigureConfig(figure_kind='bar', language=language, projection={'category_column': 'A', 'y_column': 'B' if stat == 'mean' else None, 'bar_stat': stat, 'error_bars': error_bars}, style={'caption': author}).model_dump()
    point = {'category': 'A', 'n': n, 'denominator': n if stat == 'proportion' else None, 'value': None if n == 0 else .5 if stat == 'proportion' else 2., 'sd': 1. if n >= 2 and error_bars == 'sd' else None, 'reason': 'no_valid_values' if n == 0 else 'insufficient_n_for_sd' if n < 2 and error_bars == 'sd' else None}
    projection = {'audit': {'valid_n': n, 'excluded_n': 2}, 'series': [{'group': None, 'points': [point]}]}
    rows = [{'category': 'A', 'y': 2., 'group': None}] * n
    payload, expected = material.projection_material(config, rows, projection, figure_contract=4)
    return presentation.enrich_material(payload, expected, config=config, result={}, projection=projection, fields={}, contract=4), config


@pytest.mark.parametrize('language', ['en', 'zh-CN'])
def test_count_caption_only_counts_and_applicable_limitations(language):
    (payload, expected), _ = bar(language=language)
    caption = payload['labels']['caption']
    assert all(term not in caption.lower() for term in ('proportion', 'mean', 'sd', '比例', '均值'))
    assert ('2 valid records, 2 excluded' if language == 'en' else '有效记录 2，排除 2') in caption
    assert ('causality' if language == 'en' else '因果') in caption
    assert expected['statistics']['series'][0]['points'][0]['n'] == 2
    assert payload['presentation']['schema_version'] == 3


def test_proportion_denominator_and_mean_sd_reasons_preserve_numeric_contract():
    (payload, expected), _ = bar('proportion')
    assert 'valid within-group records' in payload['labels']['caption']
    assert '0–1' in payload['labels']['caption'] and 'SD' not in payload['labels']['caption']
    assert expected['statistics']['series'][0]['points'][0]['denominator'] == 2
    for n, reason in [(0, 'no_valid_values'), (1, 'insufficient_n_for_sd'), (2, None)]:
        (payload, expected), _ = bar('mean', error_bars='sd', n=n)
        assert 'Sample SD' in payload['labels']['caption']
        assert 'fewer than two valid records' in payload['labels']['caption']
        assert 'no valid numeric values' in payload['labels']['caption']
        assert expected['statistics']['series'][0]['points'][0]['reason'] == reason
    (payload, _), _ = bar('mean', n=0)
    assert 'mean is unavailable with no valid numeric values' in payload['labels']['caption']
    assert 'SD' not in payload['labels']['caption']


@pytest.mark.parametrize('language', ['en', 'zh-CN'])
@pytest.mark.parametrize('aggregation', ['unique', 'mean'])
def test_line_system_notes_have_one_owner_and_author_remains_literal(language, aggregation):
    author = 'Known missing values break lines; no interpolation. 重复值规则：unique; {{literal}}.'
    config = FigureConfig(figure_kind='line', language=language, projection={'x_column': 'A', 'y_column': 'B', 'aggregation': aggregation}, style={'caption': author}).model_dump()
    projection = {'audit': {'valid_n': 3, 'excluded_n': 1}, 'series': [{'group': None, 'points': [{'x': 1., 'y': 2., 'n': 1, 'missing': 0}, {'x': 2., 'y': None, 'n': 0, 'missing': 1}]}]}
    payload, expected = material.projection_material(config, [{'x': 1., 'y': 2.}, {'x': 2., 'y': None}], projection, figure_contract=4)
    payload, expected = presentation.enrich_material(payload, expected, config=config, result={}, projection=projection, fields={}, contract=4)
    caption = payload['labels']['caption']
    assert caption.endswith(author)
    system = caption[:-len(author)].rstrip()
    assert system.count('no interpolation' if language == 'en' else '不插值') == 1
    assert system.count('independent participants' if language == 'en' else '独立人数') == 1
    assert system.count('arithmetic mean' if language == 'en' and aggregation == 'mean' else 'unique' if language == 'en' else '算术均值' if aggregation == 'mean' else '保持唯一') == 1
    assert expected['statistics']['series'] == projection['series']
    for note in payload['presentation']['statistical_notes']:
        assert system.count(note) == 1


def test_renderer_and_presentation_pairings_fail_closed():
    pairs = [('openai_figure_workbench_v1', None), ('openai_figure_workbench_v2', 1), ('openai_figure_workbench_v3', 2), ('openai_figure_workbench_v4', 3)]
    for renderer, schema in pairs:
        presentation.validate_renderer_presentation(renderer, None if schema is None else {'schema_version': schema})
        for wrong in [None, True, 1., '2', 1, 2, 3, 4]:
            if type(wrong) is int and wrong == schema or wrong is None and schema is None:
                continue
            with pytest.raises(StorageError):
                presentation.validate_renderer_presentation(renderer, None if wrong is None else {'schema_version': wrong})
    assert presentation.V3_RENDERER == 'openai_figure_workbench_v3'
    assert presentation.renderer_for({'figure_contract': 4}) == 'openai_figure_workbench_v4'
    with pytest.raises(StorageError):
        presentation.validate_renderer_presentation('unknown', {'schema_version': 3})


@pytest.mark.parametrize('key,required', [('correlation_heatmap:en', ['minus signs', 'longest formatted cell', 'cell bounding boxes']), ('kaplan_meier:en', ['1.25', 'risk table has its own region', 'non-overlapping text bounding boxes'])])
def test_layout_rules_are_only_in_new_contract_and_data_style_unchanged(key, required):
    entry = next(e for e in historical() if e['key'] == key)
    b = entry['bundle']; frozen = b['projection']['result']['_material']
    payload, expected = deepcopy(frozen['payload']), deepcopy(frozen['expected'])
    notes = payload.pop('presentation')['statistical_notes']; expected.pop('presentation')
    suffix = ' '.join(notes); payload['labels']['caption'] = payload['labels']['caption'][:-len(suffix)].rstrip(); expected['caption'] = payload['labels']['caption']
    new, wanted = presentation.enrich_material(payload, expected, config=b['configuration']['config'], result=b['result'], projection=b['projection']['result'], fields=frozen_fields(b), contract=4)
    instruction = prompts.instructions_for(new)
    for text in required:
        assert text in instruction
        assert text not in prompts.instructions_for(frozen['payload'])
    assert wanted['statistics'] == frozen['expected']['statistics']
    assert new['plot_config'] == frozen['payload']['plot_config']
    assert new['presentation']['axes'] == frozen['payload']['presentation']['axes']
    assert new['presentation']['legend'] == frozen['payload']['presentation']['legend']
    assert 'Render labels.caption exactly once' in instruction
    assert '2400' not in instruction  # Uses exact frozen requested dimensions, no hardcoded rescale.


@pytest.mark.parametrize('version,hashes', [
    (1, ('447aa1f7d587814d9c6bdeb4c31b3367f367e57672002a18a2911bfe1648b027', '3226cb1e200363f3207e7d74ef2163d7b341530a39fa563c32b28cee74cbfd2b', '080de24310b95d8e95b8e20570a3250d4f2b8807dc8140748927ed0b01a256f7')),
    (2, ('0de27dbf184bd07dc553c04004f99fd898b5f9fd0f36cd9117298851453847d4', '650bcef5e2151c986a670868584d312d569666ac5a5f3efc1d586b5b800aa342', 'b3e9d93ec9fb6cab1bc3615da64641cffdaf211a78ca6208dbda085928061894')),
    (3, ('549e1a4b60617a594cb6df32baa22b603cbcb5b5f43de30232a0b56a1fe78b12', '1b939c0678b98b6322ebee75f5dd82f1d4da1d85d8335f8a30e0875bb043bad7', '07fecbd98224b1554d752c50c3fed3e61db85736300638de42df81cb71cc5981')),
])
def test_v1_to_v3_bytes_against_unmodified_checkout_baseline(version, hashes):
    from tests.domain.test_batch06_presentation import materials
    payload, expected, kwargs = materials()
    if version > 1:
        payload, expected = presentation.enrich_material(payload, expected, contract=version, **kwargs)
    assert (digest(payload), digest(expected), sha256(prompts.instructions_for(payload).encode()).hexdigest()) == hashes


def test_actual_old_english_line_with_empty_author_has_no_new_duplicate_caption():
    b = next(e for e in historical() if e['key'] == 'line:en')['bundle']
    config = b['configuration']['config']; frozen = b['projection']['result']['_material']
    assert config['style']['caption'] == ''
    payload, expected = material.projection_material(config, frozen['payload']['observations'], b['projection']['result'], frozen_fields(b), figure_contract=4)
    payload, expected = presentation.enrich_material(payload, expected, config=config, result=b['result'], projection=b['projection']['result'], fields=frozen_fields(b), contract=4)
    assert payload['labels']['caption'].count('Descriptive projection') == 1
    assert payload['labels']['caption'].count('no interpolation') == 1
    assert payload['labels']['caption'].count('independent participants') == 1
    assert expected['statistics'] == frozen['expected']['statistics']
    assert payload['observations'] == frozen['payload']['observations']


@pytest.mark.parametrize('bad', [True, 1., '3', 0, 4, None])
def test_prompt_rejects_invalid_presentation_schemas(bad):
    with pytest.raises(StorageError):
        prompts.instructions_for({'figure_kind': 'line', 'presentation': {'schema_version': bad}})


@pytest.mark.parametrize('bad', [None, [], True, '3'])
def test_prompt_rejects_invalid_presentation_containers(bad):
    with pytest.raises(StorageError) as exc:
        prompts.instructions_for({'figure_kind': 'line', 'presentation': bad})
    assert exc.value.code == 'task_source_conflict'


@pytest.mark.parametrize('bad', [None, {}, [], True, 4])
def test_renderer_validator_rejects_non_engine_values(bad):
    with pytest.raises(StorageError):
        presentation.validate_renderer_presentation(bad, {'schema_version': 3})


@pytest.mark.parametrize('version', [1, 2, 3, 4])
def test_calculate_forwards_frozen_source_contract_without_numerical_execution(monkeypatch, version):
    from types import SimpleNamespace
    from app.domain.figure_workbench import sources
    config = FigureConfig(figure_kind='bar', language='zh-CN', projection={'category_column': 'A'}).model_dump()
    projection = {'audit': {'valid_n': 2, 'excluded_n': 0}, 'series': [{'group': None, 'points': []}]}
    monkeypatch.setattr(sources, 'population_rows', lambda *_: ({2, 3}, []))
    monkeypatch.setattr(sources, 'projection_rows', lambda *_args, **_kwargs: [{'category': 'A'}, {'category': 'B'}])
    monkeypatch.setattr(sources, 'fields_for', lambda _: [])
    def forbidden(*args, **kwargs):
        pytest.fail('Frozen source replay must not call the numeric worker')
    monkeypatch.setattr(sources, 'compute_bounded', forbidden)
    _, payload, _ = sources.calculate(None, 'p', 'f', {}, SimpleNamespace(row_count=2), config, frozen=projection, figure_contract=version)
    assert ('比例' in payload['labels']['caption']) == (version < 4)


def test_only_new_save_persists_contract_four_and_digest(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from app.adapters import figure_workbench_store as store_module
    config = FigureConfig(figure_kind='bar', language='zh-CN', projection={'category_column': 'A'})
    result = {'source': {'kind': 'prepared_dataset_version'}, 'analysis_plan': {'sha256': 'plan'}}
    old = {'source': deepcopy(result['source']), 'figure_contract': 3}
    unchanged = deepcopy(old)
    writes = []
    database = SimpleNamespace(execute=lambda sql, params: writes.append((sql, params)))
    store = store_module.FigureWorkbenchStore.__new__(store_module.FigureWorkbenchStore)
    store.assets = object()
    store.tasks = SimpleNamespace(user_id='owner', connection=lambda **_: nullcontext(database), require_project=lambda *_: None)
    monkeypatch.setattr(store_module, 'load_source', lambda *_: (result, None))
    def inserted(*args):
        params = next(params for sql, params in writes if 'INSERT INTO figure_config_versions' in sql)
        return {'sha256': params[6], 'config_json': params[7].obj, 'source_json': params[8].obj}
    monkeypatch.setattr(store, '_version', inserted)
    monkeypatch.setattr(store, '_entry', lambda _db, row: row)
    saved = store.save('p', 'f', 'run', SimpleNamespace(config=config, configuration_id=None))
    assert saved['source_json']['figure_contract'] == 4
    assert saved['source_json']['source'] == result['source']
    assert saved['source_json']['analysis_plan'] == result['analysis_plan']
    assert saved['sha256'] == digest({'config': config.model_dump(), 'source': saved['source_json']})
    assert old == unchanged
