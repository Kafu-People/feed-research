import { renderModel, sourceLine, type Card } from "@techtrend/core";

/**
 * The card is an ANCHOR, not a synthetic press handler.
 *
 * Tapping through to the publisher means a real <a>: middle-click,
 * open-in-new-tab, and a referrer that tells the publisher we sent the
 * traffic. Public-board mode: no feedback capture, so this is a pure
 * server component.
 */
export function CardItem({ card, position }: { card: Card; position: number }) {
  const m = renderModel(card);

  return (
    <li className="card" data-story-id={card.storyId} data-position={position}>
      <article>
        <h2>
          <a
            href={card.url}
            target="_blank"
            rel="noopener"
            // Deliberate: publishers' analytics should show TechTrend as the
            // traffic source. `noreferrer` would strip that attribution.
            referrerPolicy="origin"
          >
            {m.headline}
          </a>
        </h2>

        <p className="meta">
          {sourceLine(card.sourceName, card.sourceCount, card.publishedAt)}
          {card.topicLabels.map((t) => (
            <a className="label" key={t.label} href={`/topics/${t.topic_id}`}>
              {t.label}
            </a>
          ))}
        </p>

        {/* summary === null means unjudged/refused: degrade to headline +
            source, never hide the event. */}
        {m.showSummary && <p className="summary">{m.summary}</p>}

        {/* No summary of ours yet: the publisher's own preview snippet,
            quoted and attributed — their words, never the body. */}
        {m.showQuote && (
          <p className="summary quote">
            &ldquo;{m.quote}&rdquo; — {card.sourceName}
          </p>
        )}
      </article>
    </li>
  );
}
