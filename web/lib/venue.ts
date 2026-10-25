"use client";

// Execution venue switch (Binance Demo / production): GET/PUT /api/venue.
// Shared by the mode bar and the Settings venue card. Every PUT sends
// Content-Type: application/json — the backend CSRF rule (contract §0).
import { useCallback, useEffect, useState } from "react";
import { networkHint, parseErrorResponse } from "@/lib/api";

export type VenueName = "demo" | "production";

export type VenueInfo = {
  base_url: string;
  credentials: { key_env: string; secret_env: string; configured: boolean };
  protected_positions: number;
};

export type VenuePayload = {
  generated_at: string;
  supported: boolean;
  venue: VenueName | null;
  base_url: string | null;
  effective_exec_mode: "live" | "dry";
  venues: Record<VenueName, VenueInfo>;
};

export class VenueApiError extends Error {
  status: number;
  code: string | null;

  constructor(status: number, code: string | null, message: string) {
    super(message);
    this.name = "VenueApiError";
    this.status = status;
    this.code = code;
  }
}

async function request(init?: RequestInit): Promise<VenuePayload> {
  let res: Response;
  try {
    res = await fetch("/api/venue", { cache: "no-store", ...init });
  } catch {
    throw new VenueApiError(0, "network", networkHint());
  }
  if (!res.ok) {
    const body = await parseErrorResponse(res);
    throw new VenueApiError(res.status, body.code, body.message);
  }
  return (await res.json()) as VenuePayload;
}

export const venueApi = {
  get: () => request(),
  set: (venue: VenueName) =>
    request({
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ venue }),
    }),
};

// Every mounted useVenue() refetches after a switch, so the mode bar and the
// Settings card never disagree about which venue is active.
const listeners = new Set<() => void>();

// Contract §1: settings go stale after 30s — same refresh cadence as the mode bar.
const REFRESH_INTERVAL_MS = 30_000;

export type VenueState = {
  data: VenuePayload | null;
  error: VenueApiError | null;
  switching: VenueName | null;
  switchError: VenueApiError | null;
  refresh: () => void;
  switchTo: (venue: VenueName) => void;
};

export function useVenue(): VenueState {
  const [data, setData] = useState<VenuePayload | null>(null);
  const [error, setError] = useState<VenueApiError | null>(null);
  const [switching, setSwitching] = useState<VenueName | null>(null);
  const [switchError, setSwitchError] = useState<VenueApiError | null>(null);

  const refresh = useCallback(() => {
    venueApi.get().then(
      (payload) => {
        setData(payload);
        setError(null);
      },
      (err: VenueApiError) => setError(err),
    );
  }, []);

  useEffect(() => {
    refresh();
    listeners.add(refresh);
    const id = setInterval(refresh, REFRESH_INTERVAL_MS);
    return () => {
      listeners.delete(refresh);
      clearInterval(id);
    };
  }, [refresh]);

  const switchTo = useCallback((venue: VenueName) => {
    setSwitching(venue);
    setSwitchError(null);
    venueApi.set(venue).then(
      (payload) => {
        setData(payload);
        listeners.forEach((listener) => listener());
      },
      (err: VenueApiError) => setSwitchError(err),
    ).finally(() => setSwitching(null));
  }, []);

  return { data, error, switching, switchError, refresh, switchTo };
}
