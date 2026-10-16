import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { fitView, zoomAt } from "@/components/comparator";
import { MessagesPanel } from "@/components/messages-panel";
import { ParamsPanel } from "@/components/params-panel";
import { UploadZone } from "@/components/upload-zone";
import { DEFAULT_PARAMS } from "@/lib/params";
import type { VectorizeParams } from "@/types/api";

import { capabilities, pngFile } from "./fixtures";

function Harness({ spy }: { spy: (p: VectorizeParams) => void }) {
  const [p, setP] = useState(DEFAULT_PARAMS);
  return <ParamsPanel params={p} advancedSpecs={capabilities.advanced_controls} onChange={(n) => { setP(n); spy(n); }} />;
}

describe("UploadZone", () => {
  it("entrega el archivo seleccionado y admite arrastrar y soltar", async () => {
    const onFile = vi.fn();
    render(<UploadZone onFile={onFile} />);
    const file = pngFile();
    await userEvent.upload(screen.getByTestId("file-input"), file);
    expect(onFile).toHaveBeenCalledWith(file);
    fireEvent.drop(screen.getByTestId("upload-zone"), { dataTransfer: { files: [file] } });
    expect(onFile).toHaveBeenCalledTimes(2);
  });
});

describe("ParamsPanel", () => {
  it("modifica parámetros reales y los restablece al perfil", async () => {
    const spy = vi.fn();
    render(<Harness spy={spy} />);
    const colors = screen.getByTestId("input-max_colors");
    fireEvent.change(colors, { target: { value: "24" } });
    expect(spy).toHaveBeenLastCalledWith(expect.objectContaining({ max_colors: 24 }));
    fireEvent.change(colors, { target: { value: "9999" } });
    expect(spy).toHaveBeenLastCalledWith(expect.objectContaining({ max_colors: 256 })); // acotado al rango
    await userEvent.click(screen.getByRole("radio", { name: "Integral" }));
    expect(spy).toHaveBeenLastCalledWith(expect.objectContaining({ strategy: "integral" }));
    await userEvent.click(screen.getByTestId("switch-preserve_alpha"));
    expect(spy).toHaveBeenLastCalledWith(expect.objectContaining({ preserve_alpha: false }));
    await userEvent.click(screen.getByRole("button", { name: /Restablecer/ }));
    expect(spy).toHaveBeenLastCalledWith(DEFAULT_PARAMS);
  });

  it("muestra incompatibilidades", async () => {
    render(<Harness spy={vi.fn()} />);
    await userEvent.click(screen.getByRole("radio", { name: "Por capas" }));
    fireEvent.change(screen.getByTestId("input-outline_emphasis"), { target: { value: "0" } });
    expect(screen.getByTestId("param-problems")).toHaveTextContent("capas");
  });

  it("los ajustes avanzados pasan de «perfil» a override explícito", async () => {
    const spy = vi.fn();
    render(<Harness spy={spy} />);
    await userEvent.click(screen.getByTestId("advanced-toggle"));
    await userEvent.click(screen.getByTestId("auto-filter_speckle"));
    expect(spy).toHaveBeenLastCalledWith(expect.objectContaining({ advanced: expect.objectContaining({ filter_speckle: 0 }) }));
  });
});

describe("MessagesPanel", () => {
  it("distingue errores recuperables y fatales y muestra detalles de validación", () => {
    const { rerender } = render(<MessagesPanel error={{ fatal: false, code: "incompatible_params", message: "Parámetros no válidos.",
      details: { errors: [{ loc: ["max_colors"], msg: "Input should be greater than or equal to 2" }] } }} />);
    expect(screen.getByTestId("error-box")).toHaveTextContent("No se pudo procesar");
    expect(screen.getByTestId("error-box")).toHaveTextContent("max_colors: Input should be");
    rerender(<MessagesPanel error={{ fatal: true, code: "backend_unreachable", message: "No responde" }} />);
    expect(screen.getByTestId("error-box")).toHaveTextContent("Error del sistema");
  });
});

describe("geometría del visor", () => {
  it("ajusta a pantalla centrando y hace zoom alrededor del cursor", () => {
    const v = fitView(800, 600, 400, 400);
    expect(v.scale).toBeCloseTo(1.425);
    expect(v.x).toBeCloseTo((800 - 400 * v.scale) / 2);
    const z = zoomAt({ scale: 1, x: 0, y: 0 }, 2, 100, 50);
    expect(z).toEqual({ scale: 2, x: -100, y: -50 }); // el punto bajo el cursor no se mueve
  });
});
