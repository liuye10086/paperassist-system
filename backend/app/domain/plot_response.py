"""Parse plot evidence after the gateway has durably recorded response usage."""
import json

from app.adapters.openai_plot import PROMPT_VERSION, validate_output
from app.core.exceptions import PlotError


class PlotVerificationError(PlotError):
    def __init__(self, differences, manifest, provenance):
        super().__init__('plot_result_mismatch', '云端计算结果、标签或图注与本地核对不一致，差异已保留，未发布图表。')
        self.differences, self.manifest, self.provenance = differences, manifest, provenance


def bounded_manifest(manifest):
    allowed = {'schema_version','figure_kind','language','correlation_method','mode','title','x_label','y_label','caption',
               'variables','statistics','plot_config','overall','groups','series','paired_summary','environment'}
    def bound(value, depth=0):
        if depth>6: return '[depth limit]'
        if isinstance(value,str): return value[:500]
        if isinstance(value,list): return [bound(item,depth+1) for item in value[:100]]
        if isinstance(value,dict): return {str(key)[:80]:bound(item,depth+1) for key,item in list(value.items())[:100]
            if key not in ('values','rows','research_summary','fliers')}
        return value if type(value) in (int,float,bool) or value is None else '[invalid type]'
    return {key:bound(value) for key,value in manifest.items() if key in allowed} if isinstance(manifest,dict) else {'invalid_type':type(manifest).__name__}


def parse_plot_response(data, container_id, expected=None):
    modern = isinstance(expected,dict) and expected.get('schema_version') in (2,3,4)
    png_name = 'figure.png' if modern else 'boxplot.png'
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
                if name in (png_name, 'result.json'):
                    if name in files and files[name] != file_id:
                        raise PlotError('plot_files_missing', '云端返回了相互冲突的文件引用。')
                    files[name] = file_id
    if set(files) != {png_name, 'result.json'}:
        raise PlotError('plot_files_missing', '云端未返回完整的图片和结果文件。')
    return {'files': files, 'provenance': {'response_id': data['id'], 'container_id': container_id,
        'model': data.get('model'), 'code': [call.get('code', '') for call in calls],
        'usage': data.get('usage'), 'prompt_version': ('openai_modeling_plot_v4' if expected.get('schema_version')==4 else 'openai_comparison_plot_v3' if expected.get('schema_version')==3 else 'openai_analysis_plot_v2') if modern else PROMPT_VERSION,
        'png_file_id': files[png_name], 'result_file_id': files['result.json']}}


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
    png_name = 'figure.png' if expected.get('schema_version') in (2,3,4) else 'boxplot.png'
    png = provider.download(files[png_name], container_id, 12 * 1024 * 1024, policy=policy)
    if not isinstance(png, bytes) or len(png) > 12 * 1024 * 1024:
        raise PlotError('plot_output_limit', '云端图片超过下载上限。')
    output = {'manifest': manifest, 'png': png, 'provenance':parsed['provenance']}
    if expected.get('schema_version') in (2,3,4):
        from app.adapters.openai_plot import plot_differences
        differences=plot_differences(manifest,expected,strict_manifest=expected.get('schema_version') in (3,4))
        if differences:
            raise PlotVerificationError(differences,bounded_manifest(manifest),parsed['provenance'])
    validate_output(output, expected)
    environment = manifest.get('environment')
    output['provenance'] = {**parsed['provenance'], 'environment': {
        key: value[:200] for key, value in environment.items()
        if key in ('python_version', 'matplotlib_version', 'font') and isinstance(value, str)
    } if isinstance(environment, dict) else {}}
    return output
