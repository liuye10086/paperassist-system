"""Same-origin static frontend around the existing application and lifespan."""
from pathlib import Path

from app.workers.config import load_secrets
load_secrets()
from app.main import app as api
from starlette.staticfiles import StaticFiles
from starlette.responses import FileResponse


class ReleaseWeb:
    def __init__(self, application, directory):
        self.api = application
        self.directory = Path(directory)
        self.static = StaticFiles(directory=directory)

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        if scope['type'] != 'http' or path == '/api' or path.startswith('/api/'):
            return await self.api(scope, receive, send)
        if scope.get('method') not in ('GET', 'HEAD'):
            return await self.api(scope, receive, send)
        target = (self.directory / path.lstrip('/')).resolve()
        if self.directory.resolve() in target.parents and target.is_file():
            return await self.static(scope, receive, send)
        # Only browser navigation gets the SPA; unknown assets retain a 404.
        headers = dict(scope.get('headers', []))
        if path == '/' or (b'text/html' in headers.get(b'accept', b'') and not Path(path).suffix):
            return await FileResponse(self.directory / 'index.html', headers={'Cache-Control':'no-store'})(scope, receive, send)
        return await self.api(scope, receive, send)


app = ReleaseWeb(api, '/releaseapp/static')

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8443, proxy_headers=False,
                ssl_keyfile='/run/tls/server-key.pem', ssl_certfile='/run/tls/server.pem')
