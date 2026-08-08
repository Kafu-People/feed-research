"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

function LoginForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const router = useRouter();
  const next = useSearchParams().get("next") ?? "/";

  return (
    <main>
      <h1>{mode === "login" ? "Sign in" : "Create account"}</h1>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          void fetch("/api/session", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password, mode }),
          })
            .then((res) => {
              if (res.status === 409) throw new Error("That email is already registered.");
              if (!res.ok) throw new Error("Wrong email or password.");
              router.push(next);
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
            minLength={12}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={mode === "signup" ? "Password (12+ characters)" : "Password"}
            aria-label="Password"
          />
        </p>
        {error && <p className="rate">{error}</p>}
        <p style={{ marginTop: "1rem" }}>
          <button className="primary" type="submit" disabled={busy}>
            {busy ? "…" : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </p>
      </form>
      <p className="rate">
        {mode === "login" ? "New here? " : "Already have an account? "}
        <button
          className="chip"
          onClick={() => {
            setMode(mode === "login" ? "signup" : "login");
            setError(null);
          }}
        >
          {mode === "login" ? "Create an account" : "Sign in instead"}
        </button>
      </p>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
