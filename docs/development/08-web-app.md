# 8 — Web app

← [API surface](07-api.md) · [Dev README](README.md) · next → [Mobile app](09-mobile-app.md)

**Next.js (App Router) + React DOM + TypeScript strict.** The first surface to reach real
users, and the one where onboarding actually works properly.

Non-visual logic comes from `packages/core`; this document covers only what is genuinely
web ([shared client code](10-clients-shared.md)).

---

## Why web ships first

[Open questions](../architecture/16-open-questions.md) recommends picking one platform
first — but that is about **app stores**, and web isn't one. Three reasons it leads:

1. **Onboarding is a text box and a chip editor.** Typing a sentence and correcting a dozen
   keywords is materially better with a keyboard and a wide screen. M4 and M5 exist to
   validate exactly that screen ([milestones](17-milestones.md)).
2. **No review queue.** The distiller prompt and the confirm screen will need many
   iterations. Web ships them hourly; a store ships them next week.
3. **Link-out is the product's strongest signal.** Tapping through to the publisher is the
   strongest positive feedback there is ([feedback](../architecture/09-feedback.md)) — and
   on the web it's an ordinary `<a>`, with middle-click, open-in-new-tab, and a real
   referrer that tells the publisher we sent the traffic.

Then **one** store, not both — the original recommendation, unchanged.

---

## Routes

```
apps/web/app/
├─ (marketing)/page.tsx           landing (public, indexable)
├─ (auth)/sign-in/  sign-up/
├─ (app)/
│  ├─ layout.tsx                  shell: nav, auth guard, noindex
│  ├─ page.tsx                    ← the dashboard. The screen.
│  ├─ story/[id]/page.tsx         expanded card + source list
│  ├─ topics/page.tsx             subscriptions, chips, suggestions
│  └─ settings/page.tsx
└─ onboarding/
   ├─ page.tsx                    the sentence
   └─ confirm/page.tsx            chips + rate + three real headlines
```

Same six screens as mobile ([journey](../architecture/10-user-journey.md)). Adding a screen
to one client and not the other is a decision, not an accident.

---

## Rendering and auth

The dashboard is per-user and never cached at the edge, so the model is simple:

| Route | Rendering | Why |
| --- | --- | --- |
| `(marketing)` | Static | Public, indexable, cacheable |
| `(auth)` | Static + client form | No user data |
| `(app)/*` | **Server Component reading the session cookie**, then client islands | Personal data; must not be shared-cached |
| `onboarding/confirm` | Client | Live draft round-trips as the user edits |

```ts
// app/(app)/page.tsx — Server Component
export const dynamic = "force-dynamic";   // never statically cached; it's one user's screen

export default async function Dashboard() {
  const data = await api.dashboard({ cookies: cookies() });
  return <DashboardClient initial={data} />;   // hydrates, then owns feedback + shortcuts
}
```

### Tokens

This is a real divergence from mobile, and the right one:

| | Web | Mobile |
| --- | --- | --- |
| Refresh token | **httpOnly, Secure, SameSite=Lax cookie** | `expo-secure-store` |
| Access token | In memory only | In memory |

An httpOnly cookie is not readable by JavaScript, so an XSS bug cannot exfiltrate a
long-lived credential. `localStorage` would be the easy choice and the wrong one. Serving
the API on the same parent domain (`api.techtrend.example`) keeps the cookie first-party
and avoids CORS entirely.

---

## The dashboard

```tsx
"use client";

export function DashboardClient({ initial }: { initial: DashboardOut }) {
  const { data } = useDashboard({ initialData: initial });
  useShownTracking(data.cards);        // IntersectionObserver → shared SHOWN_THRESHOLD
  useKeyboardShortcuts(data.cards);

  return (
    <main className="mx-auto max-w-2xl">
      <ol>
        {data.cards.map((card, i) => <Card key={card.storyId} card={card} position={i} />)}
      </ol>
      <DayEnd more={data.more} />       {/* "That's today." */}
    </main>
  );
}
```

**Single column, `max-w-2xl`, even on a 27" monitor.** The temptation on desktop is a
multi-column magazine grid — and it would be wrong. The product is *one screen, one ordered
list*, and ordering ignores topic boundaries entirely
([deliver](../architecture/08-deliver.md)). A grid implies a hierarchy the ranking doesn't
have and quietly destroys the meaning of position, which is the signal
[feedback](../architecture/09-feedback.md) needs for bias correction. Wide screens get more
whitespace, not more columns.

**`<ol>`, not `<div>`.** The ordering is the product; the markup should say so.

**No infinite scroll.** `DayEnd` renders the line, then `more` below it. There is no
`onScrollEnd` fetch, mirroring the API's absent backfill path
([invariant #10](../architecture/14-invariants.md)).

### The card is an anchor

```tsx
<li>
  <article>
    <a href={card.url} target="_blank" rel="noopener"
       referrerPolicy="origin"                        // publishers SEE that we sent this
       onClick={() => track("tapped_through", card, position)}>
      <h2>{card.headline}</h2>
    </a>
    <SourceLine name={card.sourceName} count={card.sourceCount} at={card.publishedAt} />
    {card.summary && <p>{card.summary}</p>}   {/* null → degrade, don't hide */}
    <TopicLabels labels={card.topicLabels} matchedBy={card.matchedBy} />
  </article>
</li>
```

`referrerPolicy="origin"` is deliberate. We send readers **to** publishers; the whole legal
posture is headline + our summary + link out
([invariant #1](../architecture/14-invariants.md)). Sending the referrer means a publisher's
analytics shows TechTrend as a traffic source — which is the relationship we want on record
when someone asks what we do with their content.

`rel="noopener"` without `noreferrer`: security without stripping the attribution.

### Keyboard shortcuts

The affordance mobile can't have:

| Key | Action |
| --- | --- |
| `j` / `k` | Next / previous card |
| `o` or `Enter` | Open at the publisher |
| `e` | Expand summary |
| `x` | Hide (opens the reason toast) |
| `b` | Best of day |
| `?` | Shortcut help |

Each one emits the same event through the same shared queue as its touch equivalent
([shared client code](10-clients-shared.md)). Different affordance, identical signal.

---

## Onboarding — the reason web goes first

```tsx
// onboarding/confirm/page.tsx
const { data, isFetching } = useTopicDraft(sentence);

if (data?.ambiguity)
  return <AmbiguityPrompt question={data.ambiguity} options={data.options} onPick={refine} />;

return (
  <form onSubmit={save}>
    <ChipGroup label="Watching for"      chips={must}     onAdd={…} onRemove={…} />
    <ChipGroup label="Especially"        chips={entities} onAdd={…} onRemove={…} />
    <ChipGroup label="Not interested in" chips={exclude}  onAdd={…} onRemove={…} />
    <Rate count={data.count_7d} perDay={data.per_day} live={isFetching} />
    <PreviewList stories={data.preview} />
    <button type="submit">Save</button>
  </form>
);
```

Web-specific affordances that make this screen genuinely better than its mobile twin:

- **Type-ahead chip entry.** `Enter` or `,` commits a chip; `Backspace` on an empty input
  removes the last one. Standard token-input behaviour people already know.
- **Live re-count, debounced.** Editing a chip re-runs the preview at ~400ms. *"about 6 a
  day"* updates as the user narrows — so too broad or too narrow is caught **before** it's
  wrong ([match](../architecture/07-match.md)), not after a week of bad results.
- **All three chip groups visible at once.** No scrolling between "watching for" and "not
  interested in", so the whole understood topic is legible in one glance.
- **`aria-live` on the rate.** Screen readers hear the count change as chips are edited.

The rule from the architecture holds unchanged: **never hide the keywords.** Chips are
always visible and always editable.

---

## Feedback on the web

Same shared queue, three web-specific transports:

```ts
// Dwell: measured, not guessed
useEffect(() => {
  const io = new IntersectionObserver(onVisibility, { threshold: SHOWN_THRESHOLD.ratio });
  cards.forEach((el) => io.observe(el));
  return () => io.disconnect();
}, [cards]);

// Tab hidden → flush now; the user may never come back to this tab
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") feedback.flush({ beacon: true });
});
```

```ts
// packages/core calls this through the injected transport
async function flushWithBeacon(batch: EventDraft[]) {
  const blob = new Blob([JSON.stringify(batch)], { type: "application/json" });
  if (!navigator.sendBeacon("/v1/events", blob)) await api.postEvents(batch); // fallback
}
```

**`sendBeacon` is what makes clean negatives survive a closed tab.** A `fetch` on
`visibilitychange` is cancelled when the page unloads; the day's skips would be lost, and
with them the property that makes learning work at hundreds of users instead of hundreds of
thousands ([feedback](../architecture/09-feedback.md)). On mobile the equivalent is the
background flush.

Events queued while offline sit in IndexedDB and flush on reconnect — same queue, different
storage adapter.

---

## Notifications

Web Push (VAPID), registered through a service worker. Parity with mobile, same rules:

- One digest at `digest_hour` in the user's timezone.
- Breaking capped at **two a day**.
- **Ignore them and you get fewer, not more** — three dismissals without opening turns
  breaking alerts off ([deliver](../architecture/08-deliver.md)).

Web push permission is asked **after** the first successful dashboard visit, never on first
load. A permission prompt before the product has shown value is how you get a permanent
denial.

---

## SEO and indexing

Honest answer, because it interacts with the legal rules:

| Route | Indexed |
| --- | --- |
| `(marketing)` | Yes |
| `(auth)`, `onboarding` | No |
| `(app)/*` | **`noindex`** — it is one person's personal screen |

There is no public archive of stories, and there shouldn't be one by default: we hold
headlines, our own summaries and thumbnails, and publishing that at scale as a browsable
corpus is a materially different legal posture from showing it to a signed-in user who asked
for it ([invariants](../architecture/14-invariants.md) #1, #5).

**Public topic pages are a product decision, not an engineering one.** They would be a real
acquisition channel and they need a licensing position first. Flagging it here rather than
building it.

---

## Performance budget

| Metric | Budget | Why it's reachable |
| --- | --- | --- |
| LCP | < 1.5s | Dashboard is server-rendered; the first card is HTML, not a fetch |
| JS shipped | < 150KB gzipped | No RN compatibility layer, no chart library, ~6 screens |
| CLS | < 0.05 | Card image slots are reserved at fixed aspect ratio |
| Interaction | < 100ms | Feedback is local-first; the network write is fire-and-forget |

The bundle number is the concrete payoff of the shared-logic/separate-UI choice: web ships
React DOM and nothing else, rather than React Native's web compatibility layer.

---

## Accessibility

Not a checklist item here — the product is a reading list, so this **is** the product:

- Semantic `<ol>` / `<li>` / `<article>` / `<h2>`; headline order is DOM order.
- Every card reachable and openable by keyboard; the shortcut layer is an addition, never
  the only route.
- Visible focus rings, never `outline: none`.
- `aria-live="polite"` on the onboarding rate and on the dismiss toast.
- `prefers-reduced-motion` respected on the dismiss animation.
- Contrast ≥ 4.5:1, verified in CI with axe.

---

## Deployment

Node runtime (the app reads cookies and proxies auth), same container host as the API
([deployment](15-deployment.md)):

```
web   →  next build && next start   ·  2 × small  ·  scales with users
```

Served on the apex domain with the API at `api.` — first-party cookies, no CORS
preflight on every request, and a shared session boundary.

`make client` regenerates the typed API client for both apps and runs in CI, so a backend
response-model change that web hasn't absorbed fails the build
([shared client code](10-clients-shared.md)).
