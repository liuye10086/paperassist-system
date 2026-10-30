FROM python:3.11.17-slim-bookworm@sha256:0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89 AS bio-runtime
COPY backend/requirements-bio.lock.txt /tmp/requirements-bio.lock.txt
RUN python -m venv /opt/paperassist-bio \
    && /opt/paperassist-bio/bin/pip install --require-hashes --only-binary=:all: --no-cache-dir -r /tmp/requirements-bio.lock.txt \
    && /opt/paperassist-bio/bin/pip check \
    && apt-get update && apt-get install -y --no-install-recommends fonts-wqy-zenhei=0.9.45-8 libgomp1=12.2.0-14+deb12u1 \
    && rm -rf /var/lib/apt/lists/*
COPY backend/app /app/app
COPY backend/tests/numeric /app/tests/numeric
COPY backend/requirements-bio.lock.txt /app/requirements-bio.lock.txt
RUN useradd --uid 10001 --create-home paperassist
ENV PYTHONPATH=/app OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMBA_NUM_THREADS=1 \
    NUMBA_THREADING_LAYER=omp NUMBA_CACHE_DIR=/tmp/paperassist-numba PYTHONDONTWRITEBYTECODE=1 \
    MPLBACKEND=Agg MPLCONFIGDIR=/tmp/matplotlib XDG_CACHE_HOME=/tmp/paperassist-cache HDF5_PLUGIN_PATH=/nonexistent
WORKDIR /app
USER paperassist

FROM python:3.11.17-slim-bookworm@sha256:0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --timeout 60 --no-cache-dir -r requirements.txt && pip check \
    && useradd --uid 10001 --create-home paperassist
COPY --from=bio-runtime /opt/paperassist-bio /opt/paperassist-bio
COPY --from=bio-runtime /usr/share/fonts/truetype/wqy /usr/share/fonts/truetype/wqy
COPY --from=bio-runtime /usr/share/doc/fonts-wqy-zenhei/copyright /usr/share/doc/fonts-wqy-zenhei/copyright
COPY --from=bio-runtime /usr/lib/x86_64-linux-gnu/libgomp.so.1.0.0 /usr/lib/x86_64-linux-gnu/libgomp.so.1.0.0
COPY --from=bio-runtime /usr/share/doc/gcc-12-base/copyright /usr/share/doc/libgomp1/copyright
RUN ln -s libgomp.so.1.0.0 /usr/lib/x86_64-linux-gnu/libgomp.so.1
COPY backend/requirements-bio.lock.txt /app/requirements-bio.lock.txt
COPY backend/app /app/app
COPY infra/worker/runtime_probe.py /app/runtime_probe.py
RUN python -c "from app.adapters.ocr_runtime import get_runtime; get_runtime()"
USER paperassist
CMD ["python", "-m", "app.workers", "worker"]
