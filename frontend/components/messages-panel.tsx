"use client";

import { AlertTriangle, Info, OctagonX } from "lucide-react";

import type { LostComponent } from "@/types/api";

interface Props {
  error?: { fatal: boolean; code: string; message: string; details?: Record<string, unknown> } | null;
  warnings?: string[];
  notes?: string[];
  losses?: LostComponent[];
}

function detailLines(details?: Record<string, unknown>): string[] {
  const errors = details?.errors;
  if (!Array.isArray(errors)) return [];
  return errors.map((e) => {
    const item = e as { loc?: unknown[]; msg?: string };
    const loc = Array.isArray(item.loc) ? item.loc.filter((p) => p !== "body").join(".") : "";
    return `${loc ? `${loc}: ` : ""}${item.msg ?? JSON.stringify(e)}`;
  });
}

export function MessagesPanel({ error, warnings = [], notes = [], losses = [] }: Props) {
  if (!error && warnings.length === 0 && notes.length === 0 && losses.length === 0) return null;
  return (
    <div className="space-y-3 text-xs" data-testid="messages-panel">
      {error && (
        <div role="alert" data-testid="error-box"
          className={error.fatal ? "rounded-md border border-red-500/40 bg-red-500/10 p-2.5 text-red-900 dark:text-red-200"
            : "rounded-md border border-amber-500/40 bg-amber-500/10 p-2.5 text-amber-900 dark:text-amber-200"}>
          <div className="flex items-center gap-1.5 font-semibold">
            <OctagonX className="size-4" />
            {error.fatal ? "Error del sistema" : "No se pudo procesar"} <span className="font-mono font-normal opacity-70">({error.code})</span>
          </div>
          <p className="mt-1">{error.message}</p>
          {detailLines(error.details).map((l) => <p key={l} className="mt-0.5 font-mono">{l}</p>)}
          <p className="mt-1 opacity-80">
            {error.fatal ? "Compruebe que el backend está en marcha (scripts/dev.sh) y vuelva a intentarlo."
              : "Corrija el archivo o los parámetros y vuelva a intentarlo; el archivo cargado se conserva."}
          </p>
        </div>
      )}
      {warnings.length > 0 && (
        <section>
          <h3 className="mb-1 flex items-center gap-1 font-semibold"><AlertTriangle className="size-3.5 text-amber-600" />Advertencias</h3>
          <ul className="list-disc space-y-0.5 pl-5" data-testid="warnings">{warnings.map((w) => <li key={w}>{w}</li>)}</ul>
        </section>
      )}
      {losses.length > 0 && (
        <section>
          <h3 className="mb-1 font-semibold">Posibles pérdidas detectadas ({losses.length} mayores)</h3>
          <ul className="space-y-0.5 font-mono">
            {losses.slice(0, 10).map((l, i) => (
              <li key={i} className="flex items-center gap-1.5">
                <span className="inline-block size-3 rounded-sm border" style={{ background: l.color }} />
                {l.area_px}px en ({l.bbox[0]}, {l.bbox[1]}) · {Math.round(l.matched_share * 100)} % coincidente
              </li>
            ))}
          </ul>
        </section>
      )}
      {notes.length > 0 && (
        <section>
          <h3 className="mb-1 flex items-center gap-1 font-semibold"><Info className="size-3.5" />Decisiones del pipeline</h3>
          <ul className="list-disc space-y-0.5 pl-5 text-muted-foreground">{notes.map((n) => <li key={n}>{n}</li>)}</ul>
        </section>
      )}
    </div>
  );
}
