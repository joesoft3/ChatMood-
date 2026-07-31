"use client";

import React from "react";

type Pill = {
  icon?: React.ReactNode;
  label: string;
  onClick: () => void;
  ariaLabel?: string;
};

interface EmptyEnvironmentProps {
  /** Emoji or icon shown in the brand bubble — defaults to ChatMood mark */
  bubble?: React.ReactNode;
  /** Main heading — like chat's "What can I help with?" */
  title: string;
  /** Optional subheading / description under the title */
  description?: string;
  /** Optional centered content — e.g. composer, form, search */
  children?: React.ReactNode;
  /** Optional pill actions — rendered like chat's starter pills */
  pills?: Pill[];
  /** Optional secondary actions — rendered as centered buttons below pills */
  actions?: React.ReactNode;
  /** Optional footer note */
  footer?: React.ReactNode;
  /** Optional className for outer wrapper */
  className?: string;
}

/**
 * ChatMood Empty Environment — the centered, branded empty state that the
 * chat home uses (brand mark + h1 + composer + model row + starter pills).
 *
 * All task-like surfaces (Tasks, Projects, Files, Films, etc.) now ride this
 * same environment so empty states feel consistent across the app.
 */
export default function EmptyEnvironment({
  bubble,
  title,
  description,
  children,
  pills,
  actions,
  footer,
  className,
}: EmptyEnvironmentProps) {
  return (
    <div className={`flex flex-1 flex-col items-center justify-center gap-6 py-6 sm:gap-7 sm:py-8 ${className ?? ""}`}>
      <div className="flex flex-col items-center gap-3 text-center select-none">
        <span className="grid h-11 w-11 place-items-center rounded-2xl bg-[#141415] border border-white/8 shadow-[0_0_55px_-16px_rgb(var(--mood-accent)/0.65)]">
          {bubble ?? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src="/icon.png" alt="" className="h-6 w-6 rounded-lg" />
          )}
        </span>
        <h1 className="text-center text-[clamp(1.85rem,4.6vw,2.6rem)] font-semibold tracking-tight text-white">
          {title}
        </h1>
        {description && (
          <p className="max-w-xl text-center text-sm leading-relaxed text-gray-400">{description}</p>
        )}
      </div>

      {children && <div className="w-full max-w-2xl">{children}</div>}

      {pills && pills.length > 0 && (
        <div className="w-full max-w-2xl px-2">
          <nav className="flex flex-wrap items-center justify-center gap-2" aria-label="Quick actions">
            {pills.map(({ icon, label, onClick, ariaLabel }) => (
              <button
                key={label}
                onClick={onClick}
                aria-label={ariaLabel ?? label}
                className="touch-manipulation inline-flex items-center gap-2 rounded-full border border-white/8 bg-[#141415] px-4 py-2.5 text-xs text-gray-300 transition hover:border-white/15 hover:bg-white/[0.045] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
              >
                {icon && <span className="text-accent" aria-hidden>{icon}</span>}
                {label}
              </button>
            ))}
          </nav>
        </div>
      )}

      {actions && (
        <div className="flex w-full max-w-2xl flex-wrap items-center justify-center gap-2 px-2">
          {actions}
        </div>
      )}

      {footer && <div className="w-full max-w-2xl text-center">{footer}</div>}
    </div>
  );
}

/**
 * Full-page wrapper that mirrors chat's scroll + background so any page
 * using EmptyEnvironment feels like the same world.
 */
export function EmptyEnvironmentPage({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin px-3 sm:px-4 py-5 sm:py-6 compact-v bg-[radial-gradient(circle_at_top,rgba(124,155,255,0.08),transparent_34%)] flex flex-col">
      <div className="max-w-3xl xl:max-w-[50rem] 2xl:max-w-[52rem] mx-auto w-full flex flex-1 flex-col space-y-5 sm:space-y-6 mood-fade-up">
        {children}
      </div>
    </div>
  );
}
