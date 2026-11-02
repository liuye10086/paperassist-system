"""Verify each new formal package once; reuse successful offline operations."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'script'), str(ROOT / 'script/dev'), str(ROOT / 'backend')]
from verify_cr_b05_sub4_acceptance import Acceptance
import verify_cr_b05_reproduction as shared

PACKAGES = {
    'features': ('sequence-structure', 'features', 'recompute'),
    'integration': ('matched-omics', 'integration', 'recompute'),
    'network': ('matched-omics', 'network', 'render'),
    'evidence': ('matched-omics', 'evidence-figure', 'render'),
}


def retained_operation(acceptance, label, kind, operation, acquired):
    root, package, receipt = acquired
    key = label + '-' + kind
    attempts = set(root.glob('attempt-' + operation + '-*'))
    saved = acceptance.record.get('reproductions', {}).get(key)
    if saved and saved.get('operation') == operation:
        attempts.add(Path(saved['evidence']))
    if not attempts:
        return None
    current = acceptance.record['results'][key]
    image = acceptance.state['worker_image_id']
    try:
        metadata = shared.checked_package_metadata(package, receipt['manifest_sha256'])
        assert receipt['result_id'] == metadata['identity']['result_version_id'] == current['id']
        assert metadata['identity']['project_id'] == current['project_id']
        assert metadata['formal_manifest_sha256'] == current['manifest_sha256']
        for attempt in sorted(attempts):
            assert attempt.resolve().parent == root.resolve()
            request = json.loads((attempt / 'request.json').read_bytes())
            command = request['command']
            assert request['image'] == image == command[command.index('--entrypoint') + 2]
            assert 'type=bind,source=' + str(package) + ',target=/package,readonly' in command
            assert command[-6:] == ['/package/reproduce.py', operation, '--output', '/attempt/output',
                                    '--manifest-sha256', receipt['manifest_sha256']]
            completion = json.loads((attempt / 'completion.json').read_bytes())
            report = json.loads((attempt / 'output/operation.json').read_bytes())
            assert completion['exit_code'] == 0
            assert report['operation'] == operation and report['status'] == 'completed'
            assert report['comparison']['passed'] is True
            assert report['execution']['child_peak_rss_bytes'] < 2 * 1024**3
            assert report['execution']['violation'] is None
    except (OSError, KeyError, TypeError, ValueError, AssertionError) as exc:
        raise RuntimeError('Retained reproduction attempt is incomplete or differs; inspect without resubmitting: '
                           + str(root)) from exc
    acceptance.record.setdefault('reproductions', {})[key] = dict(operation=operation, status='passed',
        evidence=str(attempt), manifest_sha256=receipt['manifest_sha256'],
        peak_rss_bytes=report['execution']['child_peak_rss_bytes'])
    acceptance.save()
    return dict(status='passed', operation=operation, evidence=str(attempt), reused=True)


def execute(acceptance, selected, action):
    label, kind, operation = PACKAGES[selected]
    if action not in ('verify', operation):
        raise ValueError('Choose verify or ' + operation + ' for this package')
    root = acceptance.output / 'reproduction' / (label + '-' + kind)
    current = acceptance.record['results'][label + '-' + kind]
    if (root / 'verification.json').exists():
        receipt = json.loads((root / 'acquisition.json').read_bytes())
        if receipt['result_id'] != current['id']:
            raise ValueError('Saved verification belongs to a different fixed result')
        acquired = root, root / 'package', receipt
    else:
        acquired = shared.acquire(acceptance, label, kind)
    if action == 'verify':
        return dict(status='passed', evidence=str(root / 'verification.json'))
    completed = root / (operation + '-completed.json')
    if completed.exists():
        proof = json.loads(completed.read_bytes())
        if proof['result_id'] != current['id'] or proof['image'] != acceptance.state['worker_image_id']:
            raise ValueError('Completed operation identity differs')
        return {**proof, 'reused': True}
    result = retained_operation(acceptance, label, kind, operation, acquired)
    if result is None:
        result = shared.execute(acceptance, label, kind, operation, acquired=acquired)
    result.update(result_id=current['id'], image=acceptance.state['worker_image_id'])
    completed.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', choices=PACKAGES)
    parser.add_argument('operation', choices=['verify', 'recompute', 'render'])
    args = parser.parse_args()
    acceptance = Acceptance()
    try:
        print(json.dumps(execute(acceptance, args.package, args.operation), ensure_ascii=False))
    finally:
        acceptance.client.close()
