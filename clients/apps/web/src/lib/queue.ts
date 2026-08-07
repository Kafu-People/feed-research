"use client";

import { createFeedbackQueue } from "@techtrend/core";

import { api } from "./api";
import { webStorage } from "./storage";

/**
 * One queue per browser session. A singleton because Server Components cannot
 * pass functions across the RSC boundary -- client components import this
 * directly instead of receiving handler props.
 */
export const feedback = createFeedbackQueue({
  storage: webStorage,
  transport: {
    async postEvents(batch) {
      // sendBeacon is what makes clean negatives survive a CLOSED TAB: a fetch
      // on visibilitychange is cancelled at unload, and the day's skips would
      // be lost -- along with the property that lets the personal layer learn
      // from hundreds of users instead of hundreds of thousands.
      const body = new Blob([JSON.stringify(batch)], { type: "application/json" });
      if (typeof navigator !== "undefined" && navigator.sendBeacon) {
        if (navigator.sendBeacon("/api/events", body)) return;
      }
      await api(null).postEvents(batch);
    },
  },
});
