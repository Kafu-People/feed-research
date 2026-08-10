import Link from "next/link";

import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

/** The board's topics — public, same list for everyone. */
export default async function TopicsPage() {
  const topics = await api().listTopics();

  return (
    <main>
      <p className="rate">
        <Link href="/">← Today</Link>
      </p>
      <h1>Topics</h1>
      <ol className="cards">
        {topics.map((t) => (
          <li className="card" key={t.id}>
            <h2>
              <Link href={`/topics/${t.id}`}>{t.title}</Link>
            </h2>
            <p className="meta">{t.must.slice(0, 6).join(" · ")}</p>
          </li>
        ))}
      </ol>
      <p style={{ marginTop: "1.5rem" }}>
        <Link href="/onboarding">Follow something new →</Link>
      </p>
    </main>
  );
}
