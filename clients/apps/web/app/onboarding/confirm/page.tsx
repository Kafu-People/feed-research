"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { COPY, rateLabel, type Card, type TopicDraft } from "@techtrend/core";

/** Raw wire shape from the same-origin proxy (snake_case). */
interface RawDraft {
  title: string;
  must: string[];
  should: string[];
  entities: string[];
  exclude: string[];
  ambiguity: string | null;
  options: string[];
  count_7d: number;
  per_day: number;
  preview: {
    story_id: number;
    headline: string;
    summary: string | null;
    description: string | null;
    source_name: string;
    source_count: number;
    published_at: string;
    image_url: string | null;
    url: string;
  }[];
}

const toDraft = (r: RawDraft): TopicDraft => ({
  title: r.title,
  must: r.must,
  should: r.should,
  entities: r.entities,
  exclude: r.exclude,
  ambiguity: r.ambiguity,
  options: r.options,
  count7d: r.count_7d,
  perDay: r.per_day,
  preview: r.preview.map(
    (c): Card => ({
      storyId: c.story_id,
      headline: c.headline,
      summary: c.summary,
      description: c.description,
      sourceName: c.source_name,
      sourceCount: c.source_count,
      publishedAt: c.published_at,
      imageUrl: c.image_url,
      url: c.url,
      topicLabels: [],
      matchedBy: [],
    }),
  ),
});

/**
 * The screen web exists for.
 *
 * Three things it does that a text box can't:
 *   1. Shows what we understood  -- a misreading is caught in five seconds
 *   2. Shows the rate            -- too broad/narrow is caught BEFORE it's wrong
 *   3. Shows real stories        -- because the corpus already exists
 */
function Confirm() {
  const sentence = useSearchParams().get("s") ?? "";
  const [draft, setDraft] = useState<TopicDraft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!sentence) return;
    void fetch("/api/topics/draft", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sentence }),
    })
      .then((res) => {
        if (res.status === 401) {
          // Reading the sentence needs an account; come straight back after.
          router.push(`/login?next=${encodeURIComponent(`${pathname}?s=${sentence}`)}`);
          return null;
        }
        if (!res.ok) throw new Error("Could not read that. Try rephrasing?");
        return res.json() as Promise<RawDraft>;
      })
      .then((raw) => raw && setDraft(toDraft(raw)))
      .catch((e: Error) => setError(e.message));
  }, [sentence, router, pathname]);

  if (error) return <main><h1>Hmm</h1><p className="rate">{error}</p></main>;
  if (!draft) return <main><h1>Reading that…</h1></main>;

  // Unresolved ambiguity becomes a bad feed the user can't diagnose, so we ask
  // ONE question with buttons rather than guessing.
  if (draft.ambiguity) {
    return (
      <main>
        <h1>{draft.ambiguity}</h1>
        <div className="chips">
          {draft.options.map((o) => (
            <button className="chip" key={o} onClick={() => setDraft({ ...draft, ambiguity: null })}>
              {o}
            </button>
          ))}
        </div>
      </main>
    );
  }

  const update = (key: keyof TopicDraft, values: string[]) =>
    setDraft({ ...draft, [key]: values });

  return (
    <main>
      <h1>{draft.title}</h1>

      {/* Never hide the keywords. Always visible, always editable. */}
      <ChipGroup
        label={COPY.watchingFor}
        chips={draft.must}
        onChange={(v) => update("must", v)}
      />
      <ChipGroup
        label={COPY.especially}
        chips={draft.entities}
        onChange={(v) => update("entities", v)}
      />
      <ChipGroup
        label={COPY.notInterested}
        chips={draft.exclude}
        onChange={(v) => update("exclude", v)}
      />

      <p className="rate" aria-live="polite">
        {draft.count7d} stories in the last 7 days · {rateLabel(draft.perDay)}
      </p>

      {draft.preview.length > 0 && (
        <ol className="cards">
          {draft.preview.slice(0, 3).map((c) => (
            <li className="card" key={c.storyId}>
              <h2>{c.headline}</h2>
            </li>
          ))}
        </ol>
      )}

      <p style={{ marginTop: "1.5rem" }}>
        <button
          className="primary"
          disabled={saved}
          onClick={() => {
            void fetch("/api/topics", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                title: draft.title,
                must: draft.must,
                should: draft.should,
                entities: draft.entities,
                exclude: draft.exclude,
              }),
            })
              .then((res) => {
                if (!res.ok) throw new Error("Could not save.");
                setSaved(true);
                // Matching runs as stories arrive; the dashboard is the payoff.
                setTimeout(() => {
                  router.push("/");
                  router.refresh();
                }, 600);
              })
              .catch((e: Error) => setError(e.message));
          }}
        >
          {saved ? "Saved ✓" : "Save"}
        </button>
      </p>
    </main>
  );
}

function ChipGroup({
  label,
  chips,
  onChange,
}: {
  label: string;
  chips: string[];
  onChange: (v: string[]) => void;
}) {
  const [input, setInput] = useState("");
  return (
    <section>
      <strong style={{ fontSize: ".85rem" }}>{label}</strong>
      <div className="chips">
        {chips.map((c) => (
          <span className="chip" key={c}>
            {c}
            <button
              aria-label={`Remove ${c}`}
              onClick={() => onChange(chips.filter((x) => x !== c))}
            >
              ×
            </button>
          </span>
        ))}
      </div>
      <input
        type="text"
        value={input}
        placeholder="+ add"
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => {
          // Standard token-input behaviour people already know.
          if ((e.key === "Enter" || e.key === ",") && input.trim()) {
            e.preventDefault();
            onChange([...new Set([...chips, input.trim()])]);
            setInput("");
          } else if (e.key === "Backspace" && !input && chips.length) {
            onChange(chips.slice(0, -1));
          }
        }}
      />
    </section>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<main><h1>…</h1></main>}>
      <Confirm />
    </Suspense>
  );
}
