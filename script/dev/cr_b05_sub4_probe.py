"""Bind new feature/integration probes to unchanged, accepted scientific evidence."""
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

FEATURE_CHECKS = ('feature_sequence', 'feature_structure', 'feature_figures')
INTEGRATION_CHECKS = ('integration_matching', 'integration_correlation', 'integration_concordance', 'integration_figures')


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def delta_checks(runtime, actual, parent, child_keys, parent_key):
    if actual.get('runtime_identity') != runtime:
        raise ValueError('New scientific probe identity differs')
    child = actual.get('checks', {})
    proof = parent.get('checks', {})
    if (set(child) != set(child_keys) or set(proof) != {parent_key}
            or any(value is not True for value in [*child.values(), *proof.values()])):
        raise ValueError('New scientific checks are incomplete')
    return {**child, **proof}


def reused_science(control, image, inventory):
    baseline_path = control.RUNTIME / 'accepted-final-engine-baseline.json'
    baseline = read(baseline_path)
    compatibility = read(control.RUNTIME / 'dependencies/compatibility.json')
    if baseline['source_image'] != compatibility['base_image'] or baseline['source_image'] != control.BASE_IMAGE_ID:
        raise ValueError('Accepted baseline image differs')
    inspected = json.loads(control.worker_stack.docker([
        'image', 'inspect', control.BASE_IMAGE_ID, compatibility['dependency_image'], image]))
    accepted, dependency, final = [value['RootFS']['Layers'] for value in inspected]
    if dependency[:len(accepted)] != accepted or final[:len(dependency)] != dependency:
        raise ValueError('Accepted dependency layers were replaced')
    packages = inventory['packages']
    old_packages = baseline['packages']['paperassist-bio-insights']
    if (any(packages.get(key) != value for key, value in old_packages.items())
            or {key: value for key, value in packages.items() if key not in old_packages} != compatibility['added']):
        raise ValueError('Unexpected scientific dependency change')
    old_lock = base64.b64decode(baseline['locks']['requirements-bio-insights.lock.txt']['base64'])
    old_lines = [line for line in old_lock.splitlines() if line.strip()]
    new_lines = [line for line in (control.ROOT / 'backend/requirements-bio-insights.lock.txt').read_bytes().splitlines() if line.strip()]
    if (new_lines[:len(old_lines)] != old_lines or sha(control.ROOT / 'backend/requirements-bio.lock.txt') != baseline['locks']['requirements-bio.lock.txt']['sha256']):
        raise ValueError('Accepted lock entries changed')
    kernels = ('comparison', 'counts_model', 'enrichment', 'quantitative', 'quantitative_inputs',
               'quantitative_figures', 'qpcr', 'qpcr_figures', 'microbiome', 'microbiome_figures')
    protected = ['adapters/bio_insights_engine/' + name + '.py' for name in kernels]
    protected += [name for name in baseline['files'] if name.startswith('adapters/bio_engine/')]
    protected += ['domain/comparison/kernel.py', 'domain/correlation/kernel.py']
    unchanged = {name: sha(control.ROOT / 'backend/app' / name) for name in protected}
    changed = [name for name, value in unchanged.items() if baseline['files'].get(name) != value]
    if changed:
        raise ValueError('Accepted numerical implementation changed: ' + str(changed))
    return dict(source_image=control.BASE_IMAGE_ID, target_image=image,
        baseline_sha256=sha(baseline_path), unchanged_science_files=unchanged,
        accepted_layers=accepted, dependency_layers=dependency, added_packages=compatibility['added'],
        existing_package_versions_changed={}, old_lock_entries_unchanged=True,
        old_scientific_checks_executed=False)


def bind(inventory_path, feature_path, feature_parent_path, integration_path, integration_parent_path):
    import os
    os.environ['PAPERASSIST_CR_B05_SUBPACKAGE'] = '4'
    import cr_b05_runner as control
    from cr_b05_probe import image_identity, save
    state = control.read_state()
    control.configure(state)
    image = control.worker_stack.docker(['image', 'inspect', '--format', '{{.Id}}', control.WORKER_IMAGE]).strip()
    identity = image_identity(image)
    inventory = read(inventory_path)
    provenance = reused_science(control, image, inventory)
    from app.domain.bio_insights.settings import engine_code_digest, engine_lock_digest, BioInsightsLimits
    from app.domain.bioinformatics.tabular_settings import engine_code_digest as tabular_digest
    environment = {key: inventory[key] for key in ('python', 'packages', 'native_libraries', 'lock_sha256', 'limits')}
    runtime = dict(available=True, engine_version='bio_insights_v1.0.0', code_digest=engine_code_digest(),
                   lock_sha256=engine_lock_digest(), environment_digest=digest(environment))
    if inventory['runtime_identity'] != runtime or inventory['limits'] != BioInsightsLimits().model_dump():
        raise ValueError('Current image inventory differs from the approved runtime')
    feature = read(feature_path)
    integration = read(integration_path)
    checks = delta_checks(runtime, feature, read(feature_parent_path), FEATURE_CHECKS, 'feature_parent_validation')
    checks.update(delta_checks(runtime, integration, read(integration_parent_path), INTEGRATION_CHECKS, 'integration_parent_validation'))
    previous = control.ROOT / 'script/.runtime/client-requirements-b05-sub3'
    old = read(previous / 'runtime-gate.json')
    bio = read(previous / 'bio-runtime-gate.json')
    single = read(previous / 'single-cell-runtime-gate.json')
    if (old['status'] != 'passed' or bio['gate_status'] != 'passed'
            or bio['code_digest'] != identity['bio_code_digest'] or bio['lock_sha256'] != identity['bio_lock_digest']):
        raise ValueError('Accepted sidecar evidence cannot be inherited')
    if (single['code_digest'] != bio['code_digest'] or single['environment_digest'] != bio['environment_digest']):
        raise ValueError('Single-cell evidence identity differs')
    old_native = {value['filepath']: value['sha256'] for value in old['native_libraries']}
    new_native = {value['filepath']: value['sha256'] for value in inventory['native_libraries']}
    if old_native != new_native:
        raise ValueError('Accepted native library identity changed')
    evidence_paths = [inventory_path, feature_path, feature_parent_path, integration_path, integration_parent_path]
    provenance.update(source_report=str(previous / 'runtime-gate.json'),
        source_report_sha256=sha(previous / 'runtime-gate.json'),
        new_evidence={str(path): sha(path) for path in evidence_paths}, reused_checks=list(old['checks']))
    stamp = datetime.now(timezone.utc).isoformat()
    report = {**old, **environment, 'code_digest': runtime['code_digest'],
        'tabular_code_digest': tabular_digest(), 'image_digest': image, 'verified_at': stamp,
        'checks': {**old['checks'], **checks}, 'reused_checks': list(old['checks']),
        'validation_scope': 'accepted numerical evidence reused; new feature and integration workers checked',
        'reuse_provenance': provenance, 'actual_delta_evidence': dict(feature=feature, integration=integration),
        'resource_observation_source': 'legacy peak/counter fields are accepted observations; new resources are in actual_delta_evidence'}
    image_identity(image)
    save(control.GATE, report)
    save(control.BIO_GATE, {**bio, 'image_digest': image, 'verified_at': stamp})
    save(control.SINGLE_CELL_GATE, single)
    save(control.RUNTIME / 'bio-gate-reuse.json', dict(source_image=control.BASE_IMAGE_ID,
        target_image=image, source_report_sha256=sha(previous / 'bio-runtime-gate.json'),
        validation_scope='unchanged bio-engine bytes, lock and retained dependency layers; no scientific re-execution'))
    generation = 'r' + image[7:19]
    state.update(worker_image_id=image, service_generation=generation,
        network_profile=dict(profile='sub4-explicit-ipam', generation=generation, image_digest=image))
    save(control.STATE, control.validate_state(state))
    return dict(image=image, new_checks=list(checks), reused_checks=list(old['checks']))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('inventory', 'feature', 'feature_parent', 'integration', 'integration_parent'):
        parser.add_argument(name)
    args = parser.parse_args()
    print(json.dumps(bind(args.inventory, args.feature, args.feature_parent, args.integration, args.integration_parent)))
