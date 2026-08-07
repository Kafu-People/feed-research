/** IndexedDB-free minimal adapter (localStorage) for the feedback queue.
 *  Mobile supplies an expo-sqlite adapter for the SAME interface. */
import { isActed, type EventDraft, type Storage, type StoredEvent } from "@techtrend/core";

const KEY = "tt:events";

function read(): StoredEvent[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(window.localStorage.getItem(KEY) ?? "[]") as StoredEvent[];
  } catch {
    return [];
  }
}

function write(rows: StoredEvent[]): void {
  if (typeof window !== "undefined") window.localStorage.setItem(KEY, JSON.stringify(rows));
}

export const webStorage: Storage = {
  async enqueue(e: EventDraft) {
    const rows = read();
    rows.push({ ...e, id: `${Date.now()}-${Math.random().toString(36).slice(2)}` });
    write(rows);
  },
  async takePending(limit: number) {
    return read().slice(0, limit);
  },
  async clear(ids: string[]) {
    const drop = new Set(ids);
    write(read().filter((r) => !drop.has(r.id)));
  },
  async actedStoryIds() {
    return new Set(
      read().filter((r) => isActed(r.kind)).map((r) => r.storyId!).filter(Boolean),
    );
  },
};
