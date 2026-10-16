"use client";

import { ChevronDown, RotateCcw } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { DEFAULT_PARAMS, incompatibilities } from "@/lib/params";
import { cn } from "@/lib/utils";
import type { AdvancedParams, AdvancedSpec, VectorizeParams } from "@/types/api";

interface Props {
  params: VectorizeParams;
  onChange: (p: VectorizeParams) => void;
  disabled?: boolean;
  advancedSpecs?: AdvancedSpec[];
  maxBudget?: number;
}

function Field({ label, hint, htmlFor, children, value }: {
  label: string; hint: string; htmlFor?: string; children: ReactNode; value?: ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={htmlFor} className="text-sm font-medium">{label}</label>
        {value !== undefined && <span className="font-mono text-xs tabular-nums text-muted-foreground">{value}</span>}
      </div>
      {children}
      <p className="text-xs leading-snug text-muted-foreground">{hint}</p>
    </div>
  );
}

function Segmented<T extends string>({ value, options, onChange, disabled, name }: {
  value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; disabled?: boolean; name: string;
}) {
  return (
    <div role="radiogroup" aria-label={name} className="grid auto-cols-fr grid-flow-col gap-1 rounded-md bg-muted p-1">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          disabled={disabled}
          onClick={() => onChange(o.value)}
          className={cn(
            "rounded px-2 py-1 text-xs font-medium transition-colors disabled:opacity-50",
            value === o.value ? "bg-background shadow-sm" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function RangeInput({ id, value, min, max, step = 1, onChange, disabled, unit }: {
  id: string; value: number; min: number; max: number; step?: number; onChange: (v: number) => void;
  disabled?: boolean; unit?: string;
}) {
  return (
    <div className="flex items-center gap-3">
      <Slider
        className="flex-1"
        value={value}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onValueChange={(v) => onChange(typeof v === "number" ? v : v[0])}
        aria-label={id}
      />
      <div className="flex items-center gap-1">
        <input
          id={id}
          data-testid={`input-${id}`}
          type="number"
          className="h-7 w-16 rounded-md border border-input bg-transparent px-1.5 text-right font-mono text-xs tabular-nums"
          value={value}
          min={min}
          max={max}
          step={step}
          disabled={disabled}
          onChange={(e) => {
            const n = Number(e.target.value);
            if (Number.isFinite(n)) onChange(Math.min(max, Math.max(min, n)));
          }}
        />
        {unit && <span className="w-4 text-xs text-muted-foreground">{unit}</span>}
      </div>
    </div>
  );
}

function Toggle({ id, label, hint, checked, onChange, disabled }: {
  id: string; label: string; hint: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="space-y-0.5">
        <label htmlFor={id} className="text-sm font-medium">{label}</label>
        <p className="text-xs leading-snug text-muted-foreground">{hint}</p>
      </div>
      <Switch id={id} data-testid={`switch-${id}`} checked={checked} onCheckedChange={onChange} disabled={disabled} />
    </div>
  );
}

const ADVANCED_LABELS: Record<keyof AdvancedParams, string> = {
  filter_speckle: "Filtro de manchas",
  color_precision: "Precisión de color",
  layer_difference: "Diferencia entre capas",
  corner_threshold: "Umbral de esquinas",
  length_threshold: "Longitud mínima de segmento",
  splice_threshold: "Umbral de empalme",
  max_iterations: "Iteraciones de ajuste",
  path_precision: "Decimales de coordenadas",
  hierarchical: "Jerarquía de capas",
};

function AdvancedField({ spec, value, onChange, disabled }: {
  spec: AdvancedSpec; value: number | string | null; onChange: (v: number | string | null) => void; disabled?: boolean;
}) {
  const auto = value === null;
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-2">
        <label htmlFor={`adv-${spec.id}`} className="text-xs font-medium">
          {ADVANCED_LABELS[spec.id]} <span className="font-normal text-muted-foreground">({spec.id}{spec.unit ? `, ${spec.unit}` : ""})</span>
        </label>
        <label className="flex items-center gap-1 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={auto}
            disabled={disabled}
            data-testid={`auto-${spec.id}`}
            onChange={(e) => onChange(e.target.checked ? null : spec.values ? spec.values[0] : (spec.min ?? 0))}
          />
          perfil
        </label>
      </div>
      {spec.values ? (
        <select
          id={`adv-${spec.id}`}
          disabled={disabled || auto}
          value={auto ? "" : String(value)}
          onChange={(e) => onChange(e.target.value)}
          className="h-7 w-full rounded-md border border-input bg-transparent px-1.5 text-xs disabled:opacity-50"
        >
          {auto && <option value="">derivado del perfil</option>}
          {spec.values.map((v) => <option key={v} value={v}>{v}</option>)}
        </select>
      ) : (
        <input
          id={`adv-${spec.id}`}
          type="number"
          disabled={disabled || auto}
          placeholder="derivado del perfil"
          value={auto ? "" : Number(value)}
          min={spec.min}
          max={spec.max}
          step={spec.id === "length_threshold" ? 0.1 : 1}
          onChange={(e) => {
            const n = Number(e.target.value);
            if (e.target.value !== "" && Number.isFinite(n)) onChange(n);
          }}
          className="h-7 w-full rounded-md border border-input bg-transparent px-1.5 font-mono text-xs disabled:opacity-50"
        />
      )}
      <p className="text-[11px] leading-snug text-muted-foreground">{spec.effect}</p>
    </div>
  );
}

export function ParamsPanel({ params, onChange, disabled, advancedSpecs, maxBudget = 4 }: Props) {
  const set = <K extends keyof VectorizeParams>(key: K, value: VectorizeParams[K]) => onChange({ ...params, [key]: value });
  const problems = incompatibilities(params);
  const overrides = Object.values(params.advanced).filter((v) => v !== null).length;

  return (
    <div className="space-y-5" data-testid="params-panel">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold">Parámetros</h2>
          <p className="text-xs text-muted-foreground">Perfil <span className="font-mono">cartoon_fidelity_v1</span></p>
        </div>
        <Button variant="ghost" size="sm" disabled={disabled} onClick={() => onChange(DEFAULT_PARAMS)}>
          <RotateCcw className="size-3.5" /> Restablecer
        </Button>
      </div>

      <Field label="Modo de vectorización" hint="Auto compara trazado integral y por capas (contornos separados) y elige según métricas.">
        <Segmented name="Modo de vectorización" value={params.strategy} disabled={disabled} onChange={(v) => set("strategy", v)}
          options={[{ value: "auto", label: "Auto" }, { value: "integral", label: "Integral" }, { value: "layered", label: "Por capas" }]} />
      </Field>

      <Field label="Modo de curvas" hint="Spline: curvas suaves editables. Polígono: segmentos rectos. Píxel: bordes exactos. Auto: prueba spline y polígono.">
        <Segmented name="Modo de curvas" value={params.curve_mode} disabled={disabled} onChange={(v) => set("curve_mode", v)}
          options={[{ value: "spline", label: "Spline" }, { value: "polygon", label: "Polígono" }, { value: "pixel", label: "Píxel" }, { value: "auto", label: "Auto" }]} />
      </Field>

      <Field label="Colores máximos" htmlFor="max_colors" hint="Límite de la paleta preprocesada. Los colores minoritarios distintivos tienen cupo reservado.">
        <RangeInput id="max_colors" value={params.max_colors} min={2} max={256} disabled={disabled} onChange={(v) => set("max_colors", v)} />
      </Field>

      <Field label="Conservación de detalles" htmlFor="detail_preservation" hint="100 % = política más conservadora: sin filtrado de manchas, mínima fusión de colores. No garantiza cada píxel.">
        <RangeInput id="detail_preservation" value={params.detail_preservation} min={0} max={100} unit="%" disabled={disabled} onChange={(v) => set("detail_preservation", v)} />
      </Field>

      <Field label="Énfasis en contornos negros" htmlFor="outline_emphasis" hint="Sensibilidad de la detección de líneas oscuras (umbral de oscuridad y grosor máximo). No engrosa trazos. 0 = desactivado.">
        <RangeInput id="outline_emphasis" value={params.outline_emphasis} min={0} max={100} unit="%" disabled={disabled} onChange={(v) => set("outline_emphasis", v)} />
      </Field>

      <Toggle id="preserve_alpha" label="Preservar transparencia" hint="Las zonas transparentes no generan formas. El alfa parcial se binariza."
        checked={params.preserve_alpha} disabled={disabled} onChange={(v) => set("preserve_alpha", v)} />
      {params.preserve_alpha && (
        <Field label="Umbral de alfa" htmlFor="alpha_threshold" hint="Píxeles con alfa por debajo de este nivel (0–255) se consideran transparentes.">
          <RangeInput id="alpha_threshold" value={params.alpha_threshold} min={1} max={255} disabled={disabled} onChange={(v) => set("alpha_threshold", v)} />
        </Field>
      )}

      <Field label="Tratamiento del fondo" hint="Eliminar: vuelve transparente un fondo liso conectado con el borde (requiere transparencia).">
        <Segmented name="Tratamiento del fondo" value={params.background_mode} disabled={disabled} onChange={(v) => set("background_mode", v)}
          options={[{ value: "keep", label: "Conservar" }, { value: "remove_uniform", label: "Eliminar fondo liso" }]} />
      </Field>
      {params.background_mode === "remove_uniform" && (
        <Field label="Tolerancia del fondo" htmlFor="background_tolerance" hint="Distancia de color (ΔE) máxima al color de fondo detectado.">
          <RangeInput id="background_tolerance" value={params.background_tolerance} min={0.5} max={40} step={0.5} disabled={disabled} onChange={(v) => set("background_tolerance", v)} />
        </Field>
      )}

      <Toggle id="denoise_lossy" label="Filtrar artefactos de compresión" hint="Solo JPEG/WebP con pérdida: filtro que conserva bordes antes de la paleta."
        checked={params.denoise_lossy} disabled={disabled} onChange={(v) => set("denoise_lossy", v)} />

      <Toggle id="visual_validation" label="Validación visual" hint="Renderiza el SVG y calcula métricas. Necesaria para comparar candidatos."
        checked={params.visual_validation} disabled={disabled} onChange={(v) => set("visual_validation", v)} />

      <Field label="Sobremuestreo del trazado" hint="Traza una versión ampliada (sin colores nuevos) para colocar los bordes con precisión de subpíxel en imágenes pequeñas. Auto: ×1–×4 hasta ~1600 px de lado. El SVG conserva el tamaño original; más alto = más tiempo.">
        <Segmented name="Sobremuestreo del trazado" value={String(params.supersample)} disabled={disabled} onChange={(v) => set("supersample", Number(v))}
          options={[{ value: "0", label: "Auto" }, { value: "1", label: "×1" }, { value: "2", label: "×2" }, { value: "3", label: "×3" }, { value: "4", label: "×4" }]} />
      </Field>

      <Field label="Presupuesto de candidatos" htmlFor="candidate_budget" hint="Número máximo de configuraciones evaluadas por trabajo (más = más tiempo).">
        <RangeInput id="candidate_budget" value={params.candidate_budget} min={1} max={maxBudget} disabled={disabled} onChange={(v) => set("candidate_budget", v)} />
      </Field>

      <Collapsible>
        <CollapsibleTrigger className="flex w-full items-center justify-between rounded-md py-1 text-sm font-medium" data-testid="advanced-toggle">
          <span>Ajustes avanzados de VTracer {overrides > 0 && <span className="ml-1 rounded bg-primary/10 px-1.5 text-xs text-primary">{overrides} override</span>}</span>
          <ChevronDown className="size-4" />
        </CollapsibleTrigger>
        <CollapsibleContent className="space-y-3 pt-3">
          <p className="text-xs text-muted-foreground">Por defecto se derivan del perfil. Un override sustituye el valor derivado y queda registrado.</p>
          {(advancedSpecs ?? []).map((spec) => (
            <AdvancedField key={spec.id} spec={spec} value={params.advanced[spec.id]} disabled={disabled}
              onChange={(v) => set("advanced", { ...params.advanced, [spec.id]: v } as AdvancedParams)} />
          ))}
          {!advancedSpecs && <p className="text-xs text-muted-foreground">Disponibles cuando el backend responde.</p>}
        </CollapsibleContent>
      </Collapsible>

      {problems.length > 0 && (
        <ul role="alert" data-testid="param-problems" className="space-y-1 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs text-amber-900 dark:text-amber-200">
          {problems.map((p) => <li key={p}>{p}</li>)}
        </ul>
      )}
    </div>
  );
}
