"""Bounded execution metadata from a provider response; never store its code or text."""


def response_tool_evidence(response, response_id):
    if not isinstance(response, dict) or response.get('id') != response_id:
        return None
    output = response.get('output')
    if not isinstance(output, list) or len(output) > 1000:
        return None
    ids = set()
    complete = response.get('status') == 'completed'
    for item in output:
        if not isinstance(item, dict):
            return None
        if item.get('type') != 'code_interpreter_call':
            if item.get('type') not in ('message', 'reasoning'):
                complete = False
            continue
        identity = item.get('id')
        if not isinstance(identity, str) or not 0 < len(identity) <= 256:
            complete = False
            continue
        if item.get('status') == 'completed':
            ids.add(identity)
        else:
            complete = False
    return dict(response_id=response_id, complete=complete, call_ids=sorted(ids))


def tool_count(call):
    if call['status'] in ('reserved', 'released') and not call.get('provider_response_id'):
        return 0, False
    evidence = (call.get('provider_state') or {}).get('tool_execution_evidence')
    if not isinstance(evidence, dict) or evidence.get('response_id') != call.get('provider_response_id'):
        return 0, True
    ids = evidence.get('call_ids')
    if not isinstance(ids, list) or len(ids) > 1000 or any(not isinstance(value, str) or not value or len(value)>256 for value in ids):
        return 0, True
    return len(set(ids)), evidence.get('complete') is not True


def merge_tool_evidence(previous, evidence):
    if evidence is None or previous.get('complete') is True:
        return previous
    if previous.get('response_id') == evidence['response_id']:
        ids = sorted(set(previous.get('call_ids', [])) | set(evidence['call_ids']))
        return {**evidence, 'call_ids': ids[:1000], 'complete': evidence['complete'] and len(ids) <= 1000}
    return evidence
