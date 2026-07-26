"use client";

import Link from "next/link";
import { Check, Lock, Sparkles } from "lucide-react";

export interface Perk {
  id: string;
  label: string;
  detail: string;
  emoji: string;
  free: boolean;
  unlocked: boolean;
}

export interface ReelEntitlements {
  premium: boolean;
  plan: string;
  perks: Perk[];
  premium_effects: string[];
  max_mb: number;
  max_seconds: number;
  resolution: string;
  watermark: boolean;
  go_live: boolean;
  live_configured: boolean;
  live_provider: string;
  upgrade_path: string;
}

/**
 * ⭐ Creator Pro panel.
 *
 * Renders straight from the server's entitlement payload rather than a
 * hardcoded list, so a padlock here can never claim something the backend
 * doesn't actually enforce — the two can't drift apart.
 */
export default function ReelPremium({ ent }: { ent: ReelEntitlements }) {
  const locked = ent.perks.filter((p) => !p.unlocked);

  return (
    <div className="mx-auto max-w-lg space-y-4 p-4">
      <section
        className={`rounded-2xl border p-4 ${
          ent.premium ? "border-accent/40 bg-accent/10" : "border-line bg-panel"
        }`}
      >
        <div className="flex items-center gap-2">
          <Sparkles size={17} className="text-accent" />
          <h2 className="text-sm font-semibold text-gray-100">
            {ent.premium ? "Creator Pro — active" : "Creator Pro"}
          </h2>
          <span className="ml-auto rounded-full border border-line px-2 py-0.5 text-[10px] uppercase text-gray-400">
            {ent.plan}
          </span>
        </div>
        <p className="mt-1.5 text-xs text-gray-400">
          {ent.premium
            ? "Every creator tool is unlocked on your account."
            : "Post clean, longer, sharper reels — and broadcast live to the feed."}
        </p>

        <div className="mt-3 grid grid-cols-3 gap-2 text-center">
          {[
            ["Max clip", `${Math.round(ent.max_seconds / 60)} min`],
            ["Upload", `${ent.max_mb} MB`],
            ["Quality", ent.resolution.split("x")[0] + "p"],
          ].map(([label, value]) => (
            <div key={label} className="rounded-xl border border-line bg-base px-2 py-2.5">
              <p className="text-sm font-semibold text-gray-100">{value}</p>
              <p className="text-[10px] text-gray-500">{label}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="space-y-1.5">
        {ent.perks.map((p) => (
          <div
            key={p.id}
            className={`flex items-start gap-2.5 rounded-xl border px-3 py-2.5 ${
              p.unlocked ? "border-line bg-panel" : "border-line/60 bg-panel/50"
            }`}
          >
            <span className="mt-0.5 text-base">{p.emoji}</span>
            <div className="min-w-0 flex-1">
              <p
                className={`text-xs font-medium ${
                  p.unlocked ? "text-gray-100" : "text-gray-400"
                }`}
              >
                {p.label}
                {p.free && (
                  <span className="ml-1.5 rounded bg-white/10 px-1.5 py-0.5 text-[9px] text-gray-400">
                    free
                  </span>
                )}
              </p>
              <p className="mt-0.5 text-[11px] leading-relaxed text-gray-500">{p.detail}</p>
            </div>
            {p.unlocked ? (
              <Check size={14} className="mt-0.5 shrink-0 text-emerald-400" />
            ) : (
              <Lock size={13} className="mt-0.5 shrink-0 text-gray-600" />
            )}
          </div>
        ))}
      </section>

      {!ent.premium && (
        <Link
          href={ent.upgrade_path || "/upgrade"}
          className="block rounded-xl bg-accent px-4 py-3 text-center text-sm font-semibold text-black transition hover:brightness-110"
        >
          Unlock {locked.length} creator {locked.length === 1 ? "feature" : "features"} — Upgrade
        </Link>
      )}

      {ent.premium && !ent.live_configured && (
        <p className="rounded-xl border border-yellow-500/30 bg-yellow-500/10 px-3 py-2 text-[11px] text-yellow-300">
          🔴 Go Live is unlocked on your plan, but the platform owner hasn&apos;t connected a
          streaming provider yet.
        </p>
      )}

      <p className="text-center text-[10px] text-gray-600">
        Pay with MTN MoMo, Telecel or Vodafone Cash · cancel anytime
      </p>
    </div>
  );
}
