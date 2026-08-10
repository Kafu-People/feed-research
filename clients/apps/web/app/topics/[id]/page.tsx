import Link from "next/link";
import { notFound } from "next/navigation";

import { CardItem } from "@/components/Card";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

/** One topic's feed — public, same for everyone. */
export default async function TopicFeedPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let cards;
  try {
    cards = await api().topicStories(Number(id));
  } catch {
    notFound();
  }
  const label = cards[0]?.topicLabels[0]?.label;

  return (
    <main>
      <p className="rate">
        <Link href="/">← Today</Link> · <Link href="/topics">All topics</Link>
      </p>
      <h1>{label ?? "This topic"}</h1>
      {cards.length === 0 && (
        <p className="rate">Nothing matched in the last 7 days. A quiet topic is allowed.</p>
      )}
      <ol className="cards">
        {cards.map((c, i) => (
          <CardItem key={c.storyId} card={c} position={i} />
        ))}
      </ol>
    </main>
  );
}
