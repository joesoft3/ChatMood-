import type { Metadata, Viewport } from "next";
import "./globals.css";
import { ConversationsProvider } from "@/lib/conversations";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "https://moodai-app.vercel.app"),
  title: {
    default: "Mood AI — chat, research, voice & AI films in one workspace",
    template: "%s · Mood AI",
  },
  description:
    "A refreshed AI workspace: streaming chat, blind multi-model Arena, deep research with citations, " +
    "voice conversations, images and a video studio with AI voiceovers and cinematic sound.",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/icon.png", apple: "/icon.png" },
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: "Mood AI" },
  openGraph: {
    siteName: "Mood AI",
    type: "website",
    title: "Mood AI — chat, research, voice & AI films in one workspace",
    description:
      "A refreshed AI workspace where models debate blind in Arena, research with citations, and direct storyboard films with studio voiceovers — your chats, your terms.",
    images: [{ url: "/og.png", width: 1024, height: 500, alt: "Mood AI" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Mood AI",
    description: "A refreshed AI workspace — arena debates, deep research, voice, images and AI films with sound.",
    images: ["/og.png"],
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover", // edge-to-edge on notched phones
  themeColor: "#0b0f14",
  // Resize the app when the on-screen keyboard opens (Chrome/Android),
  // so the composer and tab bar stay visible while typing.
  interactiveWidget: "resizes-content",
};

const themeInit = `try {
  var t = localStorage.getItem("mood_theme");
  document.documentElement.dataset.theme = t || "dark";
} catch (e) { document.documentElement.dataset.theme = "dark"; }`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* 🌓 apply stored/system theme before first paint — no flash */}
        <script dangerouslySetInnerHTML={{ __html: themeInit }} />
      </head>
      <body className="bg-base text-gray-100 antialiased">
        <ConversationsProvider>{children}</ConversationsProvider>
      </body>
    </html>
  );
}
