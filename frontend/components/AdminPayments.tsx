"use client";

import { useCallback, useEffect, useState } from "react";
import {
  BadgeCheck,
  Banknote,
  CheckCircle2,
  Gift,
  Loader2,
  Plus,
  RefreshCw,
  Smartphone,
  Trash2,
  XCircle,
} from "lucide-react";
import { apiFetch } from "@/lib/api";

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
  active: boolean;
  sort_order: number;
}

interface Provider {
  id: string;
  label: string;
  configured: boolean;
  automatic: boolean;
  description: string;
}

interface Payment {
  id: string;
  user_id: string;
  user_email: string;
  provider: string;
  reference: string;
  amount_label: string;
  plan: string;
  months: number;
  status: string;
  note: string;
  admin_note: string;
  payer_name: string;
  payer_phone: string;
  created_at: string | null;
}

interface Summary {
  pending: number;
  approved: number;
  rejected: number;
  collected_label: string;
  currency: string;
  providers: Provider[];
}

const NETWORKS = ["mtn", "vodafone", "telecel", "airteltigo"];
const KINDS = ["momo", "bank", "cash", "other"];

/** 💳 Owner payments console — publish MoMo destinations, verify money manually. */
export default function AdminPayments() {
  const [methods, setMethods] = useState<Method[] | null>(null);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [filter, setFilter] = useState("pending");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [showForm, setShowForm] = useState(false);

  // new method form
  const [kind, setKind] = useState("momo");
  const [label, setLabel] = useState("");
  const [network, setNetwork] = useState("mtn");
  const [accName, setAccName] = useState("");
  const [accNumber, setAccNumber] = useState("");
  const [bankName, setBankName] = useState("");
  const [instructions, setInstructions] = useState("");

  const load = useCallback(async () => {
    try {
      const [m, p, s] = await Promise.all([
        apiFetch<{ methods: Method[] }>("/admin/payments/methods"),
        apiFetch<{ payments: Payment[] }>(`/admin/payments?status=${filter}`),
        apiFetch<Summary>("/admin/payments/summary"),
      ]);
      setMethods(m.methods);
      setPayments(p.payments);
      setSummary(s);
      setErr("");
    } catch (e: any) {
      setErr(e.message ?? "Couldn't load payments");
    }
  }, [filter]);

  useEffect(() => {
    load();
  }, [load]);

  async function addMethod() {
    if (label.trim().length < 2) return setErr("Give the method a label.");
    if (kind === "momo" && !accNumber.trim()) return setErr("A MoMo method needs a number.");
    setBusy("new");
    setErr("");
    try {
      await apiFetch("/admin/payments/methods", {
        method: "POST",
        body: JSON.stringify({
          kind,
          label: label.trim(),
          network: kind === "momo" ? network : "",
          account_name: accName.trim(),
          account_number: accNumber.trim(),
          bank_name: bankName.trim(),
          instructions: instructions.trim(),
        }),
      });
      setLabel("");
      setAccNumber("");
      setAccName("");
      setBankName("");
      setInstructions("");
      setShowForm(false);
      setMsg("✅ Payment method published — users can now pay to it.");
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(null);
    }
  }

  async function toggleMethod(m: Method) {
    setBusy(m.id);
    try {
      await apiFetch(`/admin/payments/methods/${m.id}`, {
        method: "PATCH",
        body: JSON.stringify({ active: !m.active }),
      });
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(null);
    }
  }

  async function removeMethod(m: Method) {
    if (!window.confirm(`Delete “${m.label}”?`)) return;
    setBusy(m.id);
    setErr("");
    try {
      await apiFetch(`/admin/payments/methods/${m.id}`, { method: "DELETE" });
      await load();
    } catch (e: any) {
      setErr(e.message); // 409 when payments reference it — retire instead
    } finally {
      setBusy(null);
    }
  }

  async function review(p: Payment, action: "approve" | "reject") {
    const note =
      action === "reject"
        ? window.prompt("Reason (shown to the user):", "We couldn't match that transaction.") ?? ""
        : window.prompt("Note (optional — e.g. 'seen in MoMo statement'):", "") ?? "";
    if (action === "reject" && !note.trim()) return;
    setBusy(p.id);
    setErr("");
    try {
      await apiFetch(`/admin/payments/${p.id}/${action}`, {
        method: "POST",
        body: JSON.stringify({ admin_note: note.trim() }),
      });
      setMsg(
        action === "approve"
          ? `✅ ${p.user_email} upgraded to ${p.plan} for ${p.months} month(s).`
          : `Payment from ${p.user_email} rejected.`,
      );
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(null);
    }
  }

  const gateways = summary?.providers.filter((p) => p.automatic) ?? [];

  return (
    <section className="space-y-4 rounded-2xl border border-line bg-panel p-5">
      <header className="flex flex-wrap items-center gap-2 text-sm font-semibold">
        <span className="text-accent">
          <Banknote size={16} />
        </span>
        💳 Payments — manual review
        <button
          onClick={load}
          className="ml-auto rounded-lg border border-line px-2 py-1 text-[10px] text-gray-400 hover:text-gray-100"
        >
          <RefreshCw size={12} className="inline" /> Refresh
        </button>
      </header>

      {msg && <p className="rounded-xl border border-emerald-400/30 bg-emerald-400/10 px-3 py-2 text-xs text-emerald-300">{msg}</p>}
      {err && <p className="rounded-xl border border-yellow-500/30 bg-yellow-500/10 px-3 py-2 text-xs text-yellow-300">{err}</p>}

      {summary && (
        <div className="grid grid-cols-2 gap-2 text-center sm:grid-cols-4">
          {[
            { label: "Awaiting review", value: summary.pending },
            { label: "Approved", value: summary.approved },
            { label: "Rejected", value: summary.rejected },
            { label: "Collected", value: summary.collected_label },
          ].map((s) => (
            <div key={s.label} className="rounded-xl border border-line bg-base px-3 py-3">
              <p className="text-lg font-semibold text-gray-100">{s.value}</p>
              <p className="text-[10px] text-gray-500">{s.label}</p>
            </div>
          ))}
        </div>
      )}

      {/* gateway readiness — honest about what still needs keys */}
      <div className="flex flex-wrap gap-1.5 text-[10px]">
        {gateways.map((g) => (
          <span
            key={g.id}
            title={g.description}
            className={`rounded-full border px-2.5 py-1 ${
              g.configured
                ? "border-green-400/30 bg-green-400/10 text-green-400"
                : "border-line text-gray-500"
            }`}
          >
            {g.configured ? "✓" : "○"} {g.label} {g.configured ? "live" : "needs key"}
          </span>
        ))}
      </div>

      {/* ── published destinations ─────────────────────────────── */}
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <h3 className="text-xs font-medium text-gray-300">Where users send money</h3>
          <button
            onClick={() => setShowForm((v) => !v)}
            className="ml-auto rounded-lg border border-accent/30 bg-accent/10 px-2.5 py-1 text-[10px] text-accent"
          >
            <Plus size={11} className="inline" /> {showForm ? "Close" : "Add method"}
          </button>
        </div>

        {showForm && (
          <div className="space-y-2 rounded-xl border border-line bg-base p-3">
            <div className="flex flex-wrap gap-1.5">
              {KINDS.map((k) => (
                <button
                  key={k}
                  onClick={() => setKind(k)}
                  className={`rounded-full border px-2.5 py-1 text-[10px] capitalize ${
                    kind === k ? "border-accent/40 bg-accent/15 text-accent" : "border-line text-gray-400"
                  }`}
                >
                  {k}
                </button>
              ))}
            </div>
            {kind === "momo" && (
              <div className="flex flex-wrap gap-1.5">
                {NETWORKS.map((n) => (
                  <button
                    key={n}
                    onClick={() => setNetwork(n)}
                    className={`rounded-full border px-2.5 py-1 text-[10px] uppercase ${
                      network === n ? "border-accent/40 bg-accent/15 text-accent" : "border-line text-gray-500"
                    }`}
                  >
                    {n}
                  </button>
                ))}
              </div>
            )}
            <div className="grid gap-2 sm:grid-cols-2">
              <input
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="Label — e.g. MTN MoMo (main)"
                className="rounded-lg border border-line bg-panel px-2.5 py-1.5 text-xs text-gray-100 outline-none focus:border-accent/50"
              />
              <input
                value={accNumber}
                onChange={(e) => setAccNumber(e.target.value)}
                placeholder={kind === "momo" ? "MoMo number — 024 123 4567" : "Account number"}
                className="rounded-lg border border-line bg-panel px-2.5 py-1.5 text-xs text-gray-100 outline-none focus:border-accent/50"
              />
              <input
                value={accName}
                onChange={(e) => setAccName(e.target.value)}
                placeholder="Account name"
                className="rounded-lg border border-line bg-panel px-2.5 py-1.5 text-xs text-gray-100 outline-none focus:border-accent/50"
              />
              {kind === "bank" && (
                <input
                  value={bankName}
                  onChange={(e) => setBankName(e.target.value)}
                  placeholder="Bank name"
                  className="rounded-lg border border-line bg-panel px-2.5 py-1.5 text-xs text-gray-100 outline-none focus:border-accent/50"
                />
              )}
            </div>
            <textarea
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              rows={2}
              placeholder="Instructions shown to payers — e.g. Dial *170#, choose Send Money…"
              className="w-full resize-y rounded-lg border border-line bg-panel px-2.5 py-1.5 text-xs text-gray-100 outline-none focus:border-accent/50"
            />
            <button
              onClick={addMethod}
              disabled={busy === "new"}
              className="rounded-lg border border-accent/30 bg-accent/15 px-3 py-1.5 text-[11px] text-accent disabled:opacity-50"
            >
              {busy === "new" ? <Loader2 size={11} className="inline animate-spin" /> : null} Publish
            </button>
          </div>
        )}

        {methods === null ? (
          <Loader2 className="mx-auto animate-spin text-gray-600" />
        ) : methods.length === 0 ? (
          <p className="rounded-xl border border-yellow-500/30 bg-yellow-500/10 px-3 py-2 text-[11px] text-yellow-300">
            No payment methods yet — users can&apos;t pay until you publish a mobile money number.
          </p>
        ) : (
          methods.map((m) => (
            <div
              key={m.id}
              className={`flex flex-wrap items-center gap-2 rounded-xl border border-line bg-base px-3 py-2 text-xs ${
                m.active ? "" : "opacity-50"
              }`}
            >
              <Smartphone size={13} className="text-accent" />
              <span className="font-medium text-gray-200">{m.label}</span>
              <code className="text-[11px] text-gray-400">{m.account_number}</code>
              {m.network && <span className="text-[10px] uppercase text-gray-600">{m.network}</span>}
              {!m.active && <span className="text-[10px] text-gray-500">retired</span>}
              <div className="ml-auto flex gap-1.5">
                <button
                  onClick={() => toggleMethod(m)}
                  disabled={busy === m.id}
                  className="rounded-lg border border-line px-2 py-1 text-[10px] text-gray-400 hover:text-gray-100"
                >
                  {m.active ? "Retire" : "Activate"}
                </button>
                <button
                  onClick={() => removeMethod(m)}
                  disabled={busy === m.id}
                  className="rounded-lg border border-line px-2 py-1 text-gray-500 hover:border-red-400/40 hover:text-red-300"
                >
                  <Trash2 size={11} />
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* ── review queue ───────────────────────────────────────── */}
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <h3 className="text-xs font-medium text-gray-300">Payments</h3>
          {["pending", "approved", "rejected", "all"].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`rounded-full border px-2.5 py-1 text-[10px] capitalize ${
                filter === f ? "border-accent/40 bg-accent/15 text-accent" : "border-line text-gray-500"
              }`}
            >
              {f}
            </button>
          ))}
        </div>

        {payments.length === 0 ? (
          <p className="text-[11px] text-gray-600">Nothing {filter === "all" ? "yet" : `${filter}`}.</p>
        ) : (
          payments.map((p) => (
            <div key={p.id} className="space-y-1.5 rounded-xl border border-line bg-base p-3 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                {p.status === "approved" ? (
                  <CheckCircle2 size={13} className="text-emerald-400" />
                ) : p.status === "rejected" ? (
                  <XCircle size={13} className="text-red-400" />
                ) : (
                  <BadgeCheck size={13} className="text-yellow-400" />
                )}
                <span className="font-medium text-gray-200">{p.user_email}</span>
                <span className="font-semibold text-accent">{p.amount_label}</span>
                <span className="text-[10px] text-gray-500">
                  {p.plan} · {p.months}mo
                </span>
                <span className="ml-auto text-[10px] text-gray-600">{p.created_at?.slice(0, 10)}</span>
              </div>
              <div className="flex flex-wrap gap-x-3 text-[10px] text-gray-500">
                <span>
                  ref <code className="text-gray-300">{p.reference}</code>
                </span>
                {p.payer_name && <span>from {p.payer_name}</span>}
                {p.payer_phone && <span>{p.payer_phone}</span>}
              </div>
              {p.note && <p className="text-[10px] text-gray-500">“{p.note}”</p>}
              {p.admin_note && <p className="text-[10px] text-gray-600">Admin: {p.admin_note}</p>}
              {p.status === "pending" && (
                <div className="flex gap-1.5 pt-1">
                  <button
                    onClick={() => review(p, "approve")}
                    disabled={busy === p.id}
                    className="rounded-lg border border-emerald-400/30 bg-emerald-400/10 px-3 py-1.5 text-[11px] text-emerald-300 disabled:opacity-50"
                  >
                    {busy === p.id ? <Loader2 size={11} className="inline animate-spin" /> : null} Approve &
                    activate
                  </button>
                  <button
                    onClick={() => review(p, "reject")}
                    disabled={busy === p.id}
                    className="rounded-lg border border-line px-3 py-1.5 text-[11px] text-gray-400 hover:border-red-400/40 hover:text-red-300 disabled:opacity-50"
                  >
                    Reject
                  </button>
                </div>
              )}
            </div>
          ))
        )}
      </div>

      <p className="flex items-center gap-1.5 text-[10px] text-gray-600">
        <Gift size={11} /> Approving activates the plan immediately and extends any period the user
        already has. Approving twice is safe — it never grants a double month.
      </p>
    </section>
  );
}
