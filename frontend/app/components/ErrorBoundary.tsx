"use client";

import React, { Component, ErrorInfo, ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * Error Boundary component to catch React rendering errors
 * and display a fallback UI instead of crashing the entire page.
 */
export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    // Log error to console for debugging
    console.error("ErrorBoundary caught an error:", error, errorInfo);
  }

  render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="card" style={{ padding: 24, textAlign: "center" }}>
          <h2 style={{ marginBottom: 12, color: "var(--error-fg, #ef4444)" }}>
            Something went wrong
          </h2>
          <p className="subtle" style={{ marginBottom: 16 }}>
            {this.state.error?.message || "An unexpected error occurred while rendering this component."}
          </p>
          <button
            className="btn"
            onClick={() => this.setState({ hasError: false, error: null })}
            style={{ padding: "8px 16px" }}
          >
            Try Again
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
