import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

ROOT=Path(__file__).resolve().parents[2]


class WebTests(unittest.TestCase):
    def test_static_navigation_and_api_404_keep_original_lifespan(self):
        events=[]
        async def api(scope,receive,send):
            if scope['type']=='lifespan':
                message=await receive(); events.append(message['type']); await send({'type':'lifespan.startup.complete'})
                message=await receive(); events.append(message['type']); await send({'type':'lifespan.shutdown.complete'}); return
            await JSONResponse({'detail':'original-api'},status_code=404)(scope,receive,send)
        config=types.ModuleType('app.workers.config'); config.load_secrets=lambda:None
        main=types.ModuleType('app.main'); main.app=api
        with patch.dict(sys.modules,{'app.workers.config':config,'app.main':main}),patch('starlette.staticfiles.StaticFiles'):
            spec=importlib.util.spec_from_file_location('release_web_test',ROOT/'infra/api/release_web.py')
            module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        from starlette.staticfiles import StaticFiles
        module.StaticFiles=StaticFiles
        with tempfile.TemporaryDirectory() as d:
            directory=Path(d); (directory/'index.html').write_text('frontend'); (directory/'real.js').write_text('asset')
            with TestClient(module.ReleaseWeb(api,directory)) as client:
                self.assertEqual(client.get('/').text,'frontend')
                self.assertEqual(client.get('/workspace',headers={'Accept':'text/html'}).text,'frontend')
                self.assertEqual(client.get('/api/missing',headers={'Accept':'text/html'}).json(),{'detail':'original-api'})
                self.assertEqual(client.get('/missing.js',headers={'Accept':'text/html'}).status_code,404)
                self.assertEqual(client.get('/real.js').text,'asset')
                self.assertEqual(client.post('/workspace').status_code,404)
            self.assertEqual(events,['lifespan.startup','lifespan.shutdown'])

if __name__=='__main__': unittest.main()
