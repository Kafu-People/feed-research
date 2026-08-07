import { cookies } from "next/headers";

/** Refresh/session token lives in an httpOnly cookie -- NOT localStorage.
 *  An XSS bug must not be able to exfiltrate a long-lived credential. */
export const SESSION_COOKIE = "tt_session";

export async function sessionToken(): Promise<string | null> {
  const jar = await cookies();
  return jar.get(SESSION_COOKIE)?.value ?? null;
}
