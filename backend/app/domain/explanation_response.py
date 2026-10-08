"""Parse a recorded Responses body without any provider or database operations."""
import json

from app.core.exceptions import PlotError
from app.domain.explanation_content import VERSION


def parse_explanation_response(data):
    if not isinstance(data, dict):
        raise PlotError('explanation_invalid_json', 'OpenAI 未返回有效的结构化解释，未保存内容。')
    if data.get('status') in ('queued', 'in_progress'):
        return None
    if data.get('status') != 'completed':
        raise PlotError('explanation_incomplete', 'OpenAI 解释未完成（失败、取消或输出额度不足），请检查后重试。')
    parts, size = [], 0
    try:
        for item in data.get('output', []):
            for part in item.get('content', []):
                if part.get('type') == 'refusal':
                    raise PlotError('explanation_refused', 'OpenAI 拒绝生成本次解释，未保存内容。请核查输入后重试。')
                if part.get('type') == 'output_text':
                    text = part['text']
                    size += len(text.encode('utf-8'))
                    if size > 96 * 1024:
                        raise PlotError('explanation_output_limit', 'OpenAI 返回的解释超过篇幅上限，未保存内容。')
                    parts.append(text)
        def reject_constant(value):
            raise ValueError('Nonfinite JSON is not supported.')
        draft = json.loads(''.join(parts), parse_constant=reject_constant)
        if not isinstance(draft, dict):
            raise ValueError('Explanation JSON must be an object.')
    except (KeyError, TypeError, AttributeError, ValueError, RecursionError):
        raise PlotError('explanation_invalid_json', 'OpenAI 未返回有效的结构化解释，未保存内容。') from None
    return {'draft': draft, 'provenance': {'response_id': data.get('id'), 'model': data.get('model'),
            'usage': data.get('usage'), 'prompt_version': VERSION}}
