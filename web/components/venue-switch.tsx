"use client";

import { LoaderCircleIcon } from "lucide-react";
import { cn } from "cn";
import { useT } from "@/lib/i18n";
import type { VenueName, VenueState } from "@/lib/venue";

const VENUES: readonly VenueName[] = ["demo", "production"];

/**
 * Demo | Production segmented switch over a shared useVenue() state.
 * `compact` is the mode-bar form; the full form adds the hints under it.
 * A venue without credentials is disabled (the backend would 409 anyway).
 */
export function VenueSwitch({ state, compact = false }: { state: VenueState; compact?: boolean }) {
  const t = useT();
  const copy = t.common.venue;
  const { data, switching, switchError, switchTo } = state;

  if (!data?.supported) {
    return compact || !data ? null : <p className="text-sm text-muted-foreground">{copy.unsupported}</p>;
  }

  const current = data.venue;
  const protectedHere = current ? data.venues[current].protected_positions : 0;

  return (
    <div className={cn("flex flex-col gap-1", compact && "ml-auto items-end")}>
      <div className="flex items-center gap-2">
        {!compact && <span className="text-sm font-medium">{copy.label}</span>}
        <div
          role="radiogroup"
          aria-label={copy.label}
          className="inline-flex rounded-md border border-current/30 bg-background/60 p-0.5"
        >
          {VENUES.map((venue) => {
            const info = data.venues[venue];
            const selected = current === venue;
            const disabled = switching !== null || (!selected && !info.credentials.configured);
            return (
              <button
                key={venue}
                type="button"
                role="radio"
                aria-checked={selected}
                disabled={disabled}
                title={
                  info.credentials.configured
                    ? info.base_url
                    : copy.noCredentials(info.credentials.key_env, info.credentials.secret_env)
                }
                onClick={() => !selected && switchTo(venue)}
                className={cn(
                  "min-touch rounded px-3 text-xs font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50",
                  compact ? "py-1" : "py-1.5 text-sm",
                  selected
                    ? venue === "production"
                      ? "bg-red-600 text-white"
                      : "bg-blue-600 text-white"
                    : "text-foreground hover:bg-muted",
                )}
              >
                {switching === venue ? (
                  <LoaderCircleIcon className="inline size-3.5 animate-spin" aria-label={copy.switching} />
                ) : (
                  copy[venue]
                )}
              </button>
            );
          })}
        </div>
      </div>
      {switchError && (
        <p role="alert" className="text-xs font-medium text-red-700 dark:text-red-300">
          {copy.switchFailed(switchError.message)}
        </p>
      )}
      {protectedHere > 0 && (
        <p className={cn("text-xs", compact ? "max-w-xs text-right" : "text-amber-700 dark:text-amber-300")}>
          {copy.protectedPositions(protectedHere)}
        </p>
      )}
      {!compact &&
        VENUES.filter((venue) => !data.venues[venue].credentials.configured).map((venue) => (
          <p key={venue} className="text-xs text-muted-foreground">
            {copy[venue]}: {copy.noCredentials(
              data.venues[venue].credentials.key_env,
              data.venues[venue].credentials.secret_env,
            )}
          </p>
        ))}
    </div>
  );
}
