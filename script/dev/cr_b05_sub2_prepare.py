"""Prepare this authorized subpackage using the accepted predecessor."""
import json
import os
os.environ['PAPERASSIST_CR_B05_SUBPACKAGE'] = '2'
import cr_b05_runner as control
from cr_b05_prepare import prepare as prepare_batch


def prepare():
    return prepare_batch(control, 'client-requirements-b05', 'CR-B05 subpackage 1 only', '0062_bio_tabular_assays')


if __name__ == '__main__':
    state = prepare()
    print(json.dumps({key: state[key] for key in ('schema', 'preparation_kind', 'status', 'migration_head')}))
