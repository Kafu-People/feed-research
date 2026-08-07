import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "TechTrend",
  description: "The things worth knowing, ranked, with no duplicates.",
  // The dashboard is one person's personal screen. There is no public archive
  // of stories, and building one is a licensing decision, not an eng one.
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
