import { createFeedbackQueue } from "@techtrend/core";
import { createClient } from "@techtrend/api-client";

import { sqliteStorage } from "./storage";

export const API_URL = process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000";

let token: string | null = null;
export const setToken = (t: string | null) => { token = t; };

/** Same queue as web. Only the storage adapter and flush triggers differ. */
export const feedback = createFeedbackQueue({
  storage: sqliteStorage,
  transport: {
    async postEvents(batch) {
      await createClient({ baseUrl: API_URL, token }).postEvents(batch);
    },
  },
});
