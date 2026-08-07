import { createClient } from "@techtrend/api-client";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Server Components read the session cookie; the browser passes the token. */
export function api(token?: string | null) {
  return createClient({ baseUrl: API_URL, token });
}
