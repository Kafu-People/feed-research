# 9 — Mobile app

← [Web app](08-web-app.md) · [Dev README](README.md) · next → [Shared client code](10-clients-shared.md)

React Native + Expo, TypeScript strict. **The second surface.** Web ships first
([web app](08-web-app.md)), then **one** store — not both at launch, which would double the
release surface while the risky parts are still being validated
([open questions](../architecture/16-open-questions.md)).

All non-visual logic — the feedback queue, the clean-negative rule, card display rules,
chip logic, formatting — is imported from `packages/core` and shared with web
([shared client code](10-clients-shared.md)). This document covers only what is genuinely
React Native.

---

## Structure

```
clients/apps/mobile/
├─ app/                          expo-router (file-based)
│  ├─ (auth)/sign-in.tsx  sign-up.tsx
│  ├─ (tabs)/index.tsx            ← the dashboard. The screen.
│  ├─ (tabs)/topics.tsx
│  ├─ onboarding/sentence.tsx     ← text box
│  ├─ onboarding/confirm.tsx      ← editable chips + rate + 3 headlines
│  └─ story/[id].tsx
├─ src/
│  ├─ components/  Card · Chips · TopicLabel · DayEnd · DismissToast
│  ├─ storage.ts   expo-sqlite adapter for core's Storage interface
│  ├─ store/       auth, settings (zustand)
│  └─ push.ts      APNs / FCM registration
└─ app.json
```

**The API client is generated from the backend's OpenAPI schema** (`make client`) and lives
in `packages/api-client`, shared with web. Response types are never hand-written, so a field
the API stops sending is a TypeScript error rather than an `undefined` at runtime.

---

## The six screens

| Screen | Does |
| --- | --- |
| Sentence | One text box. *"What do you want to follow?"* |
| Confirm | Chips + `47 in 7 days · about 6 a day` + three real headlines + Save |
| Dashboard | Cards from all topics, mixed, best first, each labelled |
| Story | Expanded card, source list, link out to the publisher |
| Topics | Subscriptions, edit chips, pending suggestions |
| Settings | Digest hour, push, account |

**Under a minute from install to a real, populated dashboard**
([journey](../architecture/10-user-journey.md)). The screen that makes this work is
Confirm — it turns a black box into something the user can correct in five seconds.

---

## Onboarding

```tsx
// onboarding/confirm.tsx
const { data, isLoading } = useTopicDraft(sentence);   // POST /v1/topics/draft

if (data?.ambiguity) return (
  <AmbiguityPrompt question={data.ambiguity} options={data.options} onPick={refine} />
);

return (
  <>
    <ChipGroup label="Watching for"     chips={must}     onAdd={…} onRemove={…} />
    <ChipGroup label="Especially"       chips={entities} onAdd={…} onRemove={…} />
    <ChipGroup label="Not interested in" chips={exclude} onAdd={…} onRemove={…} />
    <Rate count={data.count_7d} perDay={data.per_day} />   {/* "about 6 a day" */}
    <PreviewList stories={data.preview} />                 {/* three REAL headlines */}
    <Button title="Save" onPress={save} />
  </>
);
```

Three things this screen does that a text box can't
([match](../architecture/07-match.md)) — and each is a UI obligation, not a nicety:

1. **Shows what we understood.** Chips are always visible and always editable. Never hide
   the keywords.
2. **Shows the rate.** Too broad or too narrow is caught *before* it's wrong.
3. **Shows real stories instantly.** Only possible because the corpus already exists — the
   CC-NEWS backfill ([collect](../architecture/03-collect.md)) is what makes this screen
   possible at all.

The ambiguity prompt is one question with buttons. Unresolved ambiguity becomes a bad feed
the user can't diagnose, so asking is cheap and skipping is expensive.

---

## The dashboard

```tsx
const { data } = useDashboard();

<FlatList
  data={data.cards}
  renderItem={({ item, index }) => (
    <Card story={item} position={index}
          onExpand={() => track("expanded", item, index)}
          onTapThrough={() => { track("tapped_through", item, index); openBrowser(item.url); }}
          onHide={() => showDismissToast(item)} />
  )}
  ListFooterComponent={<DayEnd more={data.more} />}   // "That's today."
/>
```

**`ListFooterComponent` is not decoration.** The bottom exists; finishing is a feature
([deliver](../architecture/08-deliver.md)). There is no infinite scroll and no
`onEndReached` fetch — the client has no code path to request padding, matching the API's
absence of one.

`position` is passed on every event: it's what makes position-bias correction possible
server-side ([feedback](../architecture/09-feedback.md)).

### Card

```
┌────────────────────────────────────────────┐
│ [image]                                    │
│ Nvidia cleared to resume H20 sales to China│
│ Reuters · 2h · 14 sources        [AI chips]│
│ Two-sentence summary in our own words.     │
└────────────────────────────────────────────┘
```

- Tapping **14 sources** lists who else covered it.
- Tapping the **topic label** filters the dashboard to that topic — but the default
  ordering ignores topic boundaries entirely.
- Tapping the card body **leaves the app for the publisher**. That's the strongest positive
  signal there is, and the product is built to send it.
- `summary` may be `null` (unjudged, refused, or failed verification). The card degrades to
  headline + source rather than disappearing ([AI layer](06-ai-layer.md)).

---

## Feedback capture

Never block a UI transition on a network write. **The queue itself is shared code** — this
app supplies only the storage adapter and the flush triggers
([shared client code](10-clients-shared.md)).

```ts
// src/storage.ts — the only mobile-specific part
export const feedback = createFeedbackQueue({ storage: sqliteStorage, api });

// Flush on screen-exit, on background, and on day-end. Batched, fire-and-forget.
AppState.addEventListener("change", (s) => { if (s !== "active") feedback.flush(); });
```

### The clean-negative flush

```ts
async function onDayComplete(cards: Card[]) {
  const acted = await feedback.actedStoryIds();
  for (const e of cleanNegatives(shownCards(cards), acted))   // ← from packages/core
    await feedback.enqueue(e);
  await feedback.flush();
}
```

**This is the client half of the property that makes the whole learning system work.** With
a finite daily set the user has seen everything, so every un-acted card is a real negative —
learning from hundreds of users what would normally need hundreds of thousands
([feedback](../architecture/09-feedback.md)). It only holds because the API never pads.

`cleanNegatives` and the "shown" threshold are imported, not reimplemented. If web counted a
card as shown on render and mobile on viewport intersection, the two surfaces would feed the
personal layer different definitions of a negative — a silent, very hard-to-diagnose
corruption of the weights.

### Two natural moments

```tsx
// After the last card
<BestOfDay cards={cards} onPick={(c) => track("best_of_day", c, idx)} />

// On swipe-to-hide — a brief toast, most people ignore it
<Toast text="Hidden" action="Why?" onPress={showReasons} />
// wrong topic · already knew it · don't trust source · speculation · not this kind
```

The reasons matter because a thumbs-down means at least five different things, and
conflating them teaches the wrong lesson. And when a card was matched by a keyword, the
dismiss sheet offers *"Less about price targets"* — feedback on the **keyword** rather than
the article, which is the highest-leverage signal in the product because it edits the query.

---

## Offline

`expo-sqlite` holds the current dashboard and the outbound event queue. The daily set is
small — a dozen cards — so an offline open shows yesterday's set with a staleness note, and
events queued offline flush on reconnect. Nothing is lost because the phone was in a tunnel.

---

## Notifications

One daily digest at `digest_hour` in the user's timezone. Breaking alerts capped at two a
day, only for stories far above the user's normal threshold.

```ts
// Ignoring them yields FEWER, not more.
if (dismissedWithoutOpening >= 3) await api.patchSettings({ breaking: false });
```

That inversion is the point ([deliver](../architecture/08-deliver.md)): engagement-maximising
systems escalate when ignored. Treating a non-response as a signal to back off is the same
principle as never padding — the product asks for less attention when it has less to say.

---

## Build and release

```bash
npx expo start                       # dev
eas build --profile preview          # internal
eas build --profile production
eas update                           # OTA for JS-only changes
```

`make client` regenerates the typed API client from the backend's OpenAPI schema and is
part of CI: a backend response-model change that the app hasn't absorbed fails the build
rather than shipping a runtime surprise.

**Mobile is why the backend contract is additive-only.** Web updates in minutes, an
`eas update` in hours, but a native store release takes days to weeks — so the API adds
optional fields and never removes or retypes one until the oldest supported build is gone
([shared client code](10-clients-shared.md)).

---

## What differs from web

Same six screens, same events, same rules — different affordances
([web app](08-web-app.md)):

| | Mobile | Web |
| --- | --- | --- |
| Hide a card | Swipe | `x` key or button |
| Navigate | Scroll | `j` / `k` or scroll |
| Link out | In-app browser | `<a target="_blank">` with a real referrer |
| Flush trigger | `AppState` background | `visibilitychange` + `sendBeacon` |
| Token storage | `expo-secure-store` | httpOnly cookie |
| Push | APNs / FCM | Web Push (VAPID) |
| Offline | `expo-sqlite` | IndexedDB |

Everything in the left column is an affordance. Nothing in it is a behaviour: both surfaces
produce the same events, through the same queue, into the same weights.
