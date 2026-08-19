import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Sign up",
  description: "Create your ChatMood account.",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
