# 10 — Shared client code

← [Mobile app](09-mobile-app.md) · [Dev README](README.md) · next → [Configuration](11-config.md)

Two clients, one set of rules. **Everything that isn't pixels is shared exactly once** —
because several of the rules in [invariants](../architecture/14-invariants.md) are only true
if both surfaces implement them identically.

---

## Monorepo

```
clients/
├─ package.json                  pnpm workspaces
├─ packages/
│  ├─ api-client/                generated from OpenAPI + auth/refresh transport
│  │  ├─ schema.d.ts             ← generated; never hand-edited
│  │  ├─ client.ts               typed fetch wrapper
│  │  └─ auth.ts                 refresh rotation, 401 retry
│  └─ core/                      ALL non-visual logic
│     ├─ types.ts                Card, TopicDraft, EventKind (re-exported from schema)
│     ├─ feedback/
│     │  ├─ queue.ts             enqueue / flush / retry
│     │  ├─ storage.ts           ← Storage interface (platform-injected)
│     │  └─ dayEnd.ts            the clean-negative computation
│     ├─ display/
│     │  ├─ card.ts              summary-null degrade, source line, labels
│     │  └─ format.ts            relative time, "about 6 a day", source counts
│     └─ topics/chips.ts         chip add/remove/validate, draft diffing
├─ apps/
│  ├─ web/                       Next.js + React DOM      ([16](08-web-app.md))
│  └─ mobile/                    Expo + React Native      ([11](09-mobile-app.md))
└─ .dependency-cruiser.cjs       boundary enforcement
```

`pnpm` workspaces, TypeScript project references. `packages/core` is `"type": "module"`,
zero runtime dependencies, and builds to plain ES modules — it must be importable by a
bundler and by Metro without configuration gymnastics.

---

## What is shared, and why each thing has to be

| Shared | Why it can't be duplicated |
| --- | --- |
| **`api-client`** | Generated from the backend's OpenAPI. Hand-writing it twice means two chances to drift from the server |
| **Feedback queue** | Both surfaces must enqueue, batch, retry and de-duplicate identically or the weights learn from a mixture of two behaviours |
| **`dayEnd.ts`** | **The clean-negative rule.** See below — this is the one that actually matters |
| **Card display rules** | `summary === null` must degrade the same way on both, or one surface silently hides unjudged stories |
| **Chip logic** | The onboarding contract ("shows what we understood") is the same promise on both |
| **Formatting** | "2h · 14 sources · about 6 a day" — cosmetic drift here reads as two different products |

| Not shared | Why |
| --- | --- |
| Components | Different idioms: `<a>` and semantic HTML vs `Pressable` and native gestures |
| Navigation | `next/navigation` vs `expo-router` |
| Storage | IndexedDB vs `expo-sqlite` — injected through the `Storage` interface |
| Auth token storage | httpOnly cookie vs `expo-secure-store` — a genuine platform security difference |
| Notifications | Web Push (VAPID) vs APNs/FCM |
| Styling | Tailwind vs RN StyleSheet |

---

## The one that matters most

```ts
// packages/core/src/feedback/dayEnd.ts
/**
 * With a finite daily set the user has seen everything, so every card shown
 * and not acted on is a REAL negative. That property is what lets the personal
 * layer learn from hundreds of users instead of hundreds of thousands.
 *
 * It only holds if BOTH clients compute it the same way. Hence: one function.
 */
export function cleanNegatives(shown: ShownCard[], acted: ReadonlySet<number>): EventDraft[] {
  return shown
    .filter((c) => !acted.has(c.storyId))
    .map((c) => ({ kind: "skipped", storyId: c.storyId, position: c.position }));
}
```

If web counted a card as "shown" on render and mobile counted it on 50% viewport
intersection, the two surfaces would feed the personal layer different definitions of a
negative — and the weights would be learned from a blend of two incompatible signals. That
is a subtle, silent, and very hard-to-diagnose failure, so the definition lives in one file
that both platforms import.

The same logic drives the shared "shown" rule:

```ts
// A card counts as shown once it has been ≥50% visible for ≥1s.
// Web: IntersectionObserver. Mobile: FlatList viewability config.
// Both feed the SAME predicate.
export const SHOWN_THRESHOLD = { ratio: 0.5, ms: 1000 } as const;
```

---

## Storage injection

`core` never imports a platform API. Each app supplies one adapter:

```ts
// packages/core/src/feedback/storage.ts
export interface Storage {
  enqueue(e: EventDraft): Promise<void>;
  takePending(limit: number): Promise<StoredEvent[]>;
  clear(ids: string[]): Promise<void>;
  actedStoryIds(): Promise<Set<number>>;
}
```

```ts
// apps/web/src/storage.ts      → IndexedDB (idb-keyval)
// apps/mobile/src/storage.ts   → expo-sqlite
export const feedback = createFeedbackQueue({ storage: webStorage, api });
```

One consequence worth stating: because the queue is platform-agnostic, its tests run once
in Node against an in-memory adapter and cover both clients. There is no "did we get the
retry logic right on Android too" question.

---

## The generated client

```bash
make client        # from the repo root
```

```makefile
client:
	curl -s $(API_URL)/openapi.json > clients/packages/api-client/openapi.json
	cd clients/packages/api-client && pnpm openapi-typescript openapi.json -o src/schema.d.ts
	cd clients && pnpm -r build
```

Runs in CI. **A backend response-model change that the clients haven't absorbed fails the
build** rather than shipping a runtime surprise to one surface and not the other.

Types flow one way only: Postgres → SQLAlchemy → Pydantic → OpenAPI → TypeScript. No
TypeScript type describing an API response is written by hand anywhere.

---

## Boundary enforcement

The mirror of the backend's `import-linter` contract ([repo layout](01-repo-layout.md)):

```js
// .dependency-cruiser.cjs
forbidden: [
  { name: "core-is-platform-free",
    from: { path: "^packages/core" },
    to:   { path: "react-native|next/|expo|^react-dom|window|document" } },

  { name: "apps-do-not-cross-import",
    from: { path: "^apps/web" },  to: { path: "^apps/mobile" } },

  { name: "no-hand-rolled-api-calls",
    from: { path: "^apps/(web|mobile)" },
    to:   { path: "^(node-fetch|axios)$" } },   // must go through api-client
]
```

`pnpm lint:boundaries` runs in CI. The third rule is the important one: it stops a hurried
`fetch('/v1/dashboard')` in a component from bypassing auth refresh, error mapping, and the
generated types.

---

## Testing shared logic once

```
packages/core/src/**/*.test.ts     vitest, Node, no DOM, no RN
```

```ts
it("does not pad, on either surface", () => {
  expect(visibleCards(dashboard({ cards: 7 }))).toHaveLength(7);
});

it("treats an un-acted shown card as a negative", () => {
  const out = cleanNegatives(shown(10), new Set([1, 2]));
  expect(out).toHaveLength(8);
  expect(out.every((e) => e.kind === "skipped")).toBe(true);
});

it("degrades an unjudged card to headline + source", () => {
  expect(renderModel({ ...card, summary: null }).showSummary).toBe(false);
});
```

Each app then tests only what is genuinely its own: web tests routing, keyboard shortcuts
and `sendBeacon`; mobile tests gestures, background flush and push registration.

---

## Versioning and release

`core` and `api-client` are workspace packages, not published — both apps always build
against `HEAD`. There is no version skew *between clients*, but there is between a client
and a **deployed** backend:

| Surface | Update mechanism | Skew window |
| --- | --- | --- |
| Web | Deploy | Minutes |
| Mobile | `eas update` (JS-only) | Hours |
| Mobile | Store release (native) | Days–weeks |

So the backend contract is **additive-only**: new optional fields, never a removed or
retyped one, until the oldest supported build is gone. That constraint exists because of
mobile, and web inherits it for free — which is another reason the clients share the
generated types rather than each adapting to the API separately.

---

## Keeping two UIs coherent

Two view layers is the real cost of this choice ([the fork](08-web-app.md)). What keeps
them from diverging into two products:

- **Shared display models.** `renderModel(card)` returns *what* to show — summary or not,
  which labels, which source line. Each app decides only *how* to draw it.
- **Shared copy.** `packages/core/src/copy.ts` holds every user-visible string, including
  `"That's today."` and the five dismissal reasons. A phrase changes in one place.
- **One screen list.** Both apps implement the same six screens
  ([journey](../architecture/10-user-journey.md)); adding a screen to one is a decision, not
  a drift.

What is *allowed* to differ is affordance, not behaviour: web has keyboard shortcuts and
hover, mobile has swipe-to-hide. Both produce the same events, through the same queue, into
the same weights.
