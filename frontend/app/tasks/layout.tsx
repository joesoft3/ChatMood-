import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Tasks",
  description: "Scheduled prompts MoodAI runs for you, unattended.",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
