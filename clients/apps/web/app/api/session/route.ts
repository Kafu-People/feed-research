import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { SESSION_COOKIE } from "@/lib/session";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

/** Exchange credentials for a token, held in an httpOnly cookie -- the
 *  browser never sees it, so an XSS bug can't exfiltrate it. */
export async function POST(req: Request) {
  const { email, password } = (await req.json()) as { email: string; password: string };
  const res = await fetch(`${API_URL}/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
    cache: "no-store",
  });
  if (!res.ok) {
    return NextResponse.json({ error: "invalid credentials" }, { status: 401 });
  }
  const { access_token, expires_in } = (await res.json()) as {
    access_token: string;
    expires_in: number;
  };
  const jar = await cookies();
  jar.set(SESSION_COOKIE, access_token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    maxAge: expires_in,
    path: "/",
  });
  return NextResponse.json({ ok: true });
}

export async function DELETE() {
  const jar = await cookies();
  jar.delete(SESSION_COOKIE);
  return NextResponse.json({ ok: true });
}
