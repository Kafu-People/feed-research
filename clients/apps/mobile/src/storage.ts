/**
 * The ONLY mobile-specific part of the feedback pipeline.
 *
 * Same `Storage` interface web implements over localStorage/IndexedDB. The
 * queue itself, `cleanNegatives`, and SHOWN_THRESHOLD are imported from
 * @techtrend/core -- never reimplemented. Two definitions of "shown" would mean
 * the personal layer learns from a blend of two different signals.
 */
import * as SQLite from "expo-sqlite";

import { isActed, type EventDraft, type Storage, type StoredEvent } from "@techtrend/core";

const db = SQLite.openDatabaseSync("techtrend.db");

db.execSync(`
  CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    story_id INTEGER,
    position INTEGER,
    reason TEXT,
    dwell_ms INTEGER
  );
`);

export const sqliteStorage: Storage = {
  async enqueue(e: EventDraft) {
    db.runSync(
      "INSERT INTO events (kind, story_id, position, reason, dwell_ms) VALUES (?, ?, ?, ?, ?)",
      e.kind, e.storyId ?? null, e.position ?? null, e.reason ?? null, e.dwellMs ?? null,
    );
  },

  async takePending(limit: number): Promise<StoredEvent[]> {
    const rows = db.getAllSync<{
      id: number; kind: string; story_id: number | null;
      position: number | null; reason: string | null; dwell_ms: number | null;
    }>("SELECT * FROM events ORDER BY id LIMIT ?", limit);
    return rows.map((r) => ({
      id: String(r.id),
      kind: r.kind as EventDraft["kind"],
      storyId: r.story_id,
      position: r.position,
      reason: r.reason,
      dwellMs: r.dwell_ms,
    }));
  },

  async clear(ids: string[]) {
    if (ids.length === 0) return;
    db.runSync(`DELETE FROM events WHERE id IN (${ids.map(() => "?").join(",")})`, ...ids);
  },

  async actedStoryIds() {
    const rows = db.getAllSync<{ kind: string; story_id: number | null }>(
      "SELECT kind, story_id FROM events WHERE story_id IS NOT NULL",
    );
    return new Set(
      rows.filter((r) => isActed(r.kind as EventDraft["kind"])).map((r) => r.story_id!),
    );
  },
};
