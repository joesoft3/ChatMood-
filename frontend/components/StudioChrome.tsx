import Link from "next/link";

type StudioTone = "default" | "accent" | "warn" | "success";

function toneCls(tone: StudioTone) {
  if (tone === "accent") return "border-accent/30 bg-accent/10 text-accent";
  if (tone === "warn") return "border-yellow-500/30 bg-yellow-500/10 text-yellow-300";
  if (tone === "success") return "border-emerald-400/30 bg-emerald-400/10 text-emerald-300";
  return "border-line bg-white/5 text-gray-400";
}

export function StudioActionLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className="rounded-xl border border-line bg-white/5 px-3 py-2 text-xs text-gray-300 hover:border-accent/40 hover:bg-white/10 transition"
    >
      {children}
    </Link>
  );
}

export function StudioActionButton({ onClick, children, tone = "default" }: {
  onClick: () => void;
  children: React.ReactNode;
  tone?: StudioTone;
}) {
  const cls =
    tone === "accent"
      ? "border-accent/30 bg-accent/10 text-accent hover:bg-accent/20"
      : tone === "warn"
        ? "border-red-400/30 bg-red-400/10 text-red-300 hover:bg-red-400/20"
        : "border-line bg-white/5 text-gray-300 hover:border-accent/40 hover:bg-white/10";
  return (
    <button onClick={onClick} className={`rounded-xl border px-3 py-2 text-xs transition ${cls}`}>
      {children}
    </button>
  );
}

export function StudioHero({
  icon,
  title,
  subtitle,
  actions,
  stats,
}: {
  icon?: React.ReactNode;
  title: string;
  subtitle: string;
  actions?: React.ReactNode;
  stats?: { label: string; value: React.ReactNode }[];
}) {
  return (
    <section className="rounded-2xl border border-line bg-panel p-4 sm:p-5 space-y-4">
      <div className="flex items-start gap-3 flex-wrap">
        {icon && <div className="grid h-11 w-11 place-items-center rounded-xl bg-accent/15 text-accent shrink-0">{icon}</div>}
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-bold text-gray-100">{title}</h1>
          <p className="text-xs text-gray-400 mt-1">{subtitle}</p>
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
      {stats && stats.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
          {stats.map((item) => (
            <div key={item.label} className="rounded-xl bg-base border border-line px-3 py-3">
              <p className="text-lg font-semibold text-gray-100">{item.value}</p>
              <p className="text-[10px] text-gray-500">{item.label}</p>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export function StudioNotice({
  children,
  tone = "default",
}: {
  children: React.ReactNode;
  tone?: StudioTone;
}) {
  return <div className={`rounded-xl border px-3 py-2 text-xs ${toneCls(tone)}`}>{children}</div>;
}

export function StudioStatusPill({
  label,
  value,
  tone = "default",
  pulse = false,
}: {
  label: string;
  value: React.ReactNode;
  tone?: StudioTone;
  pulse?: boolean;
}) {
  return (
    <div className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-[11px] ${toneCls(tone)}`}>
      {pulse && <span className="inline-block h-2 w-2 rounded-full bg-current animate-pulse" />}
      <span className="opacity-80">{label}</span>
      <span className="font-medium text-current">{value}</span>
    </div>
  );
}

export function StudioEmptyState({
  emoji,
  title,
  description,
  actions,
}: {
  emoji: string;
  title: string;
  description: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 py-10 sm:py-14">
      <div className="flex flex-col items-center gap-3 text-center select-none">
        <span className="grid h-11 w-11 place-items-center rounded-full bg-composer text-xl">
          {emoji}
        </span>
        <h2 className="text-center text-[32px] font-semibold tracking-tight text-gray-100">
          {title}
        </h2>
        <p className="max-w-xl text-center text-sm leading-relaxed text-gray-400">{description}</p>
      </div>
      {actions && <div className="flex flex-wrap items-center justify-center gap-2">{actions}</div>}
    </div>
  );
}
