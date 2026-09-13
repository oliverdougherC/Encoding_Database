# syntax=docker/dockerfile:1
# Use the same checksum-pinned, multi-architecture media runtime as the server.
# Acquisition needs full ffprobe/decode validation, not the client GUI/build stack.
FROM linuxserver/ffmpeg:7.1.1@sha256:aea59a11c54291ac456bb2d67000445e5a8994f70bc3d96cdc29f022fbbf89fb
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       python3 python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/suite-venv
COPY scripts/requirements-suite-preparation.txt /opt/requirements.txt
RUN /opt/suite-venv/bin/pip install --no-cache-dir --disable-pip-version-check -r /opt/requirements.txt \
    && /opt/suite-venv/bin/pip check \
    && ffmpeg -version && ffprobe -version
WORKDIR /opt/encodingdb
COPY client/__init__.py client/config.py client/suite.py ./client/
COPY scripts/materialize_final_suite.py ./scripts/
ENV PYTHONDONTWRITEBYTECODE=1 HOME=/tmp
ENTRYPOINT ["/opt/suite-venv/bin/python", "/opt/encodingdb/scripts/materialize_final_suite.py"]
