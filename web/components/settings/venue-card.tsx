"use client";

import { ServerIcon } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { VenueSwitch } from "@/components/venue-switch";
import { useT } from "@/lib/i18n";
import { useVenue } from "@/lib/venue";

/** Binance Demo / production venue switch (GET/PUT /api/venue). */
export function VenueCard() {
  const t = useT();
  const copy = t.common.venue;
  const state = useVenue();

  return (
    <Card className="mb-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ServerIcon className="size-5 shrink-0" aria-hidden="true" />
          {copy.title}
        </CardTitle>
        <CardDescription>{copy.description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {state.error ? (
          <p role="alert" className="text-sm text-destructive">{state.error.message}</p>
        ) : (
          <VenueSwitch state={state} />
        )}
        {state.data?.base_url && (
          <p className="font-mono text-xs text-muted-foreground">{state.data.base_url}</p>
        )}
      </CardContent>
    </Card>
  );
}
