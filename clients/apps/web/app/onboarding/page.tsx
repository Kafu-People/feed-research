"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/** One text box. No list to pick from. */
export default function SentencePage() {
  const [sentence, setSentence] = useState("");
  const router = useRouter();

  return (
    <main>
      <h1>What do you want to follow?</h1>
      <p className="rate">Describe it in your own words.</p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          router.push(`/onboarding/confirm?s=${encodeURIComponent(sentence)}`);
        }}
      >
        <input
          type="text"
          autoFocus
          value={sentence}
          onChange={(e) => setSentence(e.target.value)}
          placeholder="AI chips and export restrictions, especially Nvidia and China"
          aria-label="What do you want to follow?"
        />
        <p style={{ marginTop: "1rem" }}>
          <button className="primary" type="submit" disabled={sentence.trim().length < 3}>
            Continue
          </button>
        </p>
      </form>
    </main>
  );
}
