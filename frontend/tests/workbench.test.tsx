import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Workbench } from "@/components/workbench";
import type { JobResponse } from "@/types/api";

import { capabilities, completed, failed, pngFile, report, running } from "./fixtures";

type Route = (url: string, init?: RequestInit) => Response | Promise<Response>;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

function mockFetch(route: Route) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => route(String(input), init));
}

function backend(sequence: JobResponse[]): Route {
  let i = 0;
  return (url, init) => {
    if (url.endsWith("/api/v1/capabilities")) return json(capabilities);
    if (url.endsWith("/api/v1/jobs") && init?.method === "POST") return json(sequence[0], 202);
    if (url.includes("/metrics")) return json(report);
    if (url.includes("/download.svg")) return new Response("<svg/>", { headers: { "content-disposition": 'attachment; filename="vectorlab-aaaaaaaa.svg"' } });
    if (/\/api\/v1\/jobs\/[a-f0-9]+$/.test(url)) return json(sequence[Math.min(++i, sequence.length - 1)]);
    return json({ error: { code: "not_found", message: "?" } }, 404);
  };
}

async function loadFile() {
  await waitFor(() => expect(screen.getByTestId("backend-status")).toHaveTextContent("vtracer 0.6.15"));
  await userEvent.upload(screen.getByTestId("file-input"), pngFile());
  await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("Archivo cargado"));
}

describe("Workbench", () => {
  it("estado inicial sin archivo con el botón deshabilitado", async () => {
    mockFetch(backend([running]));
    render(<Workbench />);
    expect(screen.getByTestId("phase")).toHaveTextContent("Sin archivo");
    expect(screen.getByTestId("run")).toBeDisabled();
    await waitFor(() => expect(screen.getByTestId("backend-status")).toHaveTextContent("vtracer"));
  });

  it("muestra progreso, resultado validado y descarga", async () => {
    const fetchSpy = mockFetch(backend([running, running, completed]));
    render(<Workbench />);
    await loadFile();
    expect(screen.getByTestId("file-info")).toHaveTextContent("100×80");
    await userEvent.click(screen.getByTestId("run"));
    await waitFor(() => expect(screen.getByTestId("stage")).toHaveTextContent("trazado integral_spline"));
    expect(screen.getByText("40 %")).toBeInTheDocument();
    expect(screen.queryByTestId("download-svg")).toBeNull(); // no se muestra hasta confirmar
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("Resultado disponible"), { timeout: 4000 });
    expect(screen.getByTestId("metric-ssim")).toHaveTextContent("0.9876");
    expect(screen.getByTestId("warnings")).toHaveTextContent("detalles pequeños");
    expect(screen.getByAltText("Resultado SVG")).toHaveAttribute("src", expect.stringContaining("download.svg?disposition=inline"));

    const sent = fetchSpy.mock.calls.find(([u, i]) => String(u).endsWith("/api/v1/jobs") && i?.method === "POST");
    const params = JSON.parse(String((sent?.[1]?.body as FormData).get("params")));
    expect(params).toMatchObject({ max_colors: 64, detail_preservation: 100, outline_emphasis: 80 });

    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    await userEvent.click(screen.getByTestId("download-svg"));
    await waitFor(() => expect(click).toHaveBeenCalled());
    expect(fetchSpy.mock.calls.some(([u]) => String(u).endsWith(`/jobs/${completed.job_id}/download.svg`))).toBe(true);
  });

  it("muestra el error del trabajo y permite reintentar", async () => {
    mockFetch(backend([running, failed]));
    render(<Workbench />);
    await loadFile();
    await userEvent.click(screen.getByTestId("run"));
    await waitFor(() => expect(screen.getByTestId("error-box")).toHaveTextContent("dañada"), { timeout: 4000 });
    expect(screen.getByTestId("run")).toHaveTextContent("Reprocesar");
    expect(screen.getByTestId("run")).toBeEnabled();
  });

  it("rechazo del backend (422) es un error recuperable con detalles", async () => {
    mockFetch((url, init) => {
      if (url.endsWith("/capabilities")) return json(capabilities);
      if (init?.method === "POST") return json({ error: { code: "incompatible_params", message: "Parámetros no válidos.", details: {} } }, 422);
      return json({}, 404);
    });
    render(<Workbench />);
    await loadFile();
    await userEvent.click(screen.getByTestId("run"));
    await waitFor(() => expect(screen.getByTestId("error-box")).toHaveTextContent("No se pudo procesar"));
  });

  it("backend caído: error fatal visible", async () => {
    mockFetch(() => { throw new TypeError("Failed to fetch"); });
    render(<Workbench />);
    await waitFor(() => expect(screen.getByTestId("backend-status")).toHaveTextContent("no disponible"));
    expect(screen.getByRole("alert")).toHaveTextContent("dev.sh");
  });

  it("cancelación", async () => {
    let cancelled = false;
    mockFetch((url, init) => {
      if (url.endsWith("/capabilities")) return json(capabilities);
      if (url.endsWith("/cancel")) { cancelled = true; return json({ ...running, state: "running" }); }
      if (init?.method === "POST") return json(running, 202);
      return json(cancelled ? { ...running, state: "cancelled", stage: "cancelado" } : running);
    });
    render(<Workbench />);
    await loadFile();
    await userEvent.click(screen.getByTestId("run"));
    const cancel = await screen.findByRole("button", { name: "Cancelar" });
    await act(async () => { await userEvent.click(cancel); });
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("Cancelado"), { timeout: 4000 });
  });
});
