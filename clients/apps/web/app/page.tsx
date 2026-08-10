import { CardItem } from "@/components/Card";
import { DayEnd } from "@/components/DayEnd";
import { DashboardClient } from "@/components/DashboardClient";
import { api } from "@/lib/api";
import { COPY } from "@techtrend/core";
import Link from "next/link";

// The board changes as stories arrive: never statically cached.
export const dynamic = "force-dynamic";

/** The global public board: one shared feed, the same for every visitor. */
export default async function DashboardPage() {
  let data;
  try {
    data = await api().dashboard();
  } catch {
    return (
      <main>
        <h1>TechTrend</h1>
        <p className="rate">Could not reach the API. Is it running on :8000?</p>
      </main>
    );
  }

  return (
    <main>
      <p className="rate">
        <Link href="/topics">Topics</Link> · <Link href="/onboarding">Follow something new</Link>
      </p>
      <h1>Today</h1>
      <DashboardClient>
        <ol className="cards">
          {data.cards.map((c, i) => (
            <CardItem key={c.storyId} card={c} position={i} />
          ))}
        </ol>
        {data.cards.length === 0 && <p className="rate">{COPY.quietDay}</p>}
        <DayEnd more={data.more} />
      </DashboardClient>
    </main>
  );
}
