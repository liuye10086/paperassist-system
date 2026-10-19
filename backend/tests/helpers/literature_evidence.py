"""Synthetic claim sources built through the ordinary isolated APIs."""
from tests.api.test_literature import project, create
from tests.helpers.literature import SyntheticNcbi


def seeded(client, kind='sci'):
    from app.domain.literature.execution import run_literature_task
    pid = project(client, kind)
    task = create(client, pid).json()
    assert run_literature_task(task['id'], task['revision'], client=SyntheticNcbi(2))['status'] == 'succeeded'
    references = client.get(f'/api/v1/projects/{pid}/literature/references').json()['items']
    reference = next(r for r in references if r['record']['abstract'])
    return pid, task['id'], reference
