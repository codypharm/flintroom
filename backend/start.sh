#!/bin/sh
# The serving process, and only that. Migrations are NOT run here: with more
# than one replica this script starts N times per deploy, and N containers
# racing `alembic upgrade head` is a lock pile-up at best. Migrations belong
# to the deploy, not the container — railway.json's preDeployCommand runs
# them exactly once, before any new container serves (docs/deployment.md →
# "Migrations run before the new version serves").
set -eu

# The rate limiter keys on the socket peer, so uvicorn must rewrite it from
# the platform proxy's forwarded headers — and must trust only that proxy.
# `*` would let any direct caller mint identities (docs/deployment.md → "The
# proxy must rewrite the peer"). No default on purpose: a deployment that has
# not decided what to trust should fail loudly here, not quietly at attack.
: "${FORWARDED_ALLOW_IPS:?set FORWARDED_ALLOW_IPS to the platform proxy's address range - never *}"

exec uv run --no-sync python -m uvicorn app.main:create_app --factory \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --proxy-headers \
  --forwarded-allow-ips "${FORWARDED_ALLOW_IPS}"
