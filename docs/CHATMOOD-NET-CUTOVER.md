# chatmood.net cutover

The production web-domain target is **https://chatmood.net**.

> **Current status (2026-08-20):** `chatmood.net` has no DNS records and its
> registry lookup reports that it is not registered. Keep production on
> **https://moodai-app.vercel.app** until the domain is registered and Vercel
> reports valid DNS and HTTPS. The repository intentionally keeps the current
> Vercel address as its default until then.

## 1. Register the domain

Buy `chatmood.net` from Vercel Domains or a registrar you control. Enable
WHOIS privacy and auto-renew. Do not enter registrar credentials or payment
information in the repository.

## 2. Attach it to the Vercel web project

1. Open the Vercel project currently serving `moodai-app.vercel.app`.
2. Go to **Settings → Domains → Add Domain**.
3. Add `chatmood.net` as the production domain.
4. Optionally add `www.chatmood.net` and redirect it to `chatmood.net`.
5. Copy the exact DNS records Vercel displays into the registrar's DNS panel.
   Do not guess the records; Vercel may show different targets for apex and
   subdomain traffic.
6. Wait until Vercel reports **Valid Configuration** and has issued HTTPS.

## 3. Update build and backend runtime variables

Set this on the Vercel **web** project for Production, then redeploy:

```dotenv
NEXT_PUBLIC_SITE_URL=https://chatmood.net
```

Keep the existing `NEXT_PUBLIC_API_URL` value; the API host is not changing in
this cutover.

On the active backend (currently Fly.io), use a transition CORS list so both the
old and new frontends work while DNS propagates:

```bash
fly secrets set -a moodai-api \
  CORS_ORIGINS="https://moodai-app.vercel.app,https://chatmood.net,https://www.chatmood.net" \
  FRONTEND_URL="https://chatmood.net"
```

Apply the same `CORS_ORIGINS` and `FRONTEND_URL` values to any warm secondary
backend, including the Vercel API project. `FRONTEND_URL` controls invite,
billing, plugin-return, and shared-media links; changing only CORS is not a
complete cutover.

## 4. Deploy and verify

After the domain, DNS, and runtime variables above are configured, redeploy the
web and API applications, then run:

```bash
python3 scripts/check_domain_cutover.py chatmood.net moodai-api.fly.dev
WEB_URL=https://chatmood.net scripts/live-smoke.sh https://moodai-api.fly.dev
```

Also verify:

- `https://chatmood.net` serves ChatMood with a valid certificate;
- sign-up and login work from the new origin;
- browser API requests have no CORS errors;
- `/robots.txt`, `/sitemap.xml`, Open Graph URLs, invite links, and payment
  returns use `https://chatmood.net`;
- the old `https://moodai-app.vercel.app` address still works during the
  transition.

## 5. Retire the old address

After the new domain passes smoke tests and DNS has had time to propagate,
configure the old Vercel domain to redirect permanently to `https://chatmood.net`.
Only then remove the old origin from `CORS_ORIGINS`.
