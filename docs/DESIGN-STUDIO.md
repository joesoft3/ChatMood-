# 🎨 Design Studio — flyers, stickers, banners & logos at print resolution

The studio turns a one-line idea into a print-ready PNG in ~30 seconds:

1. **Art-director pass** — the fast model rewrites your idea into a dense design
   brief (exact headline text, layout hierarchy, palette). Toggle it off to use
   your words verbatim. Put exact text in `'quotes'` so spelling survives.
2. **Render** — the configured image model paints the design. On `gpt-image-*`
   models the studio requests the native canvas (`1024×1536` flyer,
   `1536×1024` banner, `1024×1024` logo/sticker) at `quality=high`; cut-out
   kinds also request `background=transparent` **and** `output_format=png`
   (the default webp/jpeg would silently flatten the alpha), falling back to
   flat + auto-retry if the provider rejects it. Any other provider still
   works — the canvas is normalized server-side.
3. **Fit pass** — the render is normalized onto the exact kind canvas:
   - `cover` (flyer, banner) — scale up + center-crop for a full-bleed page.
   - `contain` (logo, sticker) — scale down + pad, because cropping a mark
     ruins it. Padding is transparent for cut-outs, white otherwise (never
     black, which would print as a slab).
4. **Print pass** — ffmpeg lanczos-upscales, applies a luma-only unsharp pass
   (lanczos enlargement is soft; chroma/alpha untouched so cut-out edges stay
   clean) and tags **300 DPI** metadata:

   | Kind | Web tier | Print master | Notes |
   |---|---|---|---|
   | Flyer | `1024×1536` | `2480×3720` | A4-class page |
   | Banner | `1536×1024` | `4608×3072` | large-format roll-up / web hero |
   | Logo | `1024×1024` | `4096×4096` | signage & embroidery grade, alpha kept |
   | Sticker | `1024×1024` | `3000×3000` | 10×10 cm die-cut at 300 DPI, alpha kept |

   Print dims keep the web aspect exactly (the upscale is a straight scale, so
   any drift would stretch the art). Paper-exact canvases come from the export
   presets below, which crop rather than warp. PNGs are written at max deflate
   (`-compression_level 100`, lossless) and flattened to `rgb24` unless the
   kind is a cut-out.

| Endpoint | Notes |
|---|---|
| `POST /api/v1/media/designs` | `{idea, kind, style, palette, transparent, enhance}` → design row |
| `GET /api/v1/media/designs` | gallery (newest 50) |
| `GET /api/v1/media/designs/presets` | kinds/styles/palettes the UI renders from |
| `GET /api/v1/media/designs/{id}/download?tier=web\|print` | owner-gated PNG with friendly filename |
| `DELETE /api/v1/media/designs/{id}` | removes row **and** both PNG tiers |

**Retention:** unlike 24h-TTL muxed videos, design files *persist* until you
delete them — a logo is a keepsake. They are never publicly served.

**Limits:** free 5/day · pro 60/day (`design_day` plan cap), 4/min burst.

## 🧑‍💼 Brand Kit (v0.9.0)
`PUT/GET /media/brand` stores one identity per user (name, tagline, 3 colors,
font vibe, brand logo = one of your logo designs). With `use_brand: true`,
generation weaves the identity into the art-director brief **and** ffmpeg
composites your saved logo bottom-right (16% canvas width, padded) onto the
web tier — the 300-DPI print tier is then upscaled *from the branded frame*,
so both tiers carry your logo. Cut-out kinds (logo/sticker) skip compositing —
they *are* the mark, and stamping a second logo into a die-cut would print it
into the sticker — but they still honor the colors/fonts.

## ✈️ Starter templates (v0.9.0)
`GET /media/designs/templates` — 10 Ghana-flavored briefs (chop bar, salon,
church program, waakye Friday, real estate, momo agent, thrift pop-up, gym,
DJ night, product sticker, provisions logo). Each presets kind+style+palette;
`[brackets]` mark the fields to personalize.

## 📱 Mobile (v0.9.0)
The Flutter app ships the full studio (`design_screen.dart`): kind tabs,
chips, brand toggle, grid gallery with Share (WhatsApp sheet) for both tiers
(share_plus), delete, autosynced previews.

## 🖨 Print-shop & social exports (v1.0.0)
`GET /media/designs/{id}/export?preset=…` → cached 300-DPI PNGs, generated on demand:
- `a4_bleed` (2480×3508 trim + 3mm bleed, white canvas + 8 crop marks, 300 DPI tag)
- `a5_bleed` (1748×2480 trim + marks) — matches the Ghana print shops' staples
- `a3_bleed` (3508×4961 trim + marks) — poster tier
- `wa_status` 1080×1920 · `ig_post` 1080×1350 · `ig_square` 1080×1080 (exact crops)
- 🏷 **Sticker sheets** — `sticker_a4` (3×4 = 12 up) and `sticker_a4_mini`
  (4×6 = 24 up): one copy is contain-fitted into each square cell and tiled on
  an A4 300-DPI page with ~8 mm margins and ~5 mm gutters, gaps left fully
  transparent so a cutting machine can kiss-cut each copy. Offered only for
  cut-out kinds (logo/sticker); asking for one on a flyer returns `422` with
  the presets that *do* apply.

Preset list: `GET /media/designs/exports` (each entry carries `sheet` and
`transparent` flags); per-design list: the `exports` field on a design row and
`GET /media/designs/presets`.

## ⭐ Brand app icon (v1.0.0)
`GET /media/brand/icon?size=192|512` renders a PWA-ready square tile from your Brand
Kit (primary-color canvas + brand initial in accent) — pure ffmpeg, no model call.

## 🤖 Design agent (v1.0.0)
The chat/plugin tool `design_create` is a **staged ✋ write action**: the model
drafts it, you approve it in the Plugin Store inbox, and only then does the
renderer run — the design lands in your Studio gallery with a how-to card.

## 🎞 Branded films (v1.0.0)
Storyboard films accept `use_brand: true`: identity colors/style are woven into
scene planning and your logo is stamped onto the hero-frame poster; the public
share card says "by *Your Brand* · Directed with ChatMood".

## 🛍 Client mode (v1.1.0)
`POST /media/design-orders` → magic link `/order/{token}`. Clients pick
kind+style, describe their design, submit — the order lands as a **✋ staged
`design_create`** action on your account. Approve in the Plugin Store inbox and
the order flips to **delivered**: the client downloads Web + Print-HD PNGs from
the very same link (`GET /media/public/orders/{token}/download`). Close links
with `POST /media/design-orders/{id}/close`.

## 📊 Studio analytics (v1.1.0)
Admin → Engagement gains a **🎨 Creative studio** widget: 30-day mix
(videos / i2v / designs / edits / exports / films), design-kind bars and a rough
est. spend (usage_events metering: `i2v`, `edit`, `design_export` kinds).
