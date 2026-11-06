# Extend an existing application Worker; do not replace retained images.
ARG WORKER_IMAGE=paperassist-client-b06-w1-worker:local
FROM ${WORKER_IMAGE} AS r-environment
USER root
COPY infra/single-cell-r/environment.yml /tmp/single-cell-r-environment.yml
RUN python -c "import urllib.request,tarfile,io; data=urllib.request.urlopen('https://micro.mamba.pm/api/micromamba/linux-64/2.9.0',timeout=120).read(); archive=tarfile.open(fileobj=io.BytesIO(data),mode='r:bz2'); open('/usr/local/bin/micromamba','wb').write(archive.extractfile('bin/micromamba').read())" \
    && chmod 755 /usr/local/bin/micromamba
RUN MAMBA_ROOT_PREFIX=/tmp/paperassist-mamba micromamba create --yes --strict-channel-priority \
      --prefix /opt/paperassist-single-cell-r --file /tmp/single-cell-r-environment.yml \
    && micromamba list --prefix /opt/paperassist-single-cell-r --explicit > /opt/paperassist-single-cell-r/explicit-spec.txt \
    && MAMBA_ROOT_PREFIX=/tmp/paperassist-mamba micromamba clean --all --yes
FROM r-environment
COPY infra/single-cell-r/compatibility.txt /tmp/single-cell-r-compatibility.txt
RUN MAMBA_ROOT_PREFIX=/tmp/paperassist-mamba micromamba install --yes --strict-channel-priority \
      --prefix /opt/paperassist-single-cell-r -c conda-forge -c bioconda \
      --file /tmp/single-cell-r-compatibility.txt \
    && micromamba list --prefix /opt/paperassist-single-cell-r --explicit > /opt/paperassist-single-cell-r/explicit-spec.txt \
    && MAMBA_ROOT_PREFIX=/tmp/paperassist-mamba micromamba clean --all --yes
RUN /opt/paperassist-single-cell-r/bin/Rscript --vanilla -e 'stopifnot(as.character(packageVersion("scDblFinder"))=="1.20.2",as.character(packageVersion("decontX"))=="1.4.0",as.character(packageVersion("harmony"))=="1.2.3"); library(scDblFinder); library(decontX); library(harmony); sessionInfo()'
RUN R_HOME=/opt/paperassist-single-cell-r/lib/R RPY2_CFFI_MODE=ABI \
      /opt/paperassist-bio/bin/pip install --no-cache-dir rpy2==3.5.17 \
    && /opt/paperassist-bio/bin/pip check
USER paperassist
