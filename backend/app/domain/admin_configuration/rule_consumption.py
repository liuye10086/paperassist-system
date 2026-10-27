"""Finite installed rules; existing objects never fall back to the current pointer."""
from .bindings import resolve, bind, projection
from .contracts import Journals, Schools, Review


def rules(version, domain):
    if domain == 'review':
        from app.domain.review_rounds.planning import installed_rules
        value = version['bundle'][domain] if version else installed_rules()
        return Review.model_validate(value).model_dump(mode='json')
    model = {'journals': Journals, 'schools': Schools}[domain]
    return model.model_validate(version['bundle'][domain] if version else {}).model_dump(mode='json')


def task_version(db, task):
    return resolve(db, kind='task', object_id=task['id'])


def round_version(db, identity):
    return resolve(db, kind='review_round', object_id=identity)


def inherit_task(db, task, *, parent_task=None, round_id=None, confirmation_id=None):
    if parent_task is not None:
        version = resolve(db, kind='task', object_id=parent_task)
    elif round_id is not None:
        version = round_version(db, round_id)
    else:
        version = resolve(db, kind='school_confirmation', object_id=confirmation_id)
    return bind(db, kind='task', object_id=task['id'], version=version)


def document_defaults(db, round_id):
    policy = rules(round_version(db, round_id), 'review')
    return dict(language=policy['default_language'], document_version=policy['document_version'])


def check_format(db, task_id, *args, **kwargs):
    # The only installed implementation is selected explicitly; no arbitrary plugins.
    policy = rules(resolve(db, kind='task', object_id=task_id), 'journals')
    if policy['format_version'] != 'journal-format-v1':
        raise ValueError('Unsupported installed format rules')
    from app.domain.journals.format_rules import check_format as installed
    return installed(*args, **kwargs)
