"""HTTP routes for boxplot; business operations live in domain."""
from urllib.parse import quote
import json

from fastapi import APIRouter, Response

from app.api.dependencies import Store, Settings
from app.domain import boxplot as operations
from app.domain.boxplot import PlotRequest
from app.adapters.excel import fail
from app.domain.boxplot import result_source, RENDERER, STATISTICS_ENGINE

router = APIRouter(prefix='/api/v1/projects/{project_id}/files/{file_id}/analysis-runs/{run_id}', tags=['箱线图'])


@router.get('/boxplot')
def get_boxplot(project_id: str, file_id: str, run_id: str, store: Store):
    return operations.get_boxplot(project_id, file_id, run_id, store)

@router.get('/boxplot/image')
def image(project_id: str, file_id: str, run_id: str, store: Store, download: bool = False):
    result = result_source(store, project_id, file_id, run_id)
    state = store.figure_state(result, RENDERER, STATISTICS_ENGINE)
    figure = state['figure']
    if figure is None:
        fail('figure_not_found', '此结果尚未生成箱线图。', 404)
    content = store.figure_png(figure)
    return Response(content, media_type='image/png', headers={
        'Content-Disposition': f'{"attachment" if download else "inline"}; filename="boxplot-{figure["id"]}.png"',
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


@router.get('/figures/{figure_id}/download')
def download_saved_figure(project_id: str, file_id: str, run_id: str, figure_id: str, store: Store):
    result = result_source(store, project_id, file_id, run_id)
    with store.connection() as db:
        row = db.execute('SELECT figure_json FROM figures WHERE id=%s AND analysis_run_id=%s',
                         (figure_id, run_id)).fetchone()
    if row is None:
        fail('figure_not_found', '此统计结果中没有该图表。', 404)
    figure = json.loads(row['figure_json'])
    if (figure['id'] != figure_id or figure['analysis_run_id'] != run_id or figure['file_id'] != file_id
            or figure['source_sha256'] != result['source_sha256']):
        fail('source_conflict', '图表与统计结果的来源不一致。', 409)
    return Response(store.figure_png(figure), media_type='image/png', headers={
        'Content-Disposition': "attachment; filename*=UTF-8''" + quote(f'boxplot-{figure_id}.png', safe=''),
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


@router.post('/boxplot')
def generate(project_id: str, file_id: str, run_id: str, request: PlotRequest, store: Store, settings: Settings, response: Response):
    result, response.status_code = operations.generate(project_id, file_id, run_id, request, store, settings)
    return result
