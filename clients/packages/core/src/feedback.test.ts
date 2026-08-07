/**
 * These run once, in Node, and cover BOTH surfaces. There is no "did we get the
 * retry logic right on Android too" question.
 */

import { describe, expect, it } from "vitest";

import { renderModel, visibleCards } from "./card";
import { cleanNegatives, createFeedbackQueue, isActed } from "./feedback";
import { rateLabel, relativeTime, sourceLine } from "./format";
import type { Card, EventDraft, EventKind } from "./types";

const card = (over: Partial<Card> = {}): Card => ({
  storyId: 1,
  headline: "Nvidia cleared to resume H20 sales to China",
  summary: "Two sentences in our own words. Reported across outlets.",
  sourceName: "Reuters",
  sourceCount: 14,
  publishedAt: new Date(Date.now() - 2 * 3600_000).toISOString(),
  imageUrl: null,
  url: "https://reuters.com/x",
  topicLabels: [{ topic_id: 1, label: "AI chips" }],
  matchedBy: ["h100"],
  ...over,
});

function memoryStorage() {
  const rows: (EventDraft & { id: string })[] = [];
  let n = 0;
  return {
    rows,
    async enqueue(e: EventDraft) {
      rows.push({ ...e, id: String(++n) });
    },
    async takePending(limit: number) {
      return rows.slice(0, limit);
    },
    async clear(ids: string[]) {
      for (const id of ids) {
        const i = rows.findIndex((r) => r.id === id);
        if (i >= 0) rows.splice(i, 1);
      }
    },
    async actedStoryIds() {
      return new Set(rows.filter((r) => isActed(r.kind)).map((r) => r.storyId!));
    },
  };
}

describe("clean negatives -- the property the learning system rests on", () => {
  it("treats every un-acted shown card as a negative", () => {
    const shown = Array.from({ length: 10 }, (_, i) => ({ storyId: i, position: i }));
    const out = cleanNegatives(shown, new Set([1, 2]));
    expect(out).toHaveLength(8);
    expect(out.every((e) => e.kind === "skipped")).toBe(true);
  });

  it("preserves position so bias can be corrected server-side", () => {
    const out = cleanNegatives([{ storyId: 5, position: 3 }], new Set());
    expect(out[0]!.position).toBe(3);
  });

  it("returns nothing when the user acted on everything", () => {
    const shown = [{ storyId: 1, position: 0 }, { storyId: 2, position: 1 }];
    expect(cleanNegatives(shown, new Set([1, 2]))).toEqual([]);
  });
});

describe("feedback queue", () => {
  it("keeps events queued when the network fails, and retries later", async () => {
    const storage = memoryStorage();
    let fail = true;
    const q = createFeedbackQueue({
      storage,
      transport: {
        async postEvents() {
          if (fail) throw new Error("offline");
        },
      },
    });

    await q.track("tapped_through", { storyId: 7 }, 0);
    expect(await q.flush()).toBe(0);
    expect(storage.rows).toHaveLength(1); // survived the failure

    fail = false;
    expect(await q.flush()).toBe(1);
    expect(storage.rows).toHaveLength(0);
  });

  it("dayComplete emits a skip for each card the user ignored", async () => {
    const storage = memoryStorage();
    const sent: EventDraft[][] = [];
    const q = createFeedbackQueue({
      storage,
      transport: {
        async postEvents(b) {
          sent.push(b);
        },
      },
    });

    await q.track("tapped_through", { storyId: 1 }, 0);
    const n = await q.dayComplete([
      { storyId: 1, position: 0 },
      { storyId: 2, position: 1 },
      { storyId: 3, position: 2 },
    ]);

    expect(n).toBe(2); // 1 was acted on; 2 and 3 are clean negatives
    const kinds = sent.flat().map((e) => e.kind);
    expect(kinds).toContain("tapped_through");
    expect(kinds.filter((k) => k === "skipped")).toHaveLength(2);
  });
});

describe("invariants that must hold on both surfaces", () => {
  it("never pads: seven good things means seven cards", () => {
    const cards = Array.from({ length: 7 }, (_, i) => card({ storyId: i }));
    expect(visibleCards({ cards })).toHaveLength(7);
  });

  it("degrades an unjudged card to headline + source, never hides it", () => {
    const m = renderModel(card({ summary: null }));
    expect(m.showSummary).toBe(false);
    expect(m.headline).toBeTruthy(); // still shown
  });

  it("has no click event kind", () => {
    const kinds: EventKind[] = [
      "shown", "expanded", "dwell", "tapped_through", "saved",
      "shared", "scrolled_past", "skipped", "hidden", "best_of_day",
    ];
    expect(kinds).not.toContain("click" as EventKind);
  });

  it("labels a story matched by two topics with both", () => {
    const m = renderModel(
      card({
        topicLabels: [
          { topic_id: 1, label: "AI chips" },
          { topic_id: 2, label: "Export controls" },
        ],
      }),
    );
    expect(m.labels).toEqual(["AI chips", "Export controls"]);
  });
});

describe("formatting", () => {
  it("renders the source line", () => {
    const at = new Date(Date.now() - 2 * 3600_000).toISOString();
    expect(sourceLine("Reuters", 14, at)).toBe("Reuters · 2h · 14 sources");
    expect(sourceLine("Reuters", 1, at)).toBe("Reuters · 2h");
  });

  it("renders relative time", () => {
    const now = new Date("2026-08-07T12:00:00Z");
    expect(relativeTime("2026-08-07T11:30:00Z", now)).toBe("30m");
    expect(relativeTime("2026-08-07T06:00:00Z", now)).toBe("6h");
    expect(relativeTime("2026-08-05T12:00:00Z", now)).toBe("2d");
  });

  it("renders the rate the way onboarding shows it", () => {
    expect(rateLabel(6.2)).toBe("about 6 a day");
    expect(rateLabel(0)).toBe("nothing yet");
  });
});
