#!/usr/bin/env bash
#
# Bring TechTrend up on the Windows/WSL host.
#
# This exists because WSL1 has no systemd: PID 1 is `init`, so the units in
# backend/deploy/systemd cannot run here and nothing restarts the processes
# after a reboot. The failure is silent -- Postgres, Redis, MinIO and the
# worker simply are not there, the hourly sweep never fires, and the Slack
# channel goes quiet exactly the way it does when a host dies.
#
# Idempotent by design: every step checks before acting, so this is safe to
# run at boot, by hand, or on a timer as a watchdog. It will not start a
# second worker.
#
# Install as a Windows scheduled task (see ops/wsl-start.md), or run:
#     wsl -d Ubuntu-24.04 -e bash -lc /path/to/ops/wsl-start.sh

set -uo pipefail

# The scheduled task runs this as root (`wsl -u root`): without systemd nothing
# recreates /var/run/postgresql after a reboot, and pg_ctlcluster fails with
# "No such file or directory" unless it exists. Long-running processes still
# drop to the normal user so file ownership does not change.
APP_USER=administrator
AS_APP=()
if [[ $(id -u) -eq 0 ]]; then
  install -d -o postgres -g postgres -m 2775 /var/run/postgresql
  AS_APP=(runuser -u "$APP_USER" --)
fi

REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
ENVF=$REPO/backend/.env
PGPORT_TT=5433
INGEST_LOG=/var/log/techtrend-ingest.log
DELIVER_LOG=/var/log/techtrend-deliver.log
# TWO workers, split by stage, because the queue has no aging.
#
# `claim` is ORDER BY priority, run_after LIMIT :batch -- so while four or more
# priority-100 jobs are pending, a priority-200 job is NEVER claimed. Reports,
# summaries, digests and briefs are all PRIORITY_BACKFILL=200, and a cold start
# across 101 feeds keeps ingestion saturated for hours. The single all-stage
# worker this host first ran went eight hours without once running the hourly
# report: not lag, starvation.
#
# The VPS got away with one worker because a steady state leaves gaps in the
# queue. A rebuilt host does not. Splitting by stage is exactly the
# "operational convenience" docs/development/15-deployment.md describes, and
# here it is what makes delivery happen at all.
#
# These lists must stay DISJOINT. Two workers sharing `collect` would double
# the crawl against every publisher, and per-host politeness is an invariant
# on this project, not a tuning knob.
STAGES_INGEST=collect,read,group,judge,match
STAGES_DELIVER=notify,summarize,hourly,digest,brief,discuss,maintenance

log() { printf '[%s] %s\n' "$(date -Is)" "$*"; }

# --- postgres ---------------------------------------------------------------
# Cluster 16/main, on 5433 rather than 5432 -- that is where the Ubuntu package
# put it, and backend/.env points at it.
if pg_isready -h localhost -p "$PGPORT_TT" -q 2>/dev/null; then
  log "postgres already up"
else
  pg_ctlcluster 16 main start 2>/dev/null && log "postgres started" || log "postgres FAILED to start"
fi

# --- redis ------------------------------------------------------------------
if redis-cli ping >/dev/null 2>&1; then
  log "redis already up"
else
  "${AS_APP[@]}" redis-server --daemonize yes && log "redis started" || log "redis FAILED to start"
fi

# --- minio ------------------------------------------------------------------
# Credentials come from .env rather than being repeated here, so the object
# store and the app cannot drift apart. Loopback only: this port was public on
# the old host and that is how a stray MinIO console becomes someone's SSH key.
if curl -sf --max-time 3 http://127.0.0.1:9000/minio/health/live >/dev/null 2>&1; then
  log "minio already up"
elif ! command -v minio >/dev/null; then
  log "minio NOT INSTALLED -- the read stage cannot store article bodies"
else
  MINIO_ROOT_USER=$(sed -n 's/^TT_S3_ACCESS_KEY=//p' "$ENVF")
  MINIO_ROOT_PASSWORD=$(sed -n 's/^TT_S3_SECRET_KEY=//p' "$ENVF")
  if [[ -z ${MINIO_ROOT_USER:-} || -z ${MINIO_ROOT_PASSWORD:-} ]]; then
    log "minio NOT STARTED -- TT_S3_ACCESS_KEY/TT_S3_SECRET_KEY missing from .env"
  else
    export MINIO_ROOT_USER MINIO_ROOT_PASSWORD
    mkdir -p /var/lib/minio/data
    # Stays root: /var/lib/minio/data has always been root-owned.
    setsid nohup minio server /var/lib/minio/data \
      --address 127.0.0.1:9000 --console-address 127.0.0.1:9001 \
      >/var/log/minio.log 2>&1 </dev/null &
    log "minio starting"
  fi
fi

# --- wait for the database --------------------------------------------------
# The worker crashes out of bootstrap() against a database that is not yet
# accepting connections, and at boot that race is the normal case, not the
# rare one.
for _ in $(seq 1 60); do
  pg_isready -h localhost -p "$PGPORT_TT" -q 2>/dev/null && break
  sleep 1
done
pg_isready -h localhost -p "$PGPORT_TT" -q 2>/dev/null \
  || { log "postgres never came up -- not starting the worker"; exit 1; }

# --- workers ----------------------------------------------------------------
# One of each, never two. The lease makes a duplicate safe for correctness,
# but an extra ingest worker doubles publisher load.
start_worker() {
  local name=$1 stages=$2 conc=$3 logf=$4
  if pgrep -f "techtrend worker --stage $stages" >/dev/null; then
    log "$name worker already running"
    return
  fi
  cd "$REPO/backend" || return 1
  setsid nohup "${AS_APP[@]}" .venv/bin/techtrend worker --stage "$stages" --concurrency "$conc"     >>"$logf" 2>&1 </dev/null &
  sleep 5
  if pgrep -f "techtrend worker --stage $stages" >/dev/null; then
    log "$name worker started"
  else
    log "$name worker DIED immediately -- see $logf"
    tail -5 "$logf"
  fi
}

start_worker ingest  "$STAGES_INGEST"  4 "$INGEST_LOG"
start_worker deliver "$STAGES_DELIVER" 2 "$DELIVER_LOG"

log "done"
