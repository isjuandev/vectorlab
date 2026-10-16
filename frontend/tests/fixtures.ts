import type { Capabilities, JobReport, JobResponse } from "@/types/api";

import { DEFAULT_PARAMS } from "@/lib/params";

export const PNG_BYTES = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13, 73, 72, 68, 82]);

export function pngFile(name = "dibujo.png"): File {
  return new File([PNG_BYTES], name, { type: "image/png" });
}

export const capabilities: Capabilities = {
  formats: ["image/png", "image/jpeg", "image/webp"],
  limits: { max_upload_bytes: 1024 * 1024, max_dimension: 6000, min_dimension: 8, max_pixels: 24_000_000, metrics_max_pixels: 4_000_000, max_candidate_budget: 4 },
  engines: [{ name: "vtracer", version: "0.6.15", default: true }],
  renderer: { name: "resvg-py", version: "0.5.0" },
  profiles: [{ id: "cartoon_fidelity_v1", defaults: DEFAULT_PARAMS }],
  controls: [],
  advanced_controls: [{ id: "filter_speckle", unit: "px", min: 0, max: 128, effect: "Descarta manchas menores." }],
};

const base: Omit<JobResponse, "state" | "stage" | "progress"> = {
  job_id: "a".repeat(32),
  created_at: "2026-10-15T00:00:00Z",
  updated_at: "2026-10-15T00:00:01Z",
  input: { format: "png", width: 100, height: 80, bytes: 16 },
  requested_params: DEFAULT_PARAMS,
  effective_params: null,
  warnings: [],
  error: null,
  exports: null,
  candidates: [],
  metrics_summary: null,
};

export const running: JobResponse = { ...base, state: "running", stage: "trazado integral_spline", progress: 40 };
export const completed: JobResponse = {
  ...base,
  state: "completed",
  stage: "completado",
  progress: 100,
  exports: { svg: "/x.svg", png: "/x.png", preview: "/p", metrics: "/m" },
};
export const failed: JobResponse = {
  ...base,
  state: "failed",
  stage: "error",
  progress: 10,
  error: { code: "corrupt_image", message: "La imagen está dañada o truncada." },
};

const metrics = {
  comparison_size: [100, 80] as [number, number], comparison_scale: 1, ssim: 0.9876, alpha_iou: null,
  delta_e_mean: 0.42, delta_e_p95: 1.1, delta_e_interior_mean: 0.1, delta_e_sampled: false,
  edge_mean_distance_px: 0.3, edge_recall_1_5px: 0.99, edge_precision_1_5px: 0.98, edge_f1: 0.985,
  region_agreement: 0.99, region_mean_iou: 0.95, outline_iou: 0.9, components_total: 10,
  components_preserved: 9, components_lost: 1, small_components_total: 4, small_components_lost: 1,
  small_component_max_area_px: 16,
  lost_components: [{ color: "#ff0000", area_px: 6, bbox: [10, 10, 3, 2] as [number, number, number, number], matched_share: 0.2, small: true }],
  score: 0.97,
};

export const report: JobReport = {
  input: { format: "png", width: 100, height: 80, has_alpha: false, lossy: false, bytes: 16, source_colors: 300 },
  requested_params: DEFAULT_PARAMS,
  effective_params: {
    profile: "cartoon_fidelity_v1",
    engine: { name: "vtracer", version: "0.6.15" },
    vectorlab_version: "0.1.0",
    selected_candidate: "integral_spline",
    native_params: { integral_spline: { filter_speckle: 0, mode: "spline", colormode: "color" } },
    native_param_sources: { filter_speckle: "derivado de detail_preservation", mode: "curve_mode" },
    supersample_factor: 3,
    preprocessing: {
      alpha: { preserve_alpha: true, threshold: 128, partial_alpha_pixels: 0 },
      background: { mode: "keep", detected_color: "#ffffff", border_share: 1, uniform: true, removed_pixels: 0 },
      palette: { method: "kmeans", colors: 2, limit: 64, entries: [
        { index: 0, hex: "#ffffff", pixels: 6000, share: 0.75, protected: false },
        { index: 1, hex: "#ff0000", pixels: 2000, share: 0.25, protected: true },
      ] },
      outlines: { enabled: true, color: "#141414", usable_for_layering: true },
    },
  },
  candidates: [
    { id: "integral_spline", strategy: "integral", curve_mode: "spline", native_params: { filter_speckle: 0, mode: "spline", colormode: "color" }, trace_seconds: 0.1,
      svg_report: { width: 100, height: 80, has_viewbox: true, paths: 12, nodes: 300, segments: 120, fill_colors: 2, bytes: 4096, raster_embedded: false },
      metrics, selected: true },
  ],
  selected_candidate: "integral_spline",
  metrics,
  svg: { width: 100, height: 80, has_viewbox: true, paths: 12, nodes: 300, segments: 120, fill_colors: 2, bytes: 4096, raster_embedded: false },
  timings_s: { total: 0.5 },
  warnings: ["Se perdieron 1 de 4 detalles pequeños (ver lista de pérdidas)."],
  notes: ["Paleta reducida de 300 colores de origen a 2 (límite 64)."],
};
