"use client";

import { useEffect } from "react";

/**
 * Keyboard navigation: the affordance mobile can't have. Public-board mode:
 * no feedback capture, so this component is shortcuts only.
 */
export function DashboardClient({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    let index = 0;
    const cards = () => Array.from(document.querySelectorAll<HTMLElement>("li.card"));

    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.metaKey || e.ctrlKey) return;
      const list = cards();
      if (list.length === 0) return;

      switch (e.key) {
        case "j":
          index = Math.min(index + 1, list.length - 1);
          list[index]?.scrollIntoView({ block: "center", behavior: "smooth" });
          break;
        case "k":
          index = Math.max(index - 1, 0);
          list[index]?.scrollIntoView({ block: "center", behavior: "smooth" });
          break;
        case "o":
        case "Enter":
          list[index]?.querySelector("a")?.click();
          break;
      }
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return <>{children}</>;
}
