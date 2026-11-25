ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG SOURCE_MANIFEST_SHA256
LABEL io.paperassist.source-manifest=${SOURCE_MANIFEST_SHA256}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/releaseapp
ENV PAPERASSIST_SKILLS_DIR=/releaseapp/SKILLS
WORKDIR /releaseapp
COPY backend/app ./app
COPY SKILLS ./SKILLS
COPY backend/alembic ./alembic
COPY backend/alembic.ini backend/requirements.txt ./
COPY frontend/dist ./static
COPY third_party ./third_party
COPY infra/api/release_web.py infra/api/release_entry.py ./
COPY source-manifest.json ./source-manifest.json
RUN python release_entry.py requirements
USER root
RUN install -d -o paperassist -g paperassist /run/paperassist-execution
# Docker copies this ownership and mode to a new release's staging volume.
RUN install -d -m 0700 -o paperassist -g paperassist /research-staging
USER paperassist
RUN python -m app.domain.runtime_skills
CMD ["python", "release_web.py"]
