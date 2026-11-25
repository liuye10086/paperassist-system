import json
import os
import subprocess
from dataclasses import replace

import pytest
from pydantic import ValidationError

from app.core.exceptions import StorageError
from app.domain.runtime_skills import registry, runtime


@pytest.fixture(autouse=True)
def use_repository_pack(monkeypatch):
    for name in ('PAPERASSIST_SKILLS_DIR', 'PAPERASSIST_SKILL_WORKFLOWS', 'PAPERASSIST_SKILLS_MANIFEST_SHA256'):
        monkeypatch.delenv(name, raising=False)


def skill(root, name='sample', *, version='1.0.0', body='Use the selected evidence.', header=None):
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    content = header or (
        f'name: {name}\ndescription: An approved rule\n'
        f'metadata:\n  category: writing\n  version: "{version}"'
    )
    path = directory / 'SKILL.md'
    path.write_bytes(f'---\n{content}\n---\n\n{body}\n'.encode())
    return path


def test_installed_pack_is_deterministic_and_freezes_only_scoped_text(monkeypatch):
    root = runtime.skills_root()
    pack = registry.check_release(root)
    assert tuple(pack.manifest.skills) == (
        'bulk-result-reading', 'citation-verification', 'narrative-review', 'research-article', 'scientific-writing',
        'single-cell-composition-reading', 'statistical-reading', 'thesis-writing',
    )
    monkeypatch.setenv('PAPERASSIST_SKILL_WORKFLOWS', 'sci_narrative_review,bulk_fixed_preview')
    first = runtime.load_step(runtime.SCI_NARRATIVE_REVIEW, 'initial_draft').freeze_writing()
    second = runtime.load_step(runtime.SCI_NARRATIVE_REVIEW, 'initial_draft').freeze_writing()
    assert first == second
    assert first.trace.manifest_sha256 == pack.sha256
    assert [ref.name for ref in first.trace.skills] == [
        'scientific-writing', 'narrative-review', 'citation-verification',
    ]
    assert [ref.path for skill_ref in first.trace.skills for ref in skill_ref.resources] == [
        'references/evidence-scope.md',
    ]
    assert 'abstract' in first.instructions and 'bulk-result-reading' not in first.instructions
    bulk = runtime.load_step(runtime.BULK_FIXED_PREVIEW, 'qc_pca')
    assert [ref.name for ref in bulk.trace.skills] == ['bulk-result-reading']
    assert bulk.trace.tool.id == 'bulk_plot_data'
    assert bulk.trace.manifest_sha256 == first.trace.manifest_sha256


def test_statistical_step_freezes_only_the_fixed_figure_rules(monkeypatch):
    monkeypatch.setenv('PAPERASSIST_SKILL_WORKFLOWS', 'statistical_explanation')
    assert runtime.is_enabled('statistical_explanation')
    loaded = runtime.load_step('statistical_explanation', 'explain_fixed_figure')
    assert loaded.trace.tool.id == 'figure_explanation'
    assert [ref.name for ref in loaded.trace.skills] == ['statistical-reading']
    assert 'six-section' in loaded.instructions and 'evidence placeholders' in loaded.instructions


def test_frozen_snapshot_replays_without_configuration_and_rejects_changed_text(monkeypatch, tmp_path):
    monkeypatch.setenv('PAPERASSIST_SKILL_WORKFLOWS', 'sci_narrative_review')
    frozen = runtime.load_step(runtime.SCI_NARRATIVE_REVIEW, 'initial_draft').freeze_writing().model_dump(mode='json')
    monkeypatch.setenv('PAPERASSIST_SKILL_WORKFLOWS', '')
    monkeypatch.setenv('PAPERASSIST_SKILLS_DIR', str(tmp_path / 'missing'))
    assert runtime.WritingSkillsSnapshot.model_validate(frozen).model_dump(mode='json') == frozen
    with pytest.raises(ValidationError):
        runtime.WritingSkillsSnapshot.model_validate({**frozen, 'instructions': 'changed'})
    with pytest.raises(StorageError) as disabled:
        runtime.load_step(runtime.SCI_NARRATIVE_REVIEW, 'initial_draft')
    assert (disabled.value.status, disabled.value.code) == (404, 'runtime_skills_disabled')
    monkeypatch.setenv('PAPERASSIST_SKILL_WORKFLOWS', 'sci_narrative_review')
    with pytest.raises(StorageError) as missing:
        runtime.load_step(runtime.SCI_NARRATIVE_REVIEW, 'initial_draft')
    assert (missing.value.status, missing.value.code) == (503, 'runtime_skills_unavailable')
    assert str(tmp_path) not in missing.value.message


@pytest.mark.parametrize('header', [
    'name: sample\ndescription: [bad',
    'name: sample\ndescription: rule\nmetadata:\n  category: writing\n  version: "1.0.0"\n  version: "2.0.0"',
    'name: sample\ndescription: rule\nmetadata:\n  category: &x writing\n  version: *x',
    'name: sample\nmetadata:\n  category: writing\n  version: "1.0.0"',
    'name: sample\ndescription: rule\nmetadata:\n  category: writing\n  version: "local"',
    'name: sample\ndescription: rule\nmetadata:\n  category: writing\n  version: 1',
    'name: another\ndescription: rule\nmetadata:\n  category: writing\n  version: "1.0.0"',
])
def test_discovery_rejects_invalid_frontmatter(tmp_path, header):
    skill(tmp_path, header=header)
    with pytest.raises(registry.SkillError):
        registry.publish(tmp_path)


def test_manifest_detects_drift_and_enforces_version_history(tmp_path):
    path = skill(tmp_path)
    first = registry.publish(tmp_path)
    assert registry.check_release(tmp_path).sha256 == first.sha256
    path.write_bytes(path.read_bytes().replace(b'\n', b'\r\n'))
    assert registry.check_release(tmp_path).sha256 == first.sha256
    skill(tmp_path, body='Other instructions.')
    with pytest.raises(registry.SkillError, match='digest'):
        registry.check_release(tmp_path)
    with pytest.raises(registry.SkillError, match='immutable'):
        registry.publish(tmp_path)
    skill(tmp_path, version='1.1.0', body='Other instructions.')
    new = registry.publish(tmp_path)
    assert new.sha256 != first.sha256
    assert 'sample@1.0.0' in new.manifest.history
    skill(tmp_path, body='Third instructions.')
    with pytest.raises(registry.SkillError, match='immutable'):
        registry.publish(tmp_path)


def test_manifest_pin_and_file_allowlist(tmp_path):
    path = skill(tmp_path)
    refs = path.parent / 'references'
    refs.mkdir()
    (refs / 'scope.md').write_bytes(b'\x23 Read from the fixed scope\n')
    pack = registry.publish(tmp_path)
    checked = registry.check_release(tmp_path, expected_sha256=pack.sha256)
    assert checked.resource('sample', 'references/scope.md')[1].sha256
    with pytest.raises(registry.SkillError, match='pin'):
        registry.check_release(tmp_path, expected_sha256='f' * 64)
    for value in ('../SKILL.md', 'references/../SKILL.md', r'references\scope.md', '/etc/hosts'):
        with pytest.raises(registry.SkillError):
            checked.resource('sample', value)
    unlisted = refs / 'unlisted.md'
    unlisted.write_text('A new file requires a manifest update.', encoding='utf-8')
    with pytest.raises(registry.SkillError):
        checked.resource('sample', 'references/unlisted.md')
    with pytest.raises(registry.SkillError):
        registry.check_release(tmp_path)
    unlisted.rename(refs / 'executable.py')
    with pytest.raises(registry.SkillError):
        registry.publish(tmp_path)


def test_release_rejects_links_before_reading_files(tmp_path):
    pack_root = tmp_path / 'pack'
    path = skill(pack_root)
    refs = path.parent / 'references'
    refs.mkdir()
    outside = tmp_path / 'outside.md'
    outside.write_text('Outside input.', encoding='utf-8')
    try:
        (refs / 'link.md').symlink_to(outside)
    except OSError:
        if os.name != 'nt':
            raise
        # A directory junction uses no symlink privilege on Windows.
        outside_dir = tmp_path / 'external'
        outside_dir.mkdir()
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(refs / 'link'), str(outside_dir)],
                       check=True, capture_output=True)
    with pytest.raises(registry.SkillError, match='link'):
        registry.publish(pack_root)


def test_release_rejects_large_resources_and_duplicate_manifest_keys(tmp_path):
    path = skill(tmp_path)
    refs = path.parent / 'references'
    refs.mkdir()
    oversized = refs / 'long.md'
    oversized.write_bytes(b'x' * (registry.MAX_FILE_BYTES + 1))
    with pytest.raises(registry.SkillError, match='size'):
        registry.publish(tmp_path)
    oversized.unlink()
    registry.publish(tmp_path)
    manifest = tmp_path / registry.MANIFEST_FILENAME
    raw = manifest.read_text(encoding='utf-8')
    manifest.write_text(raw.replace('"schema_version":1', '"schema_version":1,"schema_version":1'), encoding='utf-8')
    with pytest.raises(registry.SkillError, match='duplicate'):
        registry.open_release(tmp_path)


def test_step_order_deduplicates_dependencies_and_rejects_invalid_plans():
    pack = registry.open_release(runtime.skills_root())
    plan = runtime.STEPS[runtime.SCI_NARRATIVE_REVIEW, 'initial_draft']
    assert runtime.resolve_step(pack.manifest, plan, runtime.SKILLS) == (
        'scientific-writing', 'narrative-review', 'citation-verification',
    )
    specs = dict(runtime.SKILLS)
    specs['scientific-writing'] = replace(specs['scientific-writing'], requires=('narrative-review',))
    with pytest.raises(registry.SkillError, match='cyclic'):
        runtime.resolve_step(pack.manifest, plan, specs)
    with pytest.raises(registry.SkillError, match='missing'):
        runtime.resolve_step(pack.manifest, replace(plan, skills=('unknown-skill',)), runtime.SKILLS)
    with pytest.raises(registry.SkillError, match='tool'):
        runtime.resolve_step(pack.manifest, replace(plan, tool='shell'), runtime.SKILLS)
    specs = dict(runtime.SKILLS)
    specs['narrative-review'] = replace(specs['narrative-review'], conflicts=('citation-verification',))
    with pytest.raises(registry.SkillError, match='conflict'):
        runtime.resolve_step(pack.manifest, plan, specs)


def test_pack_loading_is_stage_scoped(monkeypatch, tmp_path):
    root = tmp_path / 'SKILLS'
    for directory in runtime.skills_root().iterdir():
        if not directory.is_dir():
            continue
        for path in directory.rglob('*'):
            if path.is_file():
                target = root / path.relative_to(runtime.skills_root())
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())
    manifest_path = root / registry.MANIFEST_FILENAME
    manifest_path.write_bytes((runtime.skills_root() / registry.MANIFEST_FILENAME).read_bytes())
    monkeypatch.setenv('PAPERASSIST_SKILLS_DIR', str(root))
    monkeypatch.setenv('PAPERASSIST_SKILL_WORKFLOWS', 'bulk_fixed_preview,sci_narrative_review')
    (root / 'scientific-writing' / 'SKILL.md').write_bytes(b'edited after publication')
    assert runtime.load_step(runtime.BULK_FIXED_PREVIEW, 'qc_pca').trace.workflow == 'bulk_fixed_preview'
    with pytest.raises(StorageError, match='技能包'):
        runtime.load_step(runtime.SCI_NARRATIVE_REVIEW, 'initial_draft')
    monkeypatch.setenv('PAPERASSIST_SKILLS_MANIFEST_SHA256', 'f' * 64)
    with pytest.raises(StorageError, match='技能包'):
        runtime.load_step(runtime.BULK_FIXED_PREVIEW, 'qc_pca')


def test_unrecognized_workflow_flag_cannot_enable_a_step(monkeypatch):
    monkeypatch.setenv('PAPERASSIST_SKILL_WORKFLOWS', 'bulk_fixed_preview,unknown')
    with pytest.raises(StorageError) as error:
        runtime.load_step(runtime.BULK_FIXED_PREVIEW, 'qc_pca')
    assert error.value.code == 'runtime_skills_unavailable'
    assert not runtime.is_enabled('unknown')


def test_malformed_manifest_fails_only_the_new_step(monkeypatch, tmp_path, caplog):
    (tmp_path / registry.MANIFEST_FILENAME).write_bytes(b'{"schema_version":' + b'9' * 5000 + b'}')
    monkeypatch.setenv('PAPERASSIST_SKILLS_DIR', str(tmp_path))
    monkeypatch.setenv('PAPERASSIST_SKILL_WORKFLOWS', 'bulk_fixed_preview')
    runtime.log_configured_installation()
    assert 'skill release manifest is invalid' in caplog.text
    with pytest.raises(StorageError) as error:
        runtime.load_step(runtime.BULK_FIXED_PREVIEW, 'qc_pca')
    assert error.value.code == 'runtime_skills_unavailable'


def test_publish_reports_invalid_workflow_before_overwriting_lock(tmp_path):
    skill(tmp_path)
    installed = registry.publish(tmp_path)
    skill(tmp_path, version='2.0.0')
    with pytest.raises(registry.SkillError, match='missing'):
        registry.publish(tmp_path, verify=runtime.verify_steps)
    assert registry.open_release(tmp_path).sha256 == installed.sha256


def test_allowed_tools_in_document_are_only_metadata(tmp_path):
    source = runtime.skills_root() / 'bulk-result-reading' / 'SKILL.md'
    installed = tmp_path / 'bulk-result-reading' / 'SKILL.md'
    installed.parent.mkdir()
    installed.write_bytes(source.read_bytes().replace(b'\nmetadata:', b'\nallowed-tools: Bash\nmetadata:'))
    release = registry.publish(tmp_path)
    assert release.manifest.skills['bulk-result-reading'].header.allowed_tools == 'Bash'
    order = runtime.resolve_step(release.manifest, runtime.STEPS[runtime.BULK_FIXED_PREVIEW, 'qc_pca'], runtime.SKILLS)
    assert order == ('bulk-result-reading',)
    assert runtime.STEPS[runtime.BULK_FIXED_PREVIEW, 'qc_pca'].tool == 'bulk_plot_data'
