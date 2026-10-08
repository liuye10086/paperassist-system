FROM python:3.11.17-slim-bookworm@sha256:0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && pip check \
    && useradd --uid 10001 --create-home paperassist
COPY backend/app /app/app
COPY infra/worker/runtime_probe.py /app/runtime_probe.py
USER paperassist
CMD ["python", "-m", "app.workers", "worker"]
