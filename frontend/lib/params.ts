import { z } from "zod";

import type { VectorizeParams } from "@/types/api";

const nullableInt = (min: number, max: number) => z.number().int().min(min).max(max).nullable();

export const advancedSchema = z.object({
  filter_speckle: nullableInt(0, 128),
  color_precision: nullableInt(1, 8),
  layer_difference: nullableInt(1, 255),
  corner_threshold: nullableInt(0, 180),
  length_threshold: z.number().min(3.5).max(10).nullable(),
  splice_threshold: nullableInt(0, 180),
  max_iterations: nullableInt(1, 50),
  path_precision: nullableInt(0, 8),
  hierarchical: z.enum(["stacked", "cutout"]).nullable(),
});

// Mismo contrato y mismas reglas de compatibilidad que el backend (schemas.incompatibilities).
export const paramsSchema = z
  .object({
    profile: z.literal("cartoon_fidelity_v1"),
    strategy: z.enum(["auto", "integral", "layered"]),
    curve_mode: z.enum(["spline", "polygon", "pixel", "auto"]),
    max_colors: z.number().int().min(2).max(256),
    detail_preservation: z.number().int().min(0).max(100),
    outline_emphasis: z.number().int().min(0).max(100),
    preserve_alpha: z.boolean(),
    alpha_threshold: z.number().int().min(1).max(255),
    background_mode: z.enum(["keep", "remove_uniform"]),
    background_tolerance: z.number().min(0.5).max(40),
    denoise_lossy: z.boolean(),
    visual_validation: z.boolean(),
    candidate_budget: z.number().int().min(1).max(4),
    supersample: z.number().int().min(0).max(4),
    advanced: advancedSchema,
  })
  .superRefine((p, ctx) => {
    for (const message of incompatibilities(p)) ctx.addIssue({ code: "custom", message });
  });

export function incompatibilities(p: VectorizeParams): string[] {
  const out: string[] = [];
  if (p.strategy === "layered" && p.outline_emphasis === 0)
    out.push("El modo por capas necesita «Énfasis en contornos» > 0.");
  if (p.background_mode === "remove_uniform" && !p.preserve_alpha)
    out.push("Eliminar el fondo requiere preservar la transparencia.");
  const multi = p.strategy === "auto" || p.curve_mode === "auto";
  if (multi && !p.visual_validation && p.candidate_budget > 1)
    out.push("Comparar varios candidatos requiere la validación visual (la selección usa métricas).");
  return out;
}

export const DEFAULT_PARAMS: VectorizeParams = {
  profile: "cartoon_fidelity_v1",
  strategy: "auto",
  curve_mode: "spline",
  max_colors: 64,
  detail_preservation: 100,
  outline_emphasis: 80,
  preserve_alpha: true,
  alpha_threshold: 128,
  background_mode: "keep",
  background_tolerance: 6,
  denoise_lossy: true,
  visual_validation: true,
  candidate_budget: 2,
  supersample: 0,
  advanced: {
    filter_speckle: null,
    color_precision: null,
    layer_difference: null,
    corner_threshold: null,
    length_threshold: null,
    splice_threshold: null,
    max_iterations: null,
    path_precision: null,
    hierarchical: null,
  },
};

export const STORAGE_KEY = "vectorlab.params.v1";

/** Lee los parámetros guardados en la sesión del navegador; ignora datos corruptos o de otra versión. */
export function loadParams(storage: Pick<Storage, "getItem"> | undefined): VectorizeParams {
  if (!storage) return DEFAULT_PARAMS;
  try {
    const raw = storage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_PARAMS;
    // Los controles añadidos después de guardar toman su valor por defecto; el resto se conserva.
    const parsed = paramsSchema.safeParse({ ...DEFAULT_PARAMS, ...JSON.parse(raw) });
    return parsed.success ? (parsed.data as VectorizeParams) : DEFAULT_PARAMS;
  } catch {
    return DEFAULT_PARAMS;
  }
}

export function saveParams(storage: Pick<Storage, "setItem"> | undefined, params: VectorizeParams): void {
  try {
    storage?.setItem(STORAGE_KEY, JSON.stringify(params));
  } catch {
    // almacenamiento lleno o deshabilitado: la sesión sigue funcionando sin persistencia
  }
}
