import { Component, type ErrorInfo, type ReactNode } from "react";
import { HOME_HASH } from "../router";
import {
  ERROR_BOUNDARY_HOME,
  ERROR_BOUNDARY_RETRY,
  ERROR_BOUNDARY_TITLE,
} from "../texts";

interface ErrorFallbackProps {
  onRetry: () => void;
}

/** Recovery card shown instead of a blank page when a screen throws while rendering. */
export function ErrorFallback({ onRetry }: ErrorFallbackProps) {
  return (
    <main className="mx-auto flex min-h-dvh max-w-md items-center px-4">
      <div
        role="alert"
        className="w-full rounded-2xl border border-[var(--border-subtle)] bg-[var(--surface-card)] p-6 text-[var(--ink-primary)]"
      >
        <p className="text-[length:var(--text-heading)] font-bold">{ERROR_BOUNDARY_TITLE}</p>
        <div className="mt-5 flex flex-wrap items-center gap-4">
          <button
            type="button"
            onClick={onRetry}
            className="rounded-xl bg-[var(--accent-primary)] px-4 py-2 text-[length:var(--text-body)] font-semibold text-[var(--accent-on-primary)] hover:bg-[var(--accent-primary-hover)]"
          >
            {ERROR_BOUNDARY_RETRY}
          </button>
          <a
            href={HOME_HASH}
            onClick={onRetry}
            className="text-[length:var(--text-body)] font-semibold text-[var(--accent-primary)] underline"
          >
            {ERROR_BOUNDARY_HOME}
          </a>
        </div>
      </div>
    </main>
  );
}

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Render error caught by ErrorBoundary", error, info.componentStack);
  }

  reset = (): void => {
    this.setState({ error: null });
  };

  render(): ReactNode {
    if (this.state.error !== null) return <ErrorFallback onRetry={this.reset} />;
    return this.props.children;
  }
}
