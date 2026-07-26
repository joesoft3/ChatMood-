import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Upgrade",
  description: "Upgrade to Pro with mobile money or card.",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
