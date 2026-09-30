# Backups

Postgres is backed up **every Sunday at 04:00 America/Sao_Paulo** by a systemd
user timer. The database is the only thing on this box that cannot be rebuilt
from the repo: article bodies that the RSS feeds no longer list, and topic
prompts that took real iteration to write.

## Two tiers, and why

One artifact cannot do both jobs, so there are two.

| | Tier 1 — full dump | Tier 2 — curated state |
| --- | --- | --- |
| What | every row, `pg_dump -Fc` | schema + the tables a human curated |
| Size | ~131 MB, grows with traffic | ~244 KB, barely grows |
| Where | `~/.local/state/techtrend/backups/` | git, branch `db-backups` |
| Kept | 8 weeks, then rotated | forever, in history |
| Restores | everything | topics, feeds, weights |

**The full dump cannot go in git.** GitHub rejects any file over 100 MB, and
this one is 131 MB today. Even under the limit, committing it weekly would add
roughly 6.8 GB of history a year, and git history cannot be reclaimed without
rewriting it for everyone.

**The curated tier is the one worth versioning.** `git log -p ops/backup/topics.sql`
shows how the topic set and its prompts changed over months. The binary dump
can never show that, however many copies you keep.

Tier 2 holds `alembic_version`, `topics`, `topic_terms`, `brief_topics`,
`endpoints`, `sites`, `weights`, `subscriptions`, `suggestions` — each bounded,
because it is configuration rather than accumulated content.

It deliberately leaves out `articles` and `stories` (301 MB of bodies and
pgvector embeddings), `jobs` (ephemeral queue), `matches` (derived, unbounded),
`events` and `seen` (telemetry, dedup), and `users` — that one holds an email
and a `password_hash`, and a hash committed to git is permanent even in a
private repo. **All of these are in the tier-1 dump.** Nothing is unprotected;
the split decides which artifact each belongs in.

## Running it by hand

    make backup          # both tiers, pushes to origin/db-backups
    make backup-dry      # both tiers, commits locally, does not push

## Restoring

Curated state, into a database that already has the schema:

    git fetch origin db-backups
    git checkout origin/db-backups -- ops/backup
    for f in ops/backup/{topics,topic_terms,brief_topics,endpoints,sites,weights,subscriptions,suggestions}.sql; do
      docker exec -i techtrend-db-1 psql -U postgres -d techtrend < "$f"
    done

Everything, from a full dump:

    ls ~/.local/state/techtrend/backups/
    docker exec -i techtrend-db-1 pg_restore -U postgres -d techtrend \
      --clean --if-exists --no-owner < ~/.local/state/techtrend/backups/techtrend-YYYY-MM-DD.dump

## Checking it ran

    systemctl --user list-timers techtrend-backup.timer
    journalctl --user -u techtrend-backup -n 40

The timer sets `Persistent=true`, so a week missed to a reboot runs on the next
boot instead of vanishing. `loginctl enable-linger` is already set for the
service account, which is what lets a *user* timer fire with nobody logged in —
without it the backup would silently never run.

## What the script verifies

`ops/backup-db.sh` writes to `*.partial` and renames only after `pg_dump`
exits 0, so a dump truncated by a crash or a full disk can never be mistaken
for a good one. It then runs `pg_restore --list` over the result and fails if
the archive has no readable entries — a corrupt dump fails *that week*, not
during a restore attempted under pressure. Rotation runs only after the new
dump is verified, so a failed week never leaves you with fewer backups than
you started with.

It also works in **its own clone**, at `~/.local/state/techtrend/backup-repo`,
never the live checkout at `/opt/TechTrend`. An unattended 04:00 job must
never be the reason someone's uncommitted work got stashed or rebased.

`db-backups` is an **orphan** branch, sharing no history with `master`, and CI
skips it. Machine commits on a weekly cadence do not belong interleaved with
code review.
