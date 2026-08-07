import { NextResponse } from "next/server";

import { API_URL } from "@/lib/api";
import { sessionToken } from "@/lib/session";

/** Same-origin target for navigator.sendBeacon, which cannot set headers.
 *  The session token is attached server-side from the httpOnly cookie. */
export async function POST(req: Request) {
  const token = await sessionToken();
  const body = await req.text();
  const res = await fetch(`${API_URL}/v1/events`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    body,
  });
  return NextResponse.json({ ok: res.ok }, { status: res.ok ? 202 : res.status });
}
