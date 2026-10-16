"use client";

import { Ban, Download, FileImage, Loader2, Play, RefreshCw, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Comparator } from "@/components/comparator";
import { MessagesPanel } from "@/components/messages-panel";
import { MetricsPanel } from "@/components/metrics-panel";
import { ParamsPanel } from "@/components/params-panel";
import { UploadZone } from "@/components/upload-zone";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { type Phase, useVectorizeJob } from "@/hooks/use-vectorize-job";
import { ApiError, api, downloadFile, pngUrl, svgUrl } from "@/lib/api";
import { FALLBACK_LIMITS, formatBytes } from "@/lib/file-validation";
import { DEFAULT_PARAMS, incompatibilities, loadParams, saveParams } from "@/lib/params";
import type { Capabilities, VectorizeParams } from "@/types/api";

type Backend = { status: "checking" } | { status: "ok"; caps: Capabilities } | { status: "down"; message: string };

const PHASE_LABEL: Record<Phase["kind"], string> = {
  empty: "Sin archivo",
  validating: "Validando archivo…",
  loaded: "Archivo cargado",
  processing: "Procesando",
  cancelling: "Cancelando…",
  completed: "Resultado disponible",
  cancelled: "Cancelado",
  error: "Error",
};

function useBackend(): Backend {
  const [backend, setBackend] = useState<Backend>({ status: "checking" });
  useEffect(() => {
    const ctrl = new AbortController();
    api.capabilities(ctrl.signal)
      .then((caps) => setBackend({ status: "ok", caps }))
      .catch((e: unknown) => {
        if (ctrl.signal.aborted) return;
        setBackend({ status: "down", message: e instanceof ApiError ? e.message : String(e) });
      });
    return () => ctrl.abort();
  }, []);
  return backend;
}

function useSessionParams(): [VectorizeParams, (p: VectorizeParams) => void] {
  const [params, setParams] = useState<VectorizeParams>(DEFAULT_PARAMS);
  useEffect(() => {
    // Se lee tras montar para que el HTML prerenderizado coincida con la hidratación.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- sincronización única con sessionStorage
    setParams(loadParams(typeof window === "undefined" ? undefined : window.sessionStorage));
  }, []);
  const update = (p: VectorizeParams) => {
    setParams(p);
    saveParams(window.sessionStorage, p);
  };
  return [params, update];
}

export function Workbench() {
  const backend = useBackend();
  const caps = backend.status === "ok" ? backend.caps : null;
  const limits = useMemo(() => caps?.limits ?? FALLBACK_LIMITS, [caps]);
  const job = useVectorizeJob(limits);
  const [params, setParams] = useSessionParams();
  const [downloading, setDownloading] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const { phase, file } = job;
  const busy = phase.kind === "processing" || phase.kind === "cancelling" || phase.kind === "validating";
  const problems = incompatibilities(params);
  const canRun = !!file && !busy && problems.length === 0 && backend.status === "ok";
  const completed = phase.kind === "completed" ? phase : null;
  const activeJob = phase.kind === "processing" || phase.kind === "cancelling" ? phase.job : null;
  const jobId = completed?.job.job_id ?? null;

  const download = async (kind: "svg" | "png", candidate?: string) => {
    if (!jobId) return;
    const label = candidate ? `${kind}:${candidate}` : kind;
    setDownloading(label);
    setDownloadError(null);
    try {
      const url = kind === "svg" ? svgUrl(jobId, { candidate }) : pngUrl(jobId, candidate);
      await downloadFile(url, `vectorlab.${kind}`);
    } catch (e) {
      setDownloadError(e instanceof Error ? e.message : String(e));
    } finally {
      setDownloading(null);
    }
  };

  const progress = activeJob?.progress ?? (phase.kind === "processing" ? 0 : null);
  const resultUrl = jobId ? svgUrl(jobId, { inline: true }) : null;
  const errorInfo = phase.kind === "error" ? phase : null;

  return (
    <div className="flex h-dvh flex-col bg-background text-foreground">
      <header className="flex items-center gap-3 border-b px-4 py-2">
        <h1 className="text-sm font-semibold tracking-tight">VectorLab</h1>
        <span className="text-xs text-muted-foreground">Ráster → SVG editable para ilustraciones y caricaturas</span>
        <span className="ml-auto flex items-center gap-1.5 text-xs" data-testid="backend-status">
          <span className={`size-2 rounded-full ${backend.status === "ok" ? "bg-emerald-500" : backend.status === "down" ? "bg-red-500" : "bg-amber-400"}`} />
          {backend.status === "ok" && `Backend local · ${caps?.engines[0]?.name} ${caps?.engines[0]?.version}`}
          {backend.status === "checking" && "Conectando con el backend…"}
          {backend.status === "down" && "Backend no disponible"}
        </span>
      </header>

      {backend.status === "down" && (
        <div role="alert" className="border-b border-red-500/40 bg-red-500/10 px-4 py-2 text-xs text-red-900 dark:text-red-200">
          {backend.message} Arranque los servicios con <code className="font-mono">./scripts/dev.sh</code> y recargue la página.
        </div>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[320px_minmax(0,1fr)_340px]">
        <aside className="min-h-0 space-y-4 overflow-y-auto border-r p-4">
          <UploadZone disabled={busy} compact={!!file} onFile={(f) => void job.selectFile(f)} />
          {file && (
            <div className="flex items-center gap-2 rounded-md bg-muted/50 p-2 text-xs" data-testid="file-info">
              <FileImage className="size-4 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium" title={file.file.name}>{file.file.name}</p>
                <p className="text-muted-foreground">{file.format.toUpperCase()} · {file.width}×{file.height} · {formatBytes(file.file.size)}</p>
              </div>
              <Button variant="ghost" size="icon-xs" aria-label="Quitar archivo" disabled={busy} onClick={job.clear}><X /></Button>
            </div>
          )}
          <ParamsPanel params={params} onChange={setParams} disabled={busy} advancedSpecs={caps?.advanced_controls}
            maxBudget={caps?.limits.max_candidate_budget ?? 4} />
        </aside>

        <main className="flex min-h-[420px] min-w-0 flex-col">
          {file ? (
            <Comparator originalUrl={file.url} resultUrl={resultUrl} width={file.width} height={file.height}
              losses={completed?.report.metrics.lost_components ?? []} openSvgUrl={resultUrl} />
          ) : (
            <div className="flex flex-1 items-center justify-center p-8 text-center text-sm text-muted-foreground" data-testid="empty-state">
              <div className="max-w-sm space-y-2">
                <p className="font-medium text-foreground">Cargue una imagen para empezar</p>
                <p>La conversión se ejecuta en el backend local; ninguna imagen sale de este equipo.</p>
              </div>
            </div>
          )}
        </main>

        <aside className="min-h-0 space-y-4 overflow-y-auto border-l p-4">
          <section className="space-y-3" data-testid="status-panel">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold">Estado</h2>
              <span className="text-xs" data-testid="phase">{PHASE_LABEL[phase.kind]}</span>
            </div>
            {progress !== null && (
              <div className="space-y-1">
                <Progress value={progress} aria-label="Progreso" />
                <p className="flex justify-between text-xs text-muted-foreground">
                  <span data-testid="stage">{activeJob ? activeJob.stage : "enviando…"}</span>
                  <span className="font-mono tabular-nums">{Math.round(progress)} %</span>
                </p>
              </div>
            )}
            <div className="flex gap-2">
              {busy && activeJob ? (
                <Button variant="outline" className="flex-1" disabled={phase.kind === "cancelling"} onClick={() => void job.cancel(activeJob.job_id)}>
                  <Ban />{phase.kind === "cancelling" ? "Cancelando…" : "Cancelar"}
                </Button>
              ) : (
                <Button className="flex-1" disabled={!canRun} onClick={() => void job.start(params)} data-testid="run">
                  {busy ? <Loader2 className="animate-spin" /> : completed || phase.kind === "error" || phase.kind === "cancelled" ? <RefreshCw /> : <Play />}
                  {completed || phase.kind === "error" || phase.kind === "cancelled" ? "Reprocesar" : "Vectorizar"}
                </Button>
              )}
            </div>
            {completed && (
              <div className="grid grid-cols-2 gap-2">
                <Button variant="secondary" disabled={downloading !== null} onClick={() => void download("svg")} data-testid="download-svg">
                  {downloading === "svg" ? <Loader2 className="animate-spin" /> : <Download />}SVG
                </Button>
                <Button variant="secondary" disabled={downloading !== null} onClick={() => void download("png")} data-testid="download-png">
                  {downloading === "png" ? <Loader2 className="animate-spin" /> : <Download />}PNG vista previa
                </Button>
              </div>
            )}
            {downloading && <p className="text-xs text-muted-foreground" data-testid="downloading">Descargando…</p>}
            {downloadError && <p role="alert" className="text-xs text-red-400">{downloadError}</p>}
            {phase.kind === "cancelled" && <p className="text-xs text-muted-foreground">El trabajo se canceló y sus archivos temporales se eliminaron.</p>}
          </section>

          <MessagesPanel error={errorInfo} warnings={completed?.report.warnings} notes={completed?.report.notes}
            losses={completed?.report.metrics.lost_components} />
          {completed && (
            <MetricsPanel report={completed.report} downloading={downloading} onDownloadCandidate={(id) => void download("svg", id)} />
          )}
        </aside>
      </div>
    </div>
  );
}
