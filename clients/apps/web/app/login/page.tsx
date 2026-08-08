"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  return (
    <main>
      <h1>Sign in</h1>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          void fetch("/api/session", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password }),
          })
            .then((res) => {
              if (!res.ok) throw new Error("Wrong email or password.");
              router.push("/");
              router.refresh();
            })
            .catch((err: Error) => setError(err.message))
            .finally(() => setBusy(false));
        }}
      >
        <p>
          <input
            type="email"
            autoFocus
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            aria-label="Email"
          />
        </p>
        <p style={{ marginTop: ".5rem" }}>
          <input
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            aria-label="Password"
          />
        </p>
        {error && <p className="rate">{error}</p>}
        <p style={{ marginTop: "1rem" }}>
          <button className="primary" type="submit" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </p>
      </form>
    </main>
  );
}
