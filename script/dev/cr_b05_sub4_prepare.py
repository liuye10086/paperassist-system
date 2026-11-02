"""Prepare an empty fourth-batch schema; retain the accepted third batch."""
import json
import os
os.environ['PAPERASSIST_CR_B05_SUBPACKAGE'] = '4'
import cr_b05_runner as control
from cr_b05_prepare import prepare as prepare_batch


def prepare():
    return prepare_batch(control, 'client-requirements-b05-sub3', 'CR-B05 subpackage 3 only', '0065_microbiome_diversity')


if __name__ == '__main__':
    value = prepare()
    print(json.dumps({key: value[key] for key in ('schema', 'preparation_kind', 'status', 'migration_head')}))
