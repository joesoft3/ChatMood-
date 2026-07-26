"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Clock, Copy, CreditCard, Loader2, Smartphone, XCircle } from "lucide-react";
import AppShell from "@/components/AppShell";
import { StudioActionLink, StudioHero, StudioNotice, StudioStatusPill } from "@/components/StudioChrome";
import { apiFetch } from "@/lib/api";
import { copyText } from "@/lib/clipboard";

interface Offer {
  id: string;
  plan: string;
  label: string;
  months: number;
  amount: number;
  currency: string;
  price_label: string;
}

interface Method {
  id: string;
  kind: string;
  label: string;
  network: string;
  account_name: string;
  account_number: string;
  bank_name: string;
  instructions: string;
  currency: string;
}

interface Provider {
  id: string;
  label: string;
  configured: boolean;
  automatic: boolean;
  description: string;
}

interface PaymentRec {
  id: string;
  status: string;
  reference: string;
  amount_label: string;
  plan: string;
  months: number;
  admin_note: string;
  created_at: string | null;
}

interface Options {
  plan: string;
  currency: string;
  offers: Offer[];
  methods: Method[];
  providers: Provider[];
  manual_enabled: boolean;
  pending: PaymentRec | null;
  current_period_end: string | null;
}

const NETWORK_LABEL: Record<string, string> = {
  mtn: "MTN MoMo",
  vodafone: "Vodafone Cash",
  telecel: "Telecel Cash",
  airteltigo: "AirtelTigo Money",
};

export default function UpgradePage() {
  const [opts, setOpts] = useState<Options | null>(null);
  const [history, setHistory] = useState<PaymentRec[]>([]);
  const [offerId, setOfferId] = useState("");
  const [methodId, setMethodId] = useState("");
  const [reference, setReference] = useState("");
  const [payerName, setPayerName] = useState("");
  const [payerPhone, setPayerPhone] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [copied, setCopied] = useState("");

  const load = useCallback(async () => {
    try {
      const [o, mine] = await Promise.all([
        apiFetch<Options>("/payments/options"),
        apiFetch<{ payments: PaymentRec[] }>("/payments/mine"),
      ]);
      setOpts(o);
      setHistory(mine.payments);
      setOfferId((prev) => prev || o.offers[0]?.id || "");
      setMethodId((prev) => prev || o.methods[0]?.id || "");
      setErr("");
    } catch (e: any) {
      setErr(e.message ?? "Couldn't load payment options");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // A pending payment is resolved by a human, so poll gently while we wait.
  useEffect(() => {
    if (!opts?.pending) return;
    const id = window.setInterval(load, 20000);
    return () => window.clearInterval(id);
  }, [opts?.pending, load]);

  async function submit() {
    if (!reference.trim()) {
      setErr("Enter the transaction ID from your mobile money confirmation SMS.");
      return;
    }
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      await apiFetch("/payments/submit", {
        method: "POST",
        body: JSON.stringify({
          offer_id: offerId,
          method_id: methodId || null,
          reference: reference.trim(),
          payer_name: payerName.trim(),
          payer_phone: payerPhone.trim(),
          note: note.trim(),
        }),
      });
      setReference("");
      setNote("");
      setMsg("✅ Payment submitted — we'll confirm it shortly and your plan activates automatically.");
      await load();
    } catch (e: any) {
      setErr(e.message ?? "Couldn't submit the payment");
    } finally {
      setBusy(false);
    }
  }

  async function copy(text: string, what: string) {
    await copyText(text);
    setCopied(what);
    window.setTimeout(() => setCopied(""), 1800);
  }

  const offer = opts?.offers.find((o) => o.id === offerId);
  const method = opts?.methods.find((m) => m.id === methodId);
  const isPro = opts?.plan === "pro";
  const autoGateway = opts?.providers.find((p) => p.automatic && p.configured);

  return (
    <AppShell title="Upgrade">
      <div className="mx-auto max-w-3xl space-y-4 p-3 sm:p-4">
        <StudioHero
          icon={<CreditCard size={20} />}
          title="Upgrade to Pro"
          subtitle="Pay with mobile money — send to the number below, then paste your transaction ID. We confirm it and your plan activates."
          stats={[
            { label: "Current plan", value: (opts?.plan ?? "…").toUpperCase() },
            { label: "Monthly", value: opts?.offers[0]?.price_label ?? "—" },
            { label: "Yearly", value: opts?.offers[1]?.price_label ?? "—" },
            {
              label: "Renews",
              value: opts?.current_period_end ? opts.current_period_end.slice(0, 10) : "—",
            },
          ]}
        />

        {msg && <StudioNotice tone="success">{msg}</StudioNotice>}
        {err && <StudioNotice tone="warn">{err}</StudioNotice>}

        {isPro && (
          <StudioNotice tone="success">
            🎉 You&apos;re on Pro
            {opts?.current_period_end ? ` until ${opts.current_period_end.slice(0, 10)}` : ""}. Paying
            again extends your period — nothing is lost.
          </StudioNotice>
        )}

        {opts?.pending && (
          <section className="rounded-2xl border border-yellow-500/30 bg-yellow-500/10 p-4">
            <div className="flex items-center gap-2 text-sm text-yellow-300">
              <Clock size={15} /> Payment awaiting confirmation
            </div>
            <p className="mt-1.5 text-xs text-gray-300">
              We received your reference <code className="text-gray-100">{opts.pending.reference}</code>{" "}
              for {opts.pending.amount_label}. An admin verifies it against the mobile money account —
              this page updates automatically.
            </p>
          </section>
        )}

        {opts === null ? (
          <div className="pt-16 text-center text-gray-600">
            <Loader2 className="mx-auto animate-spin" />
          </div>
        ) : (
          !opts.pending && (
            <>
              {/* 1 — choose a plan */}
              <section className="space-y-3 rounded-2xl border border-line bg-panel p-4">
                <h2 className="text-sm font-semibold text-gray-100">1 · Choose your plan</h2>
                <div className="grid gap-2 sm:grid-cols-2">
                  {opts.offers.map((o) => (
                    <button
                      key={o.id}
                      onClick={() => setOfferId(o.id)}
                      className={`rounded-xl border p-3 text-left transition ${
                        offerId === o.id
                          ? "border-accent/50 bg-accent/10"
                          : "border-line bg-base hover:border-accent/30"
                      }`}
                    >
                      <p className="text-sm font-medium text-gray-100">{o.label}</p>
                      <p className="mt-0.5 text-lg font-bold text-accent">{o.price_label}</p>
                      <p className="text-[11px] text-gray-500">
                        {o.months} month{o.months === 1 ? "" : "s"}
                        {o.months === 12 ? " · 2 months free" : ""}
                      </p>
                    </button>
                  ))}
                </div>
              </section>

              {/* 2 — pay */}
              <section className="space-y-3 rounded-2xl border border-line bg-panel p-4">
                <h2 className="text-sm font-semibold text-gray-100">2 · Send the money</h2>
                {opts.methods.length === 0 ? (
                  <StudioNotice tone="warn">
                    No payment methods are published yet. Please contact the admin — they need to add a
                    mobile money number in the owner panel.
                  </StudioNotice>
                ) : (
                  <>
                    {opts.methods.length > 1 && (
                      <div className="flex flex-wrap gap-1.5">
                        {opts.methods.map((m) => (
                          <button
                            key={m.id}
                            onClick={() => setMethodId(m.id)}
                            className={`rounded-full border px-3 py-1.5 text-[11px] transition ${
                              methodId === m.id
                                ? "border-accent/40 bg-accent/15 text-accent"
                                : "border-line bg-white/5 text-gray-400 hover:text-gray-200"
                            }`}
                          >
                            {m.label}
                          </button>
                        ))}
                      </div>
                    )}
                    {method && (
                      <div className="space-y-2 rounded-xl border border-line bg-base p-3">
                        <div className="flex items-center gap-2 text-xs text-gray-400">
                          <Smartphone size={14} className="text-accent" />
                          {NETWORK_LABEL[method.network] || method.label}
                          {method.bank_name && ` · ${method.bank_name}`}
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          <code className="flex-1 min-w-[160px] rounded-lg bg-panel px-3 py-2 text-base font-semibold tracking-wide text-gray-100">
                            {method.account_number}
                          </code>
                          <button
                            onClick={() => copy(method.account_number, "number")}
                            className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-2 text-[11px] text-gray-300 hover:border-accent/40"
                          >
                            <Copy size={12} /> {copied === "number" ? "Copied" : "Copy"}
                          </button>
                        </div>
                        {method.account_name && (
                          <p className="text-[11px] text-gray-500">
                            Account name: <span className="text-gray-300">{method.account_name}</span>
                          </p>
                        )}
                        <p className="text-[11px] text-gray-400">
                          Amount to send:{" "}
                          <span className="font-semibold text-accent">{offer?.price_label}</span>
                        </p>
                        {method.instructions && (
                          <p className="whitespace-pre-wrap text-[11px] leading-relaxed text-gray-500">
                            {method.instructions}
                          </p>
                        )}
                      </div>
                    )}
                  </>
                )}
              </section>

              {/* 3 — confirm */}
              <section className="space-y-3 rounded-2xl border border-line bg-panel p-4">
                <h2 className="text-sm font-semibold text-gray-100">3 · Confirm your payment</h2>
                <p className="text-[11px] text-gray-500">
                  After sending, you get a confirmation SMS with a transaction ID. Paste it here so we can
                  match your payment.
                </p>
                <input
                  value={reference}
                  onChange={(e) => setReference(e.target.value)}
                  placeholder="Transaction ID — e.g. MP240726.1423.A12345"
                  maxLength={64}
                  className="w-full rounded-xl border border-line bg-base px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent/50"
                />
                <div className="grid gap-2 sm:grid-cols-2">
                  <input
                    value={payerName}
                    onChange={(e) => setPayerName(e.target.value)}
                    placeholder="Name on the sending account (optional)"
                    maxLength={120}
                    className="rounded-xl border border-line bg-base px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent/50"
                  />
                  <input
                    value={payerPhone}
                    onChange={(e) => setPayerPhone(e.target.value)}
                    placeholder="Phone you paid from (optional)"
                    maxLength={40}
                    className="rounded-xl border border-line bg-base px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent/50"
                  />
                </div>
                <textarea
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  rows={2}
                  maxLength={600}
                  placeholder="Anything we should know? (optional)"
                  className="w-full resize-y rounded-xl border border-line bg-base px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent/50"
                />
                <button
                  onClick={submit}
                  disabled={busy || !opts.manual_enabled || opts.offers.length === 0}
                  className="inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-black transition hover:brightness-110 disabled:opacity-50"
                >
                  {busy ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
                  I&apos;ve paid — submit for confirmation
                </button>
              </section>
            </>
          )
        )}

        {history.length > 0 && (
          <section className="space-y-2 rounded-2xl border border-line bg-panel p-4">
            <h2 className="text-sm font-semibold text-gray-100">Payment history</h2>
            {history.map((p) => (
              <div
                key={p.id}
                className="flex flex-wrap items-center gap-2 rounded-xl border border-line bg-base px-3 py-2 text-xs"
              >
                {p.status === "approved" ? (
                  <CheckCircle2 size={13} className="text-emerald-400" />
                ) : p.status === "rejected" ? (
                  <XCircle size={13} className="text-red-400" />
                ) : (
                  <Clock size={13} className="text-yellow-400" />
                )}
                <span className="text-gray-200">{p.amount_label}</span>
                <span className="text-gray-500">
                  {p.plan} · {p.months}mo
                </span>
                <code className="text-[10px] text-gray-600">{p.reference}</code>
                <span className="ml-auto text-[10px] text-gray-600">
                  {p.created_at?.slice(0, 10)}
                </span>
                {p.admin_note && (
                  <p className="w-full text-[10px] text-gray-500">Note: {p.admin_note}</p>
                )}
              </div>
            ))}
          </section>
        )}

        <div className="flex flex-wrap gap-2">
          {autoGateway ? (
            <StudioStatusPill label="Instant card payments" value={autoGateway.label} tone="success" />
          ) : (
            <StudioStatusPill label="Card payments" value="coming soon" />
          )}
          <StudioActionLink href="/settings">Back to settings</StudioActionLink>
        </div>
      </div>
    </AppShell>
  );
}
