"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api";

export function errMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error && err.message) return err.message;
  return "Something went wrong";
}

/**
 * Load data on mount / dependency change, with a global retry hook:
 * the offline banner fires `estimator:retry` and every mounted resource
 * refetches (guided retry per checklist "Polish").
 */
export function useAsyncData<T>(
  loader: () => Promise<T>,
  deps: ReadonlyArray<unknown> = []
) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;
  const mounted = useRef(true);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await loaderRef.current();
      if (mounted.current) setData(next);
    } catch (err) {
      if (mounted.current) setError(errMessage(err));
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void reload();
    return () => {
      mounted.current = false;
    };
    // Deps are owned by the caller (e.g. [filterId]) — see docs on useAsyncData.
  }, [...deps]);

  useEffect(() => {
    const handler = () => void reload();
    window.addEventListener("estimator:retry", handler);
    return () => window.removeEventListener("estimator:retry", handler);
  }, [reload]);

  return { data, loading, error, reload };
}

/** Imperative action (button-triggered POSTs) with loading + error state. */
export function useAsyncAction<Args extends unknown[], T>(
  action: (...args: Args) => Promise<T>
) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const actionRef = useRef(action);
  actionRef.current = action;

  const run = useCallback(async (...args: Args): Promise<T | null> => {
    setLoading(true);
    setError(null);
    try {
      return await actionRef.current(...args);
    } catch (err) {
      setError(errMessage(err));
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  return { run, loading, error };
}
