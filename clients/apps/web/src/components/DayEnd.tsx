import { COPY, type Card } from "@techtrend/core";
import { CardItem } from "./Card";

/**
 * The bottom exists. Finishing is a feature -- everyone else optimises endless
 * scroll. There is no onEndReached fetch here, mirroring the API's absent
 * backfill path (invariant #10).
 */
export function DayEnd({ more }: { more: Card[] }) {
  return (
    <>
      <p className="day-end">{COPY.dayEnd}</p>
      {more.length > 0 && (
        <details>
          <summary className="rate">{COPY.moreBelow}</summary>
          <ol className="cards">
            {more.map((c, i) => (
              <CardItem key={c.storyId} card={c} position={100 + i} />
            ))}
          </ol>
        </details>
      )}
    </>
  );
}
