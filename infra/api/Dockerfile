ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG SOURCE_MANIFEST_SHA256
LABEL io.paperassist.source-manifest=${SOURCE_MANIFEST_SHA256}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/releaseapp
WORKDIR /releaseapp
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini backend/requirements.txt ./
COPY frontend/dist ./static
COPY infra/api/release_web.py infra/api/release_entry.py ./
COPY source-manifest.json ./source-manifest.json
RUN python release_entry.py requirements
USER paperassist
CMD ["python", "release_web.py"]
