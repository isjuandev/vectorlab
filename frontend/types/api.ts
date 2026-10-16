// Tipos que reflejan los esquemas Pydantic del backend (backend/app/schemas.py).

export type Strategy = "auto" | "integral" | "layered";
export type CurveMode = "spline" | "polygon" | "pixel" | "auto";
export type Hierarchy = "stacked" | "cutout";
export type BackgroundMode = "keep" | "remove_uniform";
export type JobState = "queued" | "running" | "completed" | "failed" | "cancelled";

export interface AdvancedParams {
  filter_speckle: number | null;
  color_precision: number | null;
  layer_difference: number | null;
  corner_threshold: number | null;
  length_threshold: number | null;
  splice_threshold: number | null;
  max_iterations: number | null;
  path_precision: number | null;
  hierarchical: Hierarchy | null;
}

export interface VectorizeParams {
  profile: "cartoon_fidelity_v1";
  strategy: Strategy;
  curve_mode: CurveMode;
  max_colors: number;
  detail_preservation: number;
  outline_emphasis: number;
  preserve_alpha: boolean;
  alpha_threshold: number;
  background_mode: BackgroundMode;
  background_tolerance: number;
  denoise_lossy: boolean;
  visual_validation: boolean;
  candidate_budget: number;
  /** 0 = auto; 1–4 = factor de sobremuestreo del trazado. */
  supersample: number;
  advanced: AdvancedParams;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

export interface ExportLinks {
  svg: string;
  png: string;
  preview: string;
  metrics: string;
}

export interface CandidateSummary {
  id: string;
  strategy: string;
  curve_mode: string;
  score: number | null;
  selected: boolean;
  svg_bytes: number;
  paths: number;
  ssim: number | null;
}

export interface JobResponse {
  job_id: string;
  state: JobState;
  stage: string;
  progress: number;
  created_at: string;
  updated_at: string;
  input: { format?: string; width?: number; height?: number; bytes?: number };
  requested_params: VectorizeParams;
  effective_params: EffectiveParams | null;
  warnings: string[];
  error: ApiErrorBody | null;
  exports: ExportLinks | null;
  candidates: CandidateSummary[];
  metrics_summary: Record<string, number | null> | null;
}

export interface PaletteEntry {
  index: number;
  hex: string;
  pixels: number;
  share: number;
  protected: boolean;
}

export interface EffectiveParams {
  profile: string;
  engine: { name: string; version: string };
  vectorlab_version: string;
  selected_candidate: string;
  native_params: Record<string, Record<string, string | number>>;
  native_param_sources: Record<string, string>;
  supersample_factor: number;
  preprocessing: {
    alpha: { preserve_alpha: boolean; threshold: number; partial_alpha_pixels: number };
    background: {
      mode: BackgroundMode;
      detected_color: string | null;
      border_share: number;
      uniform: boolean;
      removed_pixels: number;
    };
    palette: { method: string; colors: number; limit: number; entries: PaletteEntry[] };
    outlines: {
      enabled: boolean;
      color: string | null;
      usable_for_layering: boolean;
      coverage?: number;
      pixels?: number;
    };
  };
}

export interface LostComponent {
  color: string;
  area_px: number;
  bbox: [number, number, number, number];
  matched_share: number;
  small: boolean;
}

export interface Metrics {
  comparison_size: [number, number];
  comparison_scale: number;
  ssim: number | null;
  alpha_iou: number | null;
  delta_e_mean: number | null;
  delta_e_p95: number | null;
  delta_e_interior_mean: number | null;
  delta_e_sampled: boolean;
  edge_mean_distance_px: number | null;
  edge_recall_1_5px: number | null;
  edge_precision_1_5px: number | null;
  edge_f1: number | null;
  region_agreement: number | null;
  region_mean_iou: number | null;
  outline_iou: number | null;
  components_total: number;
  components_preserved: number;
  components_lost: number;
  small_components_total: number;
  small_components_lost: number;
  small_component_max_area_px: number;
  lost_components: LostComponent[];
  score: number | null;
}

export interface SvgReport {
  width: number;
  height: number;
  has_viewbox: boolean;
  paths: number;
  nodes: number;
  segments: number;
  fill_colors: number;
  bytes: number;
  raster_embedded: boolean;
}

export interface CandidateReport {
  id: string;
  strategy: string;
  curve_mode: string;
  native_params: Record<string, string | number>;
  trace_seconds: number;
  svg_report: SvgReport;
  metrics: Metrics;
  selected: boolean;
}

export interface JobReport {
  input: {
    format: string;
    width: number;
    height: number;
    has_alpha: boolean;
    lossy: boolean;
    bytes: number;
    source_colors: number;
  };
  requested_params: VectorizeParams;
  effective_params: EffectiveParams;
  candidates: CandidateReport[];
  selected_candidate: string;
  metrics: Metrics;
  svg: SvgReport;
  timings_s: Record<string, number>;
  warnings: string[];
  notes: string[];
}

export interface ControlSpec {
  id: string;
  label: string;
  type: string;
  default: unknown;
  unit: string | null;
  stage: string;
  expected_effect: string;
  no_effect_cases: string;
  custom_operation?: string | null;
  native_params?: string[];
  min?: number;
  max?: number;
  values?: string[];
}

export interface AdvancedSpec {
  id: keyof AdvancedParams;
  unit: string | null;
  min?: number;
  max?: number;
  values?: string[];
  effect: string;
}

export interface Capabilities {
  formats: string[];
  limits: {
    max_upload_bytes: number;
    max_dimension: number;
    min_dimension: number;
    max_pixels: number;
    metrics_max_pixels: number;
    max_candidate_budget: number;
  };
  engines: { name: string; version: string; default: boolean }[];
  renderer: { name: string; version: string };
  profiles: { id: string; defaults: VectorizeParams }[];
  controls: ControlSpec[];
  advanced_controls: AdvancedSpec[];
}
