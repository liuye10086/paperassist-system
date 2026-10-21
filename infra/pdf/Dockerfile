FROM python:3.11.17-slim-bookworm@sha256:0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LANG=C.UTF-8 HOME=/tmp SAL_USE_VCLPLUGIN=svp
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer=4:7.4.7-1+deb12u14 python3-uno=4:7.4.7-1+deb12u14 fontconfig \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10002 --create-home renderer \
    && mkdir -p /usr/local/share/fonts/paperassist
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-math=4:7.4.7-1+deb12u14 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY infra/pdf/renderer.py /app/renderer.py
COPY infra/pdf/update_fields.py /app/update_fields.py
COPY backend/app/adapters/pdf_renderer_lock.json /app/renderer-lock.json
USER renderer
CMD ["python", "/app/renderer.py"]
