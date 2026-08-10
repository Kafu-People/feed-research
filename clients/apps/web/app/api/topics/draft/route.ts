import { NextResponse } from "next/server";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

/** Same-origin proxy for the distiller call. Public-board mode: no auth. */
export async function POST(req: Request) {
  const res = await fetch(`${API_URL}/v1/topics/draft`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(await req.json()),
    cache: "no-store",
  });
  return NextResponse.json(await res.json(), { status: res.status });
}
