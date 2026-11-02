"""Prepare this authorized subpackage using the accepted predecessor."""
import json
import os
os.environ['PAPERASSIST_CR_B05_SUBPACKAGE'] = '3'
import cr_b05_runner as control
from cr_b05_prepare import prepare as prepare_batch


def prepare():
    return prepare_batch(control, 'client-requirements-b05-sub2', 'CR-B05 subpackage 2 only', '0063_qpcr_statistics_bridge')


if __name__ == '__main__':
    state = prepare()
    print(json.dumps({key: state[key] for key in ('schema', 'preparation_kind', 'status', 'migration_head')}))
