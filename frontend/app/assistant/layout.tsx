import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Mood AI Assistant",
  description: "A focused Mood AI Assistant chat.",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
