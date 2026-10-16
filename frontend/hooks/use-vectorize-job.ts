"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";

import { ApiError, api } from "@/lib/api";
import { FALLBACK_LIMITS, type FileLimits, type ValidatedFile, validateFile } from "@/lib/file-validation";
import type { JobReport, JobResponse, VectorizeParams } from "@/types/api";

export const POLL_MS = 400;

export type Phase =
  | { kind: "empty" }
  | { kind: "validating" }
  | { kind: "loaded" }
  | { kind: "processing"; job: JobResponse | null }
  | { kind: "cancelling"; job: JobResponse | null }
  | { kind: "completed"; job: JobResponse; report: JobReport }
  | { kind: "cancelled" }
  | { kind: "error"; fatal: boolean; code: string; message: string; details?: Record<string, unknown> };

interface State {
  phase: Phase;
  file: ValidatedFile | null;
}

type Action =
  | { type: "validate" }
  | { type: "file"; file: ValidatedFile }
  | { type: "clear" }
  | { type: "phase"; phase: Phase };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "validate":
      return { ...state, phase: { kind: "validating" } };
    case "file":
      return { file: action.file, phase: { kind: "loaded" } };
    case "clear":
      return { file: null, phase: { kind: "empty" } };
    case "phase":
      return { ...state, phase: action.phase };
  }
}

export function errorPhase(e: unknown): Phase {
  if (e instanceof ApiError) {
    return { kind: "error", fatal: !e.recoverable, code: e.code, message: e.message, details: e.details };
  }
  const message = e instanceof Error ? e.message : String(e);
  return { kind: "error", fatal: false, code: "client_validation", message };
}

const sleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(t);
      reject(new DOMException("aborted", "AbortError"));
    });
  });

export function useVectorizeJob(limits: FileLimits = FALLBACK_LIMITS) {
  const [state, dispatch] = useReducer(reducer, { phase: { kind: "empty" }, file: null });
  const pollAbort = useRef<AbortController | null>(null);
  const fileRef = useRef<ValidatedFile | null>(null);

  useEffect(() => {
    fileRef.current = state.file;
  }, [state.file]);

  useEffect(
    () => () => {
      pollAbort.current?.abort();
      if (fileRef.current) URL.revokeObjectURL(fileRef.current.url);
    },
    [],
  );

  const selectFile = useCallback(
    async (file: File) => {
      pollAbort.current?.abort();
      dispatch({ type: "validate" });
      try {
        const validated = await validateFile(file, limits);
        if (fileRef.current) URL.revokeObjectURL(fileRef.current.url);
        dispatch({ type: "file", file: validated });
      } catch (e) {
        dispatch({ type: "phase", phase: errorPhase(e) });
      }
    },
    [limits],
  );

  const clear = useCallback(() => {
    pollAbort.current?.abort();
    if (fileRef.current) URL.revokeObjectURL(fileRef.current.url);
    dispatch({ type: "clear" });
  }, []);

  const start = useCallback(async (params: VectorizeParams) => {
    const file = fileRef.current;
    if (!file) return;
    pollAbort.current?.abort();
    const ctrl = new AbortController();
    pollAbort.current = ctrl;
    dispatch({ type: "phase", phase: { kind: "processing", job: null } });
    try {
      let job = await api.createJob(file.file, params, ctrl.signal);
      let cancelling = false;
      while (job.state === "queued" || job.state === "running") {
        dispatch({ type: "phase", phase: { kind: cancelling ? "cancelling" : "processing", job } });
        await sleep(POLL_MS, ctrl.signal);
        job = await api.getJob(job.job_id, ctrl.signal);
        cancelling = cancelling || ctrlCancelRequested(ctrl);
      }
      if (job.state === "completed") {
        // El resultado solo se muestra cuando el backend confirma generación y validación.
        const report = await api.report(job.job_id, ctrl.signal);
        dispatch({ type: "phase", phase: { kind: "completed", job, report } });
      } else if (job.state === "cancelled") {
        dispatch({ type: "phase", phase: { kind: "cancelled" } });
      } else {
        const err = job.error ?? { code: "job_failed", message: "El trabajo falló." };
        const fatal = err.code === "internal_error" || err.code === "engine_error";
        dispatch({ type: "phase", phase: { kind: "error", fatal, code: err.code, message: err.message } });
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      dispatch({ type: "phase", phase: errorPhase(e) });
    }
  }, []);

  const cancel = useCallback(async (jobId: string) => {
    if (pollAbort.current) cancelRequested.add(pollAbort.current);
    dispatch({ type: "phase", phase: { kind: "cancelling", job: null } });
    try {
      await api.cancelJob(jobId);
    } catch (e) {
      dispatch({ type: "phase", phase: errorPhase(e) });
    }
  }, []);

  return { ...state, selectFile, clear, start, cancel };
}

// Marca de "cancelación solicitada" por controlador de sondeo (mantiene el estado «cancelando»).
const cancelRequested = new WeakSet<AbortController>();
const ctrlCancelRequested = (c: AbortController) => cancelRequested.has(c);
