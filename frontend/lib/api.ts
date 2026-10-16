import type { ApiErrorBody, Capabilities, JobReport, JobResponse, VectorizeParams } from "@/types/api";

// El backend escucha solo en loopback. Se puede cambiar en tiempo de build con NEXT_PUBLIC_API_BASE.
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** Errores que el usuario puede corregir (archivo o parámetros) frente a fallos del sistema. */
  get recoverable(): boolean {
    return this.status >= 400 && this.status < 500;
  }
}

export function absoluteUrl(path: string): string {
  return path.startsWith("http") ? path : `${API_BASE}${path}`;
}

async function parse<T>(res: Response): Promise<T> {
  if (res.ok) return (await res.json()) as T;
  let body: { error?: ApiErrorBody } = {};
  try {
    body = (await res.json()) as { error?: ApiErrorBody };
  } catch {
    // respuesta sin JSON (p. ej. proxy caído)
  }
  const err = body.error;
  throw new ApiError(res.status, err?.code ?? "http_error", err?.message ?? `Error HTTP ${res.status}`, err?.details);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(absoluteUrl(path), init);
  } catch {
    throw new ApiError(0, "backend_unreachable", `No se pudo contactar con el backend en ${API_BASE}. ¿Está en marcha?`);
  }
  return parse<T>(res);
}

export const api = {
  health: (signal?: AbortSignal) => request<{ status: string; version: string }>("/api/v1/health", { signal }),
  capabilities: (signal?: AbortSignal) => request<Capabilities>("/api/v1/capabilities", { signal }),
  createJob: (file: File, params: VectorizeParams, signal?: AbortSignal) => {
    const form = new FormData();
    form.append("file", file);
    form.append("params", JSON.stringify(params));
    return request<JobResponse>("/api/v1/jobs", { method: "POST", body: form, signal });
  },
  getJob: (id: string, signal?: AbortSignal) => request<JobResponse>(`/api/v1/jobs/${id}`, { signal }),
  cancelJob: (id: string) => request<JobResponse>(`/api/v1/jobs/${id}/cancel`, { method: "POST" }),
  report: (id: string, signal?: AbortSignal) => request<JobReport>(`/api/v1/jobs/${id}/metrics`, { signal }),
};

export function svgUrl(jobId: string, opts: { candidate?: string; inline?: boolean } = {}): string {
  const q = new URLSearchParams();
  if (opts.candidate) q.set("candidate", opts.candidate);
  if (opts.inline) q.set("disposition", "inline");
  const qs = q.toString();
  return absoluteUrl(`/api/v1/jobs/${jobId}/download.svg${qs ? `?${qs}` : ""}`);
}

export function pngUrl(jobId: string, candidate?: string): string {
  return absoluteUrl(`/api/v1/jobs/${jobId}/download.png${candidate ? `?candidate=${encodeURIComponent(candidate)}` : ""}`);
}

/** Descarga un recurso como archivo; devuelve el nombre usado. */
export async function downloadFile(url: string, fallbackName: string): Promise<string> {
  let res: Response;
  try {
    res = await fetch(url);
  } catch {
    throw new ApiError(0, "backend_unreachable", "No se pudo descargar: el backend no responde.");
  }
  if (!res.ok) await parse(res);
  const disposition = res.headers.get("content-disposition") ?? "";
  const name = /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? fallbackName;
  const blob = await res.blob();
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
  return name;
}
