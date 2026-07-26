"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

interface Props {
  children: ReactNode;
  /** Optional fallback UI rendered when an error is caught. */
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * 🛡️ React Error Boundary — catches render/runtime errors in its subtree
 * and shows a recoverable "Something went wrong" card instead of a blank page.
 *
 * Wrap the app shell (or any self-contained feature panel) in <ErrorBoundary>
 * so one broken component never takes down the whole UI.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Structured log — visible in browser DevTools and any log aggregator.
    console.error("[ChatMood] ErrorBoundary caught:", error, info.componentStack);
  }

  private handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      return (
        <div className="flex min-h-[200px] flex-col items-center justify-center gap-4 rounded-2xl border border-white/10 bg-[#131316]/95 p-8 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-red-500/15">
            <AlertTriangle className="h-6 w-6 text-red-400" />
          </div>
          <div className="space-y-1">
            <p className="text-sm font-medium text-white">Something went wrong</p>
            <p className="max-w-sm text-xs text-gray-500">
              {this.state.error?.message?.slice(0, 200) || "An unexpected error occurred."}
            </p>
          </div>
          <button
            type="button"
            onClick={this.handleReset}
            className="inline-flex items-center gap-1.5 rounded-lg bg-accent/15 px-4 py-2 text-xs font-medium text-accent transition hover:bg-accent/25"
          >
            <RefreshCw size={13} />
            Try again
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
