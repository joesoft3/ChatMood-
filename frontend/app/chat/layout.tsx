import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Chat",
  description: "Private signed-in chat workspace for MoodAI.",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
