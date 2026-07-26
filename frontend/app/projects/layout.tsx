import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Projects",
  description: "Durable containers for related chats, files and standing instructions.",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
