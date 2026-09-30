#!/usr/bin/env bash
#
# Weekly backup, in two tiers, because one tier cannot do both jobs.
#
# TIER 1 -- the full dump, on disk, rotated.
#   This is the disaster-recovery artifact: every row, restorable with
#   pg_restore. It is 131 MB compressed and GROWS, which is exactly why it
#   does not go in git. GitHub rejects any file over 100 MB outright, and a
#   131 MB file committed weekly would add ~6.8 GB of history a year that
#   cannot be reclaimed without rewriting history.
#
# TIER 2 -- the curated state, in git, as readable SQL.
#   Topics, their terms, brief topics, feed endpoints, publisher blocks,
#   ranking weights. A few hundred KB that barely grows, because it is
#   configuration rather than accumulated content. This is the tier worth
#   versioning: `git log -p ops/backup/topics.sql` shows how the topic set
#   changed over months, which the binary dump can never show.
#
# What tier 2 deliberately leaves out:
#   articles, stories  -- 301 MB of bodies and pgvector embeddings. The bulk.
#   jobs               -- the work queue. Ephemeral by design.
#   matches            -- derived from stories and topics; unbounded growth.
#   events, seen       -- telemetry and dedup state.
#   users              -- holds email and password_hash. A hash committed to
#                         git is permanent even in a private repo, and this
#                         table is one row that `make seed` can recreate.
#   All of these ARE in the tier-1 dump. Nothing is unprotected; the split is
#   about which artifact each belongs in.

set -euo pipefail

REPO=/opt/TechTrend
CONTAINER=techtrend-db-1
DB=techtrend
ARCHIVE=${TT_BACKUP_DIR:-$HOME/.local/state/techtrend/backups}
KEEP=${TT_BACKUP_KEEP:-8}
BRANCH=db-backups
# Its own clone, NOT the live checkout. This runs unattended at 04:00 and the
# working tree at /opt/TechTrend may have uncommitted work in it -- two Claude
# sessions have edited this repo concurrently before. A backup job must never
# be the reason someone's in-progress edit was stashed or rebased.
WORK=${TT_BACKUP_WORK:-$HOME/.local/state/techtrend/backup-repo}

# Bounded tables only: each of these is configuration a human curated, and
# none grows with traffic. Adding an unbounded table here would slowly
# recreate the size problem this split exists to avoid.
TABLES=(
  alembic_version
  topics
  topic_terms
  brief_topics
  endpoints
  sites
  weights
  subscriptions
  suggestions
)

log() { printf '%s  %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { log "FAILED: $*" >&2; exit 1; }

stamp=$(date -u +%Y-%m-%d)
mkdir -p "$ARCHIVE"

docker exec "$CONTAINER" pg_isready -U postgres -q || die "Postgres is not accepting connections"

# ---------------------------------------------------------------- tier 1
dump=$ARCHIVE/techtrend-$stamp.dump
log "full dump -> $dump"
docker exec "$CONTAINER" pg_dump -U postgres -d "$DB" -Fc -Z9 > "$dump.partial" \
  || die "pg_dump failed"
# Rename only after pg_dump exits 0, so a truncated file from a crash or a
# full disk can never be mistaken for a good backup by the rotation below.
mv "$dump.partial" "$dump"

# A backup nobody reads is a guess. pg_restore --list parses the archive's
# table of contents, so a corrupt or truncated dump fails HERE, this week,
# rather than during the restore that someone attempts under pressure.
entries=$(docker exec -i "$CONTAINER" pg_restore --list < "$dump" | grep -c '^[0-9]' || true)
[ "${entries:-0}" -gt 0 ] || die "dump is unreadable: pg_restore --list found no entries"
log "verified: $entries archive entries, $(du -h "$dump" | cut -f1)"

# Rotate AFTER the new dump is verified, never before: pruning first would, on
# a week when pg_dump fails, leave fewer backups than it started with.
surplus=$(ls -1t "$ARCHIVE"/techtrend-*.dump 2>/dev/null | tail -n +$((KEEP + 1)) || true)
if [ -n "$surplus" ]; then
  log "rotating out $(echo "$surplus" | wc -l) dump(s) beyond the $KEEP most recent"
  echo "$surplus" | xargs -r rm -f
fi

# ---------------------------------------------------------------- tier 2
if [ ! -d "$WORK/.git" ]; then
  log "first run: cloning into $WORK"
  origin=$(git -C "$REPO" remote get-url origin)
  git clone --quiet "$origin" "$WORK" || die "clone failed"
fi

git -C "$WORK" fetch --quiet origin || die "fetch failed"
if git -C "$WORK" rev-parse --verify --quiet "origin/$BRANCH" >/dev/null; then
  git -C "$WORK" checkout --quiet -B "$BRANCH" "origin/$BRANCH"
else
  # An ORPHAN branch, with no shared history with master. The backup commits
  # are machine output on a weekly cadence; interleaving them into master
  # would bury real commits and guarantee conflicts with whoever is working.
  log "creating orphan branch $BRANCH"
  git -C "$WORK" checkout --quiet --orphan "$BRANCH"
  git -C "$WORK" rm -rq --cached . 2>/dev/null || true
fi

out=$WORK/ops/backup
rm -rf "$out"
mkdir -p "$out"

docker exec "$CONTAINER" pg_dump -U postgres -d "$DB" --schema-only --no-owner --no-privileges \
  > "$out/schema.sql" || die "schema dump failed"

for t in "${TABLES[@]}"; do
  # --column-inserts, not COPY: an INSERT naming its columns still restores
  # after a migration adds one, and it diffs a line at a time so `git log -p`
  # reads as "this topic's prompt changed", not "this blob changed".
  docker exec "$CONTAINER" pg_dump -U postgres -d "$DB" \
    --data-only --column-inserts --no-owner --table="public.$t" \
    > "$out/$t.sql" || die "dump of $t failed"
done

cat > "$out/README.md" <<EOF
# Database backup -- curated state

Written by \`ops/backup-db.sh\` on the weekly timer. **Machine output. Do not
hand-edit:** the next run deletes this directory and rewrites it.

Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)
Source:    $DB on $(hostname)
Full dump: $ARCHIVE/techtrend-$stamp.dump ($(du -h "$dump" | cut -f1), NOT in git)

## What is here

\`schema.sql\` plus one file per curated table, as column-named INSERTs.
These are the rows a human chose: topics and their prompts, feed endpoints,
blocked publishers, ranking weights.

Article bodies, embeddings, the job queue, matches and the users table are
**not** here -- they are in the full dump on disk. See the header of
\`ops/backup-db.sh\` for why each was left out.

## Restore

Curated state only, into a database that already has the schema:

    for f in ops/backup/{topics,topic_terms,brief_topics,endpoints,sites,weights,subscriptions,suggestions}.sql; do
      docker exec -i techtrend-db-1 psql -U postgres -d techtrend < "\$f"
    done

Everything, from the full dump:

    docker exec -i techtrend-db-1 pg_restore -U postgres -d techtrend \\
      --clean --if-exists --no-owner < techtrend-$stamp.dump

The full dumps are kept for $KEEP weeks and then rotated out.
EOF

git -C "$WORK" add --all ops/backup
if git -C "$WORK" diff --cached --quiet; then
  log "curated state unchanged since last week; nothing to commit"
else
  git -C "$WORK" -c user.name="TechTrend backup" -c user.email="devdelcimario@gmail.com" \
    commit --quiet -m "backup: curated database state $stamp" \
    -m "Schema and the curated tables as of $stamp. Full dump ($(du -h "$dump" | cut -f1)) is on disk at $ARCHIVE, not here -- see ops/backup/README.md." \
    || die "commit failed"
  if [ -n "${TT_BACKUP_NO_PUSH:-}" ]; then
    log "TT_BACKUP_NO_PUSH set: committed $(git -C "$WORK" rev-parse --short HEAD) locally, not pushed"
  else
    git -C "$WORK" push --quiet origin "$BRANCH" || die "push to origin/$BRANCH failed"
    log "pushed $(git -C "$WORK" rev-parse --short HEAD) to origin/$BRANCH"
  fi
fi

log "done"
