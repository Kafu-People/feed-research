import { CardItem } from "@/components/Card";
import { DayEnd } from "@/components/DayEnd";
import { DashboardClient } from "@/components/DashboardClient";
import { api } from "@/lib/api";
import { sessionToken } from "@/lib/session";
import { COPY } from "@techtrend/core";
import Link from "next/link";

// One user's screen: never statically cached, never shared at the edge.
export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const token = await sessionToken();
  if (!token) {
    return (
      <main>
        <h1>TechTrend</h1>
        <p>Describe what you want to follow, and see it immediately.</p>
        <p><Link href="/onboarding">Get started →</Link></p>
      </main>
    );
  }

  let data;
  try {
    data = await api(token).dashboard();
  } catch {
    return (
      <main>
        <h1>TechTrend</h1>
        <p className="rate">Could not reach the API. Is it running on :8000?</p>
      </main>
    );
  }

  // Server-rendered so the first card is HTML, not a fetch. The client
  // component below takes over feedback capture and keyboard shortcuts.
  return (
    <main>
      <h1>Today</h1>
      <DashboardClient initial={data}>
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
