# The one container this product deploys. Host-agnostic by intent: Railway
# today, and anything that runs Docker tomorrow — the platform-specific surface
# is railway.json and the dashboard's env vars, never this file.
#
# uv is pinned to the version developers run, for the same reason ty is pinned:
# an unpinned toolchain makes "the build passed" a statement about the day.
FROM ghcr.io/astral-sh/uv:0.12.3-python3.12-trixie-slim

# LibreOffice converts PPTX to PDF in the extraction sweep, and it is the only
# system package this backend needs (docs/deployment.md → "LibreOffice is in
# the image, or PPTX quietly stops working"). PyAV ships its own ffmpeg and
# libopus in the wheel, deliberately, so audio encoding needs nothing here.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies before source, so editing app code does not reinstall the world.
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY scripts ./scripts
COPY start.sh ./
RUN uv sync --frozen --no-dev

# Unprivileged, because this process handles other people's unannounced
# financials. LibreOffice wants a writable HOME for its profile; TMPDIR stays
# the container's own disk, which is what the deployment doc requires of it.
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser
ENV HOME=/home/appuser

# One asyncio worker per container; scale is replicas, not workers. That is
# the shape the write path was built for — per-user locking, nothing global —
# and it keeps each container's sweep loop, memory, and failure domain small.
CMD ["./start.sh"]
