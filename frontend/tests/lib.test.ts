import { describe, expect, it, vi } from "vitest";

import { checkDimensions, checkSize, FALLBACK_LIMITS, sniffFormat, validateFile } from "@/lib/file-validation";
import { DEFAULT_PARAMS, incompatibilities, loadParams, paramsSchema, saveParams, STORAGE_KEY } from "@/lib/params";

import { pngFile } from "./fixtures";

describe("sniffFormat", () => {
  it("reconoce las firmas reales", () => {
    expect(sniffFormat(new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))).toBe("png");
    expect(sniffFormat(new Uint8Array([0xff, 0xd8, 0xff, 0xe0]))).toBe("jpeg");
    const webp = new TextEncoder().encode("RIFF\0\0\0\0WEBPVP8 ");
    expect(sniffFormat(webp)).toBe("webp");
    expect(sniffFormat(new TextEncoder().encode("GIF89a......"))).toBeNull();
  });
});

describe("límites", () => {
  it("rechaza tamaño y dimensiones fuera de rango", () => {
    expect(checkSize(0, FALLBACK_LIMITS)).toMatch(/vacío/);
    expect(checkSize(FALLBACK_LIMITS.max_upload_bytes + 1, FALLBACK_LIMITS)).toMatch(/máximo/);
    expect(checkSize(100, FALLBACK_LIMITS)).toBeNull();
    expect(checkDimensions(4, 100, FALLBACK_LIMITS)).toMatch(/pequeña/);
    expect(checkDimensions(7000, 100, FALLBACK_LIMITS)).toMatch(/máximo/);
    expect(checkDimensions(5000, 5000, FALLBACK_LIMITS)).toMatch(/píxeles/);
    expect(checkDimensions(512, 512, FALLBACK_LIMITS)).toBeNull();
  });

  it("validateFile comprueba contenido y dimensiones", async () => {
    const ok = await validateFile(pngFile(), FALLBACK_LIMITS);
    expect(ok).toMatchObject({ format: "png", width: 100, height: 80 });
    const fake = new File(["hola"], "foto.png", { type: "image/png" });
    await expect(validateFile(fake, FALLBACK_LIMITS)).rejects.toThrow(/Formato no admitido/);
    vi.mocked(URL.createObjectURL).mockReturnValueOnce("blob:broken");
    await expect(validateFile(pngFile(), FALLBACK_LIMITS)).rejects.toThrow(/decodificar/);
    await expect(validateFile(pngFile(), { ...FALLBACK_LIMITS, max_dimension: 50 })).rejects.toThrow(/máximo/);
  });
});

describe("parámetros", () => {
  it("los valores por defecto son válidos y corresponden al perfil", () => {
    expect(paramsSchema.safeParse(DEFAULT_PARAMS).success).toBe(true);
    expect(DEFAULT_PARAMS).toMatchObject({ max_colors: 64, detail_preservation: 100, outline_emphasis: 80, preserve_alpha: true, visual_validation: true });
  });

  it("detecta configuraciones incompatibles (mismas reglas que el backend)", () => {
    expect(incompatibilities({ ...DEFAULT_PARAMS, strategy: "layered", outline_emphasis: 0 })).toHaveLength(1);
    expect(incompatibilities({ ...DEFAULT_PARAMS, background_mode: "remove_uniform", preserve_alpha: false })).toHaveLength(1);
    expect(incompatibilities({ ...DEFAULT_PARAMS, visual_validation: false })).toHaveLength(1);
    expect(incompatibilities({ ...DEFAULT_PARAMS, visual_validation: false, strategy: "integral" })).toHaveLength(0);
    expect(paramsSchema.safeParse({ ...DEFAULT_PARAMS, max_colors: 1 }).success).toBe(false);
  });

  it("persiste en sessionStorage e ignora datos corruptos", () => {
    saveParams(sessionStorage, { ...DEFAULT_PARAMS, max_colors: 12 });
    expect(loadParams(sessionStorage).max_colors).toBe(12);
    sessionStorage.setItem(STORAGE_KEY, "{roto");
    expect(loadParams(sessionStorage)).toEqual(DEFAULT_PARAMS);
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ ...DEFAULT_PARAMS, max_colors: 9999 }));
    expect(loadParams(sessionStorage)).toEqual(DEFAULT_PARAMS);
  });

  it("conserva parámetros guardados antes de existir un control nuevo", () => {
    const older: Partial<typeof DEFAULT_PARAMS> = { ...DEFAULT_PARAMS, max_colors: 20 };
    delete older.supersample;
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(older));
    const loaded = loadParams(sessionStorage);
    expect(loaded.max_colors).toBe(20);
    expect(loaded.supersample).toBe(DEFAULT_PARAMS.supersample);
    expect(paramsSchema.safeParse({ ...DEFAULT_PARAMS, supersample: 5 }).success).toBe(false);
  });
});
