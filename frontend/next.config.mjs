/**
 * The web app talks to the FastAPI backend at `/api/v1`.
 *
 * When `NEXT_PUBLIC_API_URL` is set (Netlify/Vercel/Fly production wiring), the
 * browser calls that absolute URL directly and these rewrites are inert.
 *
 * When it is NOT set, `lib/apiBase.ts` falls back to the same-origin path
 * `/api/v1`, and Next proxies those requests to `BACKEND_ORIGIN`
 * (default http://localhost:8000). That keeps the app working out of the box on
 * localhost, on sandbox/preview URLs and behind any reverse proxy — the browser
 * only ever needs to reach the host it was served from, so it never tries (and
 * fails) to open a connection to the visitor's own machine.
 */
const BACKEND_ORIGIN = (process.env.BACKEND_ORIGIN ?? "http://localhost:8000").replace(/\/+$/, "");
const PROXY_API = !process.env.NEXT_PUBLIC_API_URL;

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // `next dev` behind a hosted preview/tunnel (sandbox URLs, ngrok, Codespaces)
  // is served on a different host than localhost; without this Next.js refuses
  // the cross-origin /_next/* requests and the page loads without its JS.
  allowedDevOrigins: [
    "*.e2b.app",
    "*.e2b.dev",
    "*.arena.ai",
    "*.app.github.dev",
    "*.ngrok-free.app",
    "*.trycloudflare.com",
    "*.loca.lt",
  ],
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          // Arena (and other hosted previews) load the app inside an iframe.
          { key: "Content-Security-Policy", value: "frame-ancestors *" },
        ],
      },
    ];
  },
  async rewrites() {
    if (!PROXY_API) return [];
    return [{ source: "/api/v1/:path*", destination: `${BACKEND_ORIGIN}/api/v1/:path*` }];
  },
};

export default nextConfig;
