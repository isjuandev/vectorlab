import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const SAMPLES = path.resolve(__dirname, "../../samples/synthetic");
const SHOTS = path.resolve(__dirname, "../../output/e2e-screenshots");

async function ready(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("backend-status")).toContainText("vtracer");
}

test("flujo completo: carga, parámetros, conversión, comparación y descarga", async ({ page }) => {
  await ready(page);
  await page.getByTestId("file-input").setInputFiles(path.join(SAMPLES, "char_white_512.png"));
  await expect(page.getByTestId("file-info")).toContainText("512×512");
  await expect(page.getByTestId("phase")).toHaveText("Archivo cargado");

  // Los controles envían sus valores reales al backend.
  await page.getByTestId("input-max_colors").fill("32");
  await page.getByTestId("input-outline_emphasis").fill("70");
  const created = page.waitForResponse((r) => r.url().endsWith("/api/v1/jobs") && r.request().method() === "POST");
  await page.getByTestId("run").click();
  const job = await (await created).json();
  expect(job.requested_params.max_colors).toBe(32);
  expect(job.requested_params.outline_emphasis).toBe(70);

  await expect(page.getByTestId("phase")).toHaveText("Resultado disponible");
  await expect(page.getByTestId("metrics-panel")).toBeVisible();
  const ssim = Number(await page.getByTestId("metric-ssim").textContent());
  expect(ssim).toBeGreaterThan(0.9);
  await expect(page.getByAltText("Resultado SVG")).toHaveAttribute("src", /download\.svg\?disposition=inline/);
  await page.screenshot({ path: path.join(SHOTS, "01-resultado-deslizador.png") });

  await page.getByRole("radio", { name: "Dividida" }).click();
  await page.getByRole("button", { name: "Acercar" }).click();
  await page.getByRole("button", { name: "Acercar" }).click();
  await page.screenshot({ path: path.join(SHOTS, "02-dividida-zoom.png") });
  await page.getByRole("button", { name: "1:1" }).click();
  await expect(page.getByTestId("zoom-level")).toHaveText("100%");

  const [svgDl] = await Promise.all([page.waitForEvent("download"), page.getByTestId("download-svg").click()]);
  expect(svgDl.suggestedFilename()).toMatch(/^vectorlab-[0-9a-f]{8}\.svg$/);
  const svg = readFileSync((await svgDl.path())!, "utf8");
  expect(svg).toContain("<svg");
  expect(svg).toContain("<path");
  expect(svg).not.toContain("<image");
  expect(svg).not.toContain("base64");

  const [pngDl] = await Promise.all([page.waitForEvent("download"), page.getByTestId("download-png").click()]);
  const png = readFileSync((await pngDl.path())!);
  expect(png.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a");

  // Reprocesar sin volver a cargar el archivo.
  await page.getByTestId("input-max_colors").fill("8");
  const second = page.waitForResponse((r) => r.url().endsWith("/api/v1/jobs") && r.request().method() === "POST");
  await page.getByTestId("run").click();
  expect((await (await second).json()).requested_params.max_colors).toBe(8);
  await expect(page.getByTestId("phase")).toHaveText("Resultado disponible");

  // Los parámetros persisten durante la sesión.
  await page.reload();
  await expect(page.getByTestId("input-max_colors")).toHaveValue("8");
});

test("transparencia y WebP", async ({ page }) => {
  await ready(page);
  await page.getByTestId("file-input").setInputFiles(path.join(SAMPLES, "char_transparent_512_lossless.webp"));
  await page.getByTestId("run").click();
  await expect(page.getByTestId("phase")).toHaveText("Resultado disponible");
  const iou = await page.getByTestId("metric-alpha_iou").textContent();
  expect(parseFloat(iou ?? "0")).toBeGreaterThan(95);
  await expect(page.getByTestId("warnings")).toContainText("alfa parcial");
  await page.screenshot({ path: path.join(SHOTS, "03-transparencia.png") });
});

test("JPEG con pérdida", async ({ page }) => {
  await ready(page);
  await page.getByTestId("file-input").setInputFiles(path.join(SAMPLES, "char_white_512_q75.jpg"));
  await page.getByTestId("run").click();
  await expect(page.getByTestId("phase")).toHaveText("Resultado disponible");
  await expect(page.getByTestId("messages-panel")).toContainText("mean-shift");
});

test("archivo no válido: error recuperable sin llamar al backend", async ({ page }) => {
  await ready(page);
  await page.getByTestId("file-input").setInputFiles({ name: "trampa.png", mimeType: "image/png", buffer: Buffer.from("no soy una imagen") });
  await expect(page.getByTestId("error-box")).toContainText("Formato no admitido");
  await expect(page.getByTestId("run")).toBeDisabled();
});

test("configuración incompatible bloquea el envío", async ({ page }) => {
  await ready(page);
  await page.getByTestId("file-input").setInputFiles(path.join(SAMPLES, "char_white_200.png"));
  await page.getByRole("radio", { name: "Por capas" }).click();
  await page.getByTestId("input-outline_emphasis").fill("0");
  await expect(page.getByTestId("param-problems")).toContainText("capas");
  await expect(page.getByTestId("run")).toBeDisabled();
  await page.getByRole("button", { name: "Restablecer" }).click();
  await expect(page.getByTestId("run")).toBeEnabled();
});

test("cancelación de un trabajo en curso", async ({ page }) => {
  await ready(page);
  await page.getByTestId("file-input").setInputFiles(path.join(SAMPLES, "char_white_1600.png"));
  await page.getByRole("radio", { name: "Auto" }).nth(1).click(); // curvas: auto
  await page.getByTestId("input-candidate_budget").fill("4");
  await page.getByTestId("run").click();
  await page.getByRole("button", { name: "Cancelar" }).click();
  await expect(page.getByTestId("phase")).toHaveText("Cancelado");
});

const REAL_DIR = path.resolve(__dirname, "../../samples/real");
const realFiles = (() => {
  try {
    return readdirSync(REAL_DIR).filter((f) => /\.(png|jpe?g|webp)$/i.test(f));
  } catch {
    return [];
  }
})();

test("imágenes reales de samples/real (se omite si no hay)", async ({ page }) => {
  test.skip(realFiles.length === 0, "samples/real está vacío");
  for (const f of realFiles) {
    await ready(page);
    await page.getByTestId("file-input").setInputFiles(path.join(REAL_DIR, f));
    await page.getByTestId("run").click();
    await expect(page.getByTestId("phase")).toHaveText("Resultado disponible");
    const ssim = Number(await page.getByTestId("metric-ssim").textContent());
    expect(ssim).toBeGreaterThan(0.9);
    // El ruido de codificación del alfa no se presenta como advertencia.
    await expect(page.getByTestId("warnings")).not.toContainText("ruido de codificación");
    await page.screenshot({ path: path.join(SHOTS, `real-${f.replace(/\W+/g, "_")}.png`) });
  }
});
