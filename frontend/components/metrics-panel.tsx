"use client";

import { Download } from "lucide-react";

import { Button } from "@/components/ui/button";
import { formatBytes } from "@/lib/file-validation";
import { cn } from "@/lib/utils";
import type { JobReport, Metrics } from "@/types/api";

type Fmt = (v: number) => string;
const pct: Fmt = (v) => `${(v * 100).toFixed(1)} %`;
const num = (d: number): Fmt => (v) => v.toFixed(d);

interface MetricDef {
  key: keyof Metrics;
  label: string;
  hint: string;
  fmt: Fmt;
}

const METRICS: MetricDef[] = [
  { key: "ssim", label: "SSIM", hint: "Similitud estructural de luminancia (compuesto sobre blanco). 1 = idéntico.", fmt: num(4) },
  { key: "delta_e_mean", label: "ΔE2000 medio", hint: "Error de color perceptual medio. < 1 apenas perceptible; > 5 visible.", fmt: num(2) },
  { key: "delta_e_p95", label: "ΔE2000 p95", hint: "El 5 % de píxeles con más error de color (suele concentrarse en bordes).", fmt: num(2) },
  { key: "delta_e_interior_mean", label: "ΔE interior", hint: "Error de color lejos de los bordes (sin efecto del antialiasing).", fmt: num(2) },
  { key: "edge_f1", label: "Bordes F1 (≤1,5 px)", hint: "Coincidencia de bordes Canny entre original y SVG.", fmt: pct },
  { key: "edge_mean_distance_px", label: "Distancia de bordes", hint: "Distancia media simétrica entre bordes, en píxeles.", fmt: (v) => `${v.toFixed(2)} px` },
  { key: "region_agreement", label: "Acuerdo de regiones", hint: "Píxeles cuyo color de paleta coincide con la imagen preprocesada.", fmt: pct },
  { key: "region_mean_iou", label: "IoU medio de regiones", hint: "IoU promedio por color de paleta.", fmt: pct },
  { key: "outline_iou", label: "IoU de contornos", hint: "Coincidencia de la máscara de líneas oscuras.", fmt: pct },
  { key: "alpha_iou", label: "IoU de transparencia", hint: "Coincidencia de la silueta opaca (solo con alfa).", fmt: pct },
];

function MetricRow({ def, value }: { def: MetricDef; value: number | null | undefined }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1" title={def.hint}>
      <dt className="text-xs text-muted-foreground">{def.label}</dt>
      <dd className="font-mono text-xs tabular-nums" data-testid={`metric-${def.key}`}>
        {value === null || value === undefined ? <span className="text-muted-foreground">no aplicable</span> : def.fmt(value)}
      </dd>
    </div>
  );
}

interface Props {
  report: JobReport;
  onDownloadCandidate: (id: string) => void;
  downloading: string | null;
}

export function MetricsPanel({ report, onDownloadCandidate, downloading }: Props) {
  const m = report.metrics;
  const svg = report.svg;
  const eff = report.effective_params;
  const selected = report.candidates.find((c) => c.selected);
  return (
    <div className="space-y-5 text-sm" data-testid="metrics-panel">
      <section>
        <h3 className="mb-1 text-sm font-semibold">Métricas del resultado</h3>
        <p className="mb-2 text-xs text-muted-foreground">
          Calculadas a {m.comparison_size[0]}×{m.comparison_size[1]} px{m.comparison_scale < 1 ? ` (escala ${m.comparison_scale})` : ""}.
          Ninguna métrica aislada demuestra fidelidad absoluta.
        </p>
        <dl className="divide-y">
          {METRICS.map((d) => <MetricRow key={d.key} def={d} value={m[d.key] as number | null} />)}
          <div className="flex items-baseline justify-between py-1" title="Regiones conexas de la imagen preprocesada que sobreviven en el SVG (≥ 50 % de sus píxeles).">
            <dt className="text-xs text-muted-foreground">Componentes conservados</dt>
            <dd className="font-mono text-xs tabular-nums" data-testid="metric-components">{m.components_preserved}/{m.components_total}</dd>
          </div>
          <div className="flex items-baseline justify-between py-1" title={`Componentes de ≤ ${m.small_component_max_area_px} px.`}>
            <dt className="text-xs text-muted-foreground">Detalles pequeños perdidos</dt>
            <dd className={cn("font-mono text-xs tabular-nums", m.small_components_lost > 0 && "text-amber-600")}>{m.small_components_lost}/{m.small_components_total}</dd>
          </div>
        </dl>
      </section>

      <section>
        <h3 className="mb-1 text-sm font-semibold">SVG</h3>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
          <dt className="text-muted-foreground">Rutas</dt><dd className="text-right font-mono" data-testid="svg-paths">{svg.paths.toLocaleString("es")}</dd>
          <dt className="text-muted-foreground">Nodos</dt><dd className="text-right font-mono">{svg.nodes.toLocaleString("es")}</dd>
          <dt className="text-muted-foreground">Colores de relleno</dt><dd className="text-right font-mono">{svg.fill_colors}</dd>
          <dt className="text-muted-foreground">Tamaño</dt><dd className="text-right font-mono">{formatBytes(svg.bytes)}</dd>
          <dt className="text-muted-foreground">Ráster incrustado</dt><dd className="text-right font-mono">{svg.raster_embedded ? "sí" : "no"}</dd>
          <dt className="text-muted-foreground">Sobremuestreo</dt><dd className="text-right font-mono" data-testid="svg-supersample">×{eff.supersample_factor ?? 1}</dd>
          <dt className="text-muted-foreground">Tiempo total</dt><dd className="text-right font-mono">{report.timings_s.total?.toFixed(2)} s</dd>
        </dl>
      </section>

      <section>
        <h3 className="mb-1 text-sm font-semibold">Candidatos evaluados</h3>
        <table className="w-full text-xs" data-testid="candidates-table">
          <thead className="text-muted-foreground">
            <tr><th className="text-left font-normal">Candidato</th><th className="text-right font-normal">Puntuación</th><th className="text-right font-normal">SSIM</th><th className="text-right font-normal">Rutas</th><th /></tr>
          </thead>
          <tbody>
            {report.candidates.map((c) => (
              <tr key={c.id} className={cn(c.selected && "font-medium")}>
                <td className="py-0.5">{c.id}{c.selected && <span className="ml-1 text-primary">✓</span>}</td>
                <td className="text-right font-mono">{c.metrics.score?.toFixed(4) ?? "—"}</td>
                <td className="text-right font-mono">{c.metrics.ssim?.toFixed(4) ?? "—"}</td>
                <td className="text-right font-mono">{c.svg_report.paths}</td>
                <td className="text-right">
                  <Button variant="ghost" size="icon-xs" aria-label={`Descargar SVG ${c.id}`} disabled={downloading !== null}
                    onClick={() => onDownloadCandidate(c.id)}><Download /></Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-1 text-[11px] text-muted-foreground">
          Puntuación = 0,35·SSIM + 0,30·regiones + 0,20·bordes F1 + 0,15·color − 0,10·componentes perdidos. Solo ordena candidatos del mismo trabajo.
        </p>
      </section>

      <section>
        <h3 className="mb-1 text-sm font-semibold">Paleta ({eff.preprocessing.palette.colors} / límite {eff.preprocessing.palette.limit})</h3>
        <p className="mb-1.5 text-xs text-muted-foreground">
          Origen: {report.input.source_colors.toLocaleString("es")} colores · método {eff.preprocessing.palette.method === "exact" ? "exacto (sin cuantizar)" : "k-means CIELAB"}
        </p>
        <div className="flex flex-wrap gap-1" data-testid="palette">
          {eff.preprocessing.palette.entries.map((e) => (
            <span key={e.index} title={`${e.hex} · ${(e.share * 100).toFixed(2)} %${e.protected ? " · protegido" : ""}`}
              className={cn("size-5 rounded-sm border", e.protected && "ring-2 ring-amber-500 ring-offset-1")}
              style={{ background: e.hex }} />
          ))}
        </div>
      </section>

      <section>
        <h3 className="mb-1 text-sm font-semibold">Parámetros efectivos ({selected?.id})</h3>
        <p className="mb-1 text-xs text-muted-foreground">Motor {eff.engine.name} {eff.engine.version} · VectorLab {eff.vectorlab_version}</p>
        <table className="w-full text-xs" data-testid="effective-params">
          <tbody>
            {selected && Object.entries(selected.native_params).map(([k, v]) => (
              <tr key={k}>
                <td className="py-0.5 font-mono">{k}</td>
                <td className="text-right font-mono">{String(v)}</td>
                <td className="pl-2 text-right text-[11px] text-muted-foreground">{eff.native_param_sources[k] ?? (k === "colormode" ? "estrategia" : "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
