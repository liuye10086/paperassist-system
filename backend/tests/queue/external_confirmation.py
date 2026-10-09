"""Explicit confirmation for synthetic queue inputs, never a real project."""


def confirm(client, url):
    response = client.get(url + '/disclosure')
    assert response.status_code == 200, response.text
    preview = response.json()
    return {'version': 1, 'confirmed': True, 'source_digest': preview['source_digest'],
            'labels': {item['key']: item['value'] for item in preview['labels']}}
