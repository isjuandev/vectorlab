// Validación previa en el navegador. Es solo una ayuda: el backend vuelve a validar todo.

export type SniffedFormat = "png" | "jpeg" | "webp";

export interface FileLimits {
  max_upload_bytes: number;
  max_dimension: number;
  min_dimension: number;
  max_pixels: number;
}

export const FALLBACK_LIMITS: FileLimits = {
  max_upload_bytes: 25 * 1024 * 1024,
  max_dimension: 6000,
  min_dimension: 8,
  max_pixels: 24_000_000,
};

export function sniffFormat(head: Uint8Array): SniffedFormat | null {
  const png = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
  if (png.every((b, i) => head[i] === b)) return "png";
  if (head[0] === 0xff && head[1] === 0xd8 && head[2] === 0xff) return "jpeg";
  const ascii = (from: number, to: number) => String.fromCharCode(...head.slice(from, to));
  if (head.length >= 12 && ascii(0, 4) === "RIFF" && ascii(8, 12) === "WEBP") return "webp";
  return null;
}

export async function readHead(file: Blob, n = 16): Promise<Uint8Array> {
  return new Uint8Array(await file.slice(0, n).arrayBuffer());
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function checkSize(bytes: number, limits: FileLimits): string | null {
  if (bytes === 0) return "El archivo está vacío.";
  if (bytes > limits.max_upload_bytes)
    return `El archivo pesa ${formatBytes(bytes)}; el máximo es ${formatBytes(limits.max_upload_bytes)}.`;
  return null;
}

export function checkDimensions(width: number, height: number, limits: FileLimits): string | null {
  if (width < limits.min_dimension || height < limits.min_dimension)
    return `Imagen demasiado pequeña (${width}×${height}); mínimo ${limits.min_dimension}px por lado.`;
  if (Math.max(width, height) > limits.max_dimension)
    return `Dimensión ${Math.max(width, height)}px supera el máximo de ${limits.max_dimension}px.`;
  if (width * height > limits.max_pixels)
    return `La imagen tiene ${(width * height).toLocaleString("es")} píxeles; el máximo es ${limits.max_pixels.toLocaleString("es")}.`;
  return null;
}

export interface ValidatedFile {
  file: File;
  format: SniffedFormat;
  width: number;
  height: number;
  url: string; // object URL reutilizado por el visor (no se vuelve a leer el archivo)
}

export function loadDimensions(url: string): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight });
    img.onerror = () => reject(new Error("El navegador no pudo decodificar la imagen (¿archivo dañado?)."));
    img.src = url;
  });
}

export async function validateFile(file: File, limits: FileLimits): Promise<ValidatedFile> {
  const sizeError = checkSize(file.size, limits);
  if (sizeError) throw new Error(sizeError);
  const format = sniffFormat(await readHead(file));
  if (!format) throw new Error("Formato no admitido: solo PNG, JPEG y WebP (se comprueba el contenido, no la extensión).");
  const url = URL.createObjectURL(file);
  try {
    const { width, height } = await loadDimensions(url);
    const dimError = checkDimensions(width, height, limits);
    if (dimError) throw new Error(dimError);
    return { file, format, width, height, url };
  } catch (e) {
    URL.revokeObjectURL(url);
    throw e;
  }
}
