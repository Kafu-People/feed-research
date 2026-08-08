import { NextResponse } from "next/server";

import { sessionToken } from "@/lib/session";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

/** Same-origin proxy for saving a topic (see draft/route.ts). */
export async function POST(req: Request) {
  const token = await sessionToken();
  if (!token) return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  const res = await fetch(`${API_URL}/v1/topics`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(await req.json()),
    cache: "no-store",
  });
  return NextResponse.json(await res.json(), { status: res.status });
}
