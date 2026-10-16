"use client";

import { useSyncExternalStore } from "react";
import { getMockState, subscribeMockState } from "@/lib/api";

/**
 * Global banner when screens are rendering bundled demo data: either forced
 * (NEXT_PUBLIC_USE_MOCK=1) or automatic fallback because the backend is
 * unreachable. Retry re-fires every mounted data hook.
 */
export default function OfflineNotice() {
  const state = useSyncExternalStore(
    subscribeMockState,
    getMockState,
    getMockState
  );

  if (!state.active) return null;

  if (state.forced) {
    return (
      <div className="no-print banner banner-cyan mx-5 mt-4 lg:mx-8" role="status">
        <span aria-hidden>◆</span>
        <div>
          <span className="font-medium">Mock mode</span>{" "}
          <span className="opacity-90">
            (NEXT_PUBLIC_USE_MOCK=1) — screens render bundled demo data matching
            the API contract. Set it to 0 to use the live backend.
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="no-print banner banner-amber mx-5 mt-4 lg:mx-8" role="alert">
      <span aria-hidden>⚠</span>
      <div className="flex flex-1 flex-wrap items-center justify-between gap-2">
        <div>
          <span className="font-medium">Backend offline</span>{" "}
          <span className="opacity-90">
            — showing local demo data (mock). Start the API with{" "}
            <code className="num rounded bg-black/30 px-1 py-0.5 text-[11px]">
              scripts/run_api.sh
            </code>{" "}
            then retry.
          </span>
        </div>
        <button
          type="button"
          className="btn"
          onClick={() => window.dispatchEvent(new Event("estimator:retry"))}
        >
          Retry live API
        </button>
      </div>
    </div>
  );
}
