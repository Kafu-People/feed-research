"use client";

import { useEffect, useRef } from "react";

import { SHOWN_THRESHOLD, type Dashboard, type ShownCard } from "@techtrend/core";

import { feedback } from "@/lib/queue";

/**
 * Owns feedback capture and keyboard shortcuts. The cards themselves are
 * server-rendered by the parent, so the first paint is HTML.
 */
export function DashboardClient({
  initial,
  children,
}: {
  initial: Dashboard;
  children: React.ReactNode;
}) {
  const shown = useRef<Map<number, ShownCard>>(new Map());
  // "Shown" = >=50% visible for >=1s. Same predicate mobile uses via
  // FlatList viewability -- imported, not reimplemented.
  useEffect(() => {
    const timers = new Map<number, ReturnType<typeof setTimeout>>();
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const el = entry.target as HTMLElement;
          const storyId = Number(el.dataset.storyId);
          const position = Number(el.dataset.position);
          if (entry.intersectionRatio >= SHOWN_THRESHOLD.ratio) {
            if (!timers.has(storyId)) {
              timers.set(
                storyId,
                setTimeout(() => {
                  shown.current.set(storyId, { storyId, position });
                }, SHOWN_THRESHOLD.ms),
              );
            }
          } else {
            const t = timers.get(storyId);
            if (t) {
              clearTimeout(t);
              timers.delete(storyId);
            }
          }
        }
      },
      { threshold: [SHOWN_THRESHOLD.ratio] },
    );

    document.querySelectorAll<HTMLElement>("li.card").forEach((el) => io.observe(el));
    return () => {
      io.disconnect();
      timers.forEach(clearTimeout);
    };
  }, [initial]);

  // Tab hidden -> flush now. The user may never come back to this tab.
  useEffect(() => {
    const onHide = () => {
      if (document.visibilityState === "hidden") {
        void feedback.dayComplete(Array.from(shown.current.values()));
      }
    };
    document.addEventListener("visibilitychange", onHide);
    return () => document.removeEventListener("visibilitychange", onHide);
  }, []);

  // Keyboard shortcuts: the affordance mobile can't have. Each emits the SAME
  // event through the SAME queue as its touch equivalent.
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
        case "x": {
          const el = list[index];
          if (el) {
            void feedback.track("hidden", { storyId: Number(el.dataset.storyId) }, index);
            el.style.opacity = "0.35";
          }
          break;
        }
      }
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return <>{children}</>;
}
