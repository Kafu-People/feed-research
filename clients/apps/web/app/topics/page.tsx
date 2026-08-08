import Link from "next/link";
import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import { sessionToken } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function TopicsPage() {
  const token = await sessionToken();
  if (!token) redirect("/login?next=/topics");

  const topics = await api(token).listTopics();

  return (
    <main>
      <p className="rate">
        <Link href="/">← Today</Link>
      </p>
      <h1>Your topics</h1>
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
