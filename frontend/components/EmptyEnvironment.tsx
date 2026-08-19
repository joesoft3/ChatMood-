"use client";

import React from "react";

type Pill = {
  icon?: React.ReactNode;
  label: string;
  onClick: () => void;
  ariaLabel?: string;
};

interface EmptyEnvironmentProps {
  /** Optional mark above the heading. Hidden by default so empty states match ChatGPT home. */
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
 * Centered empty state used by the ChatGPT-style home (h1 + composer + starters).
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
    <div className={`flex flex-1 flex-col items-center justify-center gap-7 py-8 ${className ?? ""}`}>
      <div className="flex flex-col items-center gap-3 text-center select-none">
        {bubble && <span className="grid h-11 w-11 place-items-center rounded-full bg-composer">{bubble}</span>}
        <h1 className="text-center text-[32px] font-semibold tracking-tight text-gray-100">{title}</h1>
        {description && <p className="max-w-xl text-center text-sm leading-relaxed text-gray-400">{description}</p>}
      </div>

      {children && <div className="w-full max-w-[48rem]">{children}</div>}

      {pills && pills.length > 0 && (
        <div className="w-full max-w-[48rem] px-2">
          <nav className="flex flex-wrap items-center justify-center gap-2" aria-label="Quick actions">
            {pills.map(({ icon, label, onClick, ariaLabel }) => (
              <button
                key={label}
                onClick={onClick}
                aria-label={ariaLabel ?? label}
                className="inline-flex items-center gap-2 rounded-full bg-composer px-4 py-2 text-sm text-gray-200 transition hover:bg-white/10"
              >
                {icon && <span className="text-gray-400" aria-hidden>{icon}</span>}
                {label}
              </button>
            ))}
          </nav>
        </div>
      )}

      {actions && (
        <div className="flex w-full max-w-[48rem] flex-wrap items-center justify-center gap-2 px-2">
          {actions}
        </div>
      )}

      {footer && <div className="w-full max-w-[48rem] text-center">{footer}</div>}
    </div>
  );
}

/**
 * Full-page wrapper that mirrors chat's scroll + background so any page
 * using EmptyEnvironment feels like the same world.
 */
export function EmptyEnvironmentPage({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-3 py-5 scrollbar-thin sm:px-4 sm:py-6">
      <div className="mx-auto flex w-full max-w-[48rem] flex-1 flex-col space-y-6 mood-fade-up">
        {children}
      </div>
    </div>
  );
}
