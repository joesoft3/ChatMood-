import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  const base = (process.env.NEXT_PUBLIC_SITE_URL ?? "https://moodai-app.vercel.app").replace(/\/+$/, "");
  return {
    rules: [
      {
        userAgent: "*",
        allow: ["/", "/privacy", "/terms", "/account-deletion", "/f/"],
        disallow: [
          "/admin",
          "/chat",
          "/deepsearch",
          "/design",
          "/files",
          "/films",
          "/images",
          "/join/",
          "/login",
          "/signin",
          "/signup",
          "/order/",
          "/plugins",
          "/settings",
          "/shared/",
          "/voice",
        ],
      },
    ],
    sitemap: `${base}/sitemap.xml`,
    host: base,
  };
}
