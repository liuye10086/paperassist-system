"""Parse plot evidence after the gateway has durably recorded response usage."""
import json

from app.adapters.openai_plot import PROMPT_VERSION, validate_output
from app.core.exceptions import PlotError


def parse_plot_response(data, container_id):
    if not isinstance(data, dict):
        raise PlotError('plot_invalid_result', '云端绘图响应无效。')
    if data.get('status') in ('queued', 'in_progress'):
        return None
    if data.get('status') != 'completed':
        raise PlotError('openai_incomplete', '云端绘图未成功完成。')
    output = data.get('output')
    if not isinstance(output, list):
        raise PlotError('plot_no_execution', '云端未返回绘图执行记录。')
    calls = [item for item in output if isinstance(item, dict) and item.get('type') == 'code_interpreter_call']
    if not any(call.get('status') == 'completed' and call.get('container_id') == container_id for call in calls):
        raise PlotError('plot_no_execution', '云端未返回对应容器的完整执行记录。')
    files = {}
    for item in output:
        if not isinstance(item, dict) or item.get('type') != 'message':
            continue
        content = item.get('content', [])
        if not isinstance(content, list):
            raise PlotError('plot_invalid_result', '云端绘图消息结构无效。')
        for part in content:
            if not isinstance(part, dict):
                continue
            annotations = part.get('annotations', [])
            if not isinstance(annotations, list):
                raise PlotError('plot_invalid_result', '云端绘图文件引用结构无效。')
            for annotation in annotations:
                if (not isinstance(annotation, dict) or annotation.get('type') != 'container_file_citation'
                        or annotation.get('container_id') != container_id):
                    continue
                filename, file_id = annotation.get('filename'), annotation.get('file_id')
                if not isinstance(filename, str) or not isinstance(file_id, str):
                    continue
                name = filename.replace('\\', '/').rsplit('/', 1)[-1]
                if name in ('boxplot.png', 'result.json'):
                    if name in files and files[name] != file_id:
                        raise PlotError('plot_files_missing', '云端返回了相互冲突的文件引用。')
                    files[name] = file_id
    if set(files) != {'boxplot.png', 'result.json'}:
        raise PlotError('plot_files_missing', '云端未返回完整的图片和结果文件。')
    return {'files': files, 'provenance': {'response_id': data['id'], 'container_id': container_id,
        'model': data.get('model'), 'code': [call.get('code', '') for call in calls],
        'usage': data.get('usage'), 'prompt_version': PROMPT_VERSION,
        'png_file_id': files['boxplot.png'], 'result_file_id': files['result.json']}}


def download_plot(parsed, provider, policy, expected):
    container_id, files = parsed['provenance']['container_id'], parsed['files']
    manifest_bytes = provider.download(files['result.json'], container_id, 8 * 1024 * 1024, policy=policy)
    if not isinstance(manifest_bytes, bytes) or len(manifest_bytes) > 8 * 1024 * 1024:
        raise PlotError('plot_output_limit', '云端结果文件超过下载上限。')
    def reject_constant(value):
        raise ValueError('Nonfinite JSON number.')
    try:
        manifest = json.loads(manifest_bytes.decode('utf-8'), parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise PlotError('plot_invalid_result', '云端计算结果不是有效 JSON。') from None
    png = provider.download(files['boxplot.png'], container_id, 12 * 1024 * 1024, policy=policy)
    if not isinstance(png, bytes) or len(png) > 12 * 1024 * 1024:
        raise PlotError('plot_output_limit', '云端图片超过下载上限。')
    output = {'manifest': manifest, 'png': png}
    validate_output(output, expected)
    environment = manifest.get('environment')
    output['provenance'] = {**parsed['provenance'], 'environment': {
        key: value[:200] for key, value in environment.items()
        if key in ('python_version', 'matplotlib_version', 'font') and isinstance(value, str)
    } if isinstance(environment, dict) else {}}
    return output
