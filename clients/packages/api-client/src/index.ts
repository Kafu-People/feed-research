/**
 * The typed API client. Shared by web and mobile.
 *
 * Response types are GENERATED from the backend's OpenAPI schema (`make client`),
 * never hand-written -- a field the API stops sending is a TypeScript error, not
 * an `undefined` at runtime.
 */

import type { Card, Dashboard, EventDraft, TopicDraft } from "@techtrend/core";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

export interface ClientOptions {
  baseUrl: string;
  /** Web passes cookies; mobile passes a bearer token from secure storage. */
  token?: string | null;
  fetchImpl?: typeof fetch;
}

interface RawCard {
  story_id: number;
  headline: string;
  summary: string | null;
  description: string | null;
  source_name: string;
  source_count: number;
  published_at: string;
  image_url: string | null;
  url: string;
  topic_labels: { topic_id: number; label: string }[];
  matched_by: string[];
}

const toCard = (c: RawCard): Card => ({
  storyId: c.story_id,
  headline: c.headline,
  summary: c.summary,
  description: c.description ?? null,
  sourceName: c.source_name,
  sourceCount: c.source_count,
  publishedAt: c.published_at,
  imageUrl: c.image_url,
  url: c.url,
  topicLabels: c.topic_labels,
  matchedBy: c.matched_by,
});

export function createClient(opts: ClientOptions) {
  const doFetch = opts.fetchImpl ?? fetch;

  async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
    const res = await doFetch(`${opts.baseUrl}${path}`, {
      ...init,
      headers: {
        "content-type": "application/json",
        ...(opts.token ? { authorization: `Bearer ${opts.token}` } : {}),
        ...(init.headers ?? {}),
      },
    });
    if (!res.ok) {
      const body = (await res.json().catch(() => ({}))) as {
        error?: { code?: string; message?: string };
        detail?: { error?: { code?: string; message?: string } };
      };
      const err = body.error ?? body.detail?.error;
      // Clients switch on a CODE, never on a message string.
      throw new ApiError(res.status, err?.code ?? "unknown", err?.message ?? res.statusText);
    }
    return (res.status === 204 ? undefined : await res.json()) as T;
  }

  return {
    async signup(email: string, password: string) {
      return call<{ access_token: string; expires_in: number }>("/v1/auth/signup", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
    },

    async login(email: string, password: string) {
      return call<{ access_token: string; expires_in: number }>("/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
    },

    async dashboard(): Promise<Dashboard> {
      const raw = await call<{
        cards: RawCard[];
        generated_at: string;
        done: boolean;
        more: RawCard[];
      }>("/v1/dashboard");
      return {
        cards: raw.cards.map(toCard),
        generatedAt: raw.generated_at,
        done: raw.done,
        more: raw.more.map(toCard),
      };
    },

    async draftTopic(sentence: string): Promise<TopicDraft> {
      const raw = await call<{
        title: string; must: string[]; should: string[]; entities: string[];
        exclude: string[]; ambiguity: string | null; options: string[];
        count_7d: number; per_day: number; preview: RawCard[];
      }>("/v1/topics/draft", { method: "POST", body: JSON.stringify({ sentence }) });
      return {
        title: raw.title, must: raw.must, should: raw.should, entities: raw.entities,
        exclude: raw.exclude, ambiguity: raw.ambiguity, options: raw.options,
        count7d: raw.count_7d, perDay: raw.per_day, preview: raw.preview.map(toCard),
      };
    },

    async saveTopic(t: Pick<TopicDraft, "title" | "must" | "should" | "entities" | "exclude">) {
      return call<{ id: number; title: string; subscriber_count: number }>("/v1/topics", {
        method: "POST",
        body: JSON.stringify(t),
      });
    },

    async listTopics() {
      return call<{ id: number; title: string; must: string[] }[]>("/v1/topics");
    },

    async topicStories(topicId: number): Promise<Card[]> {
      const raw = await call<RawCard[]>(`/v1/topics/${topicId}/stories`);
      return raw.map(toCard);
    },

    async postEvents(batch: EventDraft[]): Promise<void> {
      await call<{ accepted: number }>("/v1/events", {
        method: "POST",
        body: JSON.stringify(
          batch.map((e) => ({
            story_id: e.storyId ?? null,
            kind: e.kind,
            reason: e.reason ?? null,
            dwell_ms: e.dwellMs ?? null,
            position: e.position ?? null,
          })),
        ),
      });
    },
  };
}

export type Client = ReturnType<typeof createClient>;
