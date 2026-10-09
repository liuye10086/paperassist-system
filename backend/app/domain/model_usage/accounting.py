"""Integer-only effective budget and safe actual-cost projections."""


def tool_applicable(call):
    return 'code_interpreter' in call['policy_snapshot'].get('tools', [])


def reconciliation_status(call):
    if call['status'] == 'released':
        return 'not_applicable'
    token, tool = call.get('actual_token_micro_usd'), call.get('actual_tool_micro_usd')
    if token is not None and (not tool_applicable(call) or tool is not None):
        return 'reconciled'
    return 'partial' if token is not None or tool is not None else 'pending'


def public_reconciliation(call, reconciled_at=None):
    status = reconciliation_status(call)
    token, tool = call.get('actual_token_micro_usd'), call.get('actual_tool_micro_usd')
    if status in ('pending', 'not_applicable'):
        token = tool = reconciled_at = None
    return dict(status=status, token_micro_usd=token, tool_micro_usd=tool,
        tool_applicable=tool_applicable(call),
        actual_micro_usd=None if token is None and tool is None else (token or 0) + (tool or 0),
        reconciled_at=reconciled_at)


def accounting_projection(call, reservation):
    """Partial evidence never reduces the baseline reconstructed from original policy."""
    if call['status'] == 'released':
        return 0, 0
    state = reconciliation_status(call)
    if state == 'reconciled':
        return (call.get('actual_token_micro_usd') or 0) + (call.get('actual_tool_micro_usd') or 0), 0
    estimate = call['estimated_cost_micro_usd'] or 0
    original = reservation['reserved_micro_usd']
    tools = tool_applicable(call)
    tool_reserve = call['policy_snapshot'].get('tool_reserve_micro_usd', 0) if tools else 0
    baseline_remaining = max(original - estimate, 0, tool_reserve if call['usage_status'] == 'pending' and tools else 0)
    baseline = estimate + (baseline_remaining if call['usage_status'] == 'pending' else 0)
    if state == 'pending':
        return reservation['accounted_micro_usd'], baseline_remaining if reservation['status'] == 'held' else 0
    known = (call.get('actual_token_micro_usd') or 0) + (call.get('actual_tool_micro_usd') or 0)
    unknown_reserve = (original - tool_reserve if call.get('actual_token_micro_usd') is None else 0)
    unknown_reserve += tool_reserve if tools and call.get('actual_tool_micro_usd') is None else 0
    occupied = max(baseline, known + max(unknown_reserve, estimate))
    return estimate, occupied - estimate
