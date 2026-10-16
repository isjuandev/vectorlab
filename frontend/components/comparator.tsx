"use client";

import { Columns2, ExternalLink, Maximize, Minus, Plus, SplitSquareHorizontal, Square } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type PointerEvent, type WheelEvent } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { LostComponent } from "@/types/api";

export type CompareMode = "split" | "slider" | "result" | "original";
type Backdrop = "checker" | "white" | "black" | "custom";

interface View { scale: number; x: number; y: number }

interface Props {
  originalUrl: string;
  resultUrl: string | null;
  width: number;
  height: number;
  losses?: LostComponent[];
  openSvgUrl?: string | null;
}

const MIN_SCALE = 0.05;
const MAX_SCALE = 16;
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

export function fitView(cw: number, ch: number, w: number, h: number): View {
  const scale = clamp(Math.min(cw / w, ch / h) * 0.95, MIN_SCALE, MAX_SCALE);
  return { scale, x: (cw - w * scale) / 2, y: (ch - h * scale) / 2 };
}

export function zoomAt(view: View, factor: number, px: number, py: number): View {
  const scale = clamp(view.scale * factor, MIN_SCALE, MAX_SCALE);
  const k = scale / view.scale;
  return { scale, x: px - (px - view.x) * k, y: py - (py - view.y) * k };
}

function backdropStyle(b: Backdrop, custom: string): CSSProperties {
  if (b === "white") return { background: "#ffffff" };
  if (b === "black") return { background: "#000000" };
  if (b === "custom") return { background: custom };
  return {
    backgroundColor: "#ffffff",
    backgroundImage: "conic-gradient(#d4d4d4 25%, transparent 0 50%, #d4d4d4 0 75%, transparent 0)",
    backgroundSize: "16px 16px",
  };
}

function Layer({ src, view, w, h, alt, pixelated }: { src: string; view: View; w: number; h: number; alt: string; pixelated?: boolean }) {
  // Se escala el tamaño de layout (no transform: scale) para que el SVG se rasterice nítido a cualquier zoom.
  return (
    // eslint-disable-next-line @next/next/no-img-element -- object URLs y SVG del backend local
    <img
      src={src}
      alt={alt}
      draggable={false}
      className="pointer-events-none absolute top-0 left-0 max-w-none select-none"
      style={{
        width: w * view.scale,
        height: h * view.scale,
        transform: `translate(${view.x}px, ${view.y}px)`,
        imageRendering: pixelated && view.scale >= 2 ? "pixelated" : "auto",
      }}
    />
  );
}

function LossOverlay({ losses, view }: { losses: LostComponent[]; view: View }) {
  return (
    <div className="pointer-events-none absolute top-0 left-0" style={{ transform: `translate(${view.x}px, ${view.y}px)` }}>
      {losses.map((l, i) => (
        <div
          key={i}
          title={`Posible pérdida: ${l.color}, ${l.area_px}px`}
          className="absolute border-2 border-fuchsia-500 bg-fuchsia-500/15"
          style={{ left: l.bbox[0] * view.scale - 2, top: l.bbox[1] * view.scale - 2, width: l.bbox[2] * view.scale + 4, height: l.bbox[3] * view.scale + 4 }}
        />
      ))}
    </div>
  );
}

function useViewport(onSize: (w: number, h: number) => void) {
  const ref = useRef<HTMLDivElement>(null);
  const cb = useRef(onSize);
  useEffect(() => {
    cb.current = onSize;
  });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => cb.current(entry.contentRect.width, entry.contentRect.height));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return ref;
}

export function Comparator({ originalUrl, resultUrl, width, height, losses = [], openSvgUrl }: Props) {
  const [mode, setMode] = useState<CompareMode>("slider");
  const [view, setView] = useState<View>({ scale: 1, x: 0, y: 0 });
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [reveal, setReveal] = useState(50);
  const [backdrop, setBackdrop] = useState<Backdrop>("checker");
  const [custom, setCustom] = useState("#7c3aed");
  const [showLosses, setShowLosses] = useState(false);
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null);
  const fitted = useRef<string>("");

  const effectiveMode: CompareMode = resultUrl ? mode : "original";
  const paneWidth = effectiveMode === "split" ? size.w / 2 : size.w;

  const fit = useCallback(() => {
    if (paneWidth > 0 && size.h > 0) setView(fitView(paneWidth, size.h, width, height));
  }, [paneWidth, size.h, width, height]);

  const actualSize = useCallback(() => {
    setView({ scale: 1, x: (paneWidth - width) / 2, y: (size.h - height) / 2 });
  }, [paneWidth, size.h, width, height]);

  // Ajuste automático al cambiar de imagen o de distribución.
  useEffect(() => {
    const key = `${originalUrl}|${width}x${height}|${effectiveMode === "split"}|${Math.round(paneWidth)}x${Math.round(size.h)}`;
    if (paneWidth > 0 && fitted.current !== key) {
      fitted.current = key;
      fit();
    }
  }, [originalUrl, width, height, effectiveMode, paneWidth, size.h, fit]);

  const container = useViewport((w, h) => setSize({ w, h }));

  const onWheel = (e: WheelEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const factor = Math.exp(-e.deltaY * 0.0015);
    setView((v) => zoomAt(v, factor, e.clientX - rect.left, e.clientY - rect.top));
  };
  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (d) setView((v) => ({ ...v, x: d.vx + e.clientX - d.x, y: d.vy + e.clientY - d.y }));
  };
  const onPointerUp = () => {
    drag.current = null;
  };
  const zoomCenter = (factor: number) => setView((v) => zoomAt(v, factor, paneWidth / 2, size.h / 2));

  const paneHandlers = { onWheel, onPointerDown, onPointerMove, onPointerUp, onPointerCancel: onPointerUp };
  const bg = backdropStyle(backdrop, custom);
  const overlay = showLosses && losses.length > 0 ? <LossOverlay losses={losses} view={view} /> : null;

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="comparator">
      <div className="flex flex-wrap items-center gap-1 border-b px-2 py-1.5">
        <div role="radiogroup" aria-label="Modo de comparación" className="flex gap-0.5 rounded-md bg-muted p-0.5">
          {([
            ["slider", "Deslizador", SplitSquareHorizontal],
            ["split", "Dividida", Columns2],
            ["original", "Original", Square],
            ["result", "Resultado", Square],
          ] as const).map(([m, label, Icon]) => (
            <button key={m} type="button" role="radio" aria-checked={effectiveMode === m} disabled={!resultUrl && m !== "original"}
              onClick={() => setMode(m)}
              className={cn("flex items-center gap-1 rounded px-2 py-1 text-xs disabled:opacity-40",
                effectiveMode === m ? "bg-background shadow-sm" : "text-muted-foreground hover:text-foreground")}>
              <Icon className="size-3.5" aria-hidden />{label}
            </button>
          ))}
        </div>
        <div className="mx-1 h-5 w-px bg-border" />
        <Button variant="ghost" size="icon-sm" aria-label="Alejar" onClick={() => zoomCenter(1 / 1.25)}><Minus /></Button>
        <span className="w-12 text-center font-mono text-xs tabular-nums" data-testid="zoom-level">{Math.round(view.scale * 100)}%</span>
        <Button variant="ghost" size="icon-sm" aria-label="Acercar" onClick={() => zoomCenter(1.25)}><Plus /></Button>
        <Button variant="ghost" size="sm" onClick={fit}><Maximize className="size-3.5" />Ajustar</Button>
        <Button variant="ghost" size="sm" onClick={actualSize}>1:1</Button>
        <div className="mx-1 h-5 w-px bg-border" />
        <label className="flex items-center gap-1 text-xs text-muted-foreground">
          Fondo
          <select value={backdrop} onChange={(e) => setBackdrop(e.target.value as Backdrop)}
            className="h-7 rounded-md border border-input bg-transparent px-1 text-xs" aria-label="Fondo de transparencia">
            <option value="checker">Cuadrícula</option>
            <option value="white">Blanco</option>
            <option value="black">Negro</option>
            <option value="custom">Personalizado</option>
          </select>
        </label>
        {backdrop === "custom" && (
          <input type="color" value={custom} onChange={(e) => setCustom(e.target.value)} aria-label="Color de fondo" className="h-7 w-8 rounded" />
        )}
        {losses.length > 0 && (
          <label className="ml-1 flex items-center gap-1 text-xs text-muted-foreground">
            <input type="checkbox" checked={showLosses} onChange={(e) => setShowLosses(e.target.checked)} />
            Marcar pérdidas ({losses.length})
          </label>
        )}
        {openSvgUrl && (
          <a href={openSvgUrl} target="_blank" rel="noreferrer" className="ml-auto flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
            <ExternalLink className="size-3.5" />Abrir SVG
          </a>
        )}
      </div>

      <div ref={container} className="relative min-h-0 flex-1 overflow-hidden">
        {effectiveMode === "split" && resultUrl ? (
          <div className="absolute inset-0 grid grid-cols-2">
            {[["Original", originalUrl, true], ["SVG", resultUrl, false]].map(([label, src, pix]) => (
              <div key={label as string} className="relative cursor-grab overflow-hidden border-r last:border-r-0 active:cursor-grabbing" style={bg} {...paneHandlers}>
                <Layer src={src as string} view={view} w={width} h={height} alt={label as string} pixelated={pix as boolean} />
                {!pix && overlay}
                <span className="absolute top-2 left-2 rounded bg-black/60 px-1.5 py-0.5 text-[11px] text-white">{label as string}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="absolute inset-0 cursor-grab overflow-hidden active:cursor-grabbing" style={bg} {...paneHandlers}>
            {effectiveMode !== "result" && <Layer src={originalUrl} view={view} w={width} h={height} alt="Original" pixelated />}
            {resultUrl && effectiveMode !== "original" && (
              <div className="absolute inset-0" style={effectiveMode === "slider" ? { clipPath: `inset(0 ${100 - reveal}% 0 0)`, ...bg } : bg}>
                <Layer src={resultUrl} view={view} w={width} h={height} alt="Resultado SVG" />
                {overlay}
              </div>
            )}
            {effectiveMode === "slider" && resultUrl && (
              <>
                <div className="pointer-events-none absolute top-0 bottom-0 w-0.5 bg-fuchsia-500" style={{ left: `${reveal}%` }} />
                <span className="absolute top-2 left-2 rounded bg-black/60 px-1.5 py-0.5 text-[11px] text-white">SVG</span>
                <span className="absolute top-2 right-2 rounded bg-black/60 px-1.5 py-0.5 text-[11px] text-white">Original</span>
              </>
            )}
          </div>
        )}
      </div>
      {effectiveMode === "slider" && resultUrl && (
        <div className="flex items-center gap-2 border-t px-3 py-1.5">
          <span className="text-xs text-muted-foreground">SVG</span>
          <input type="range" min={0} max={100} value={reveal} onChange={(e) => setReveal(Number(e.target.value))}
            aria-label="Revelar resultado" className="flex-1 accent-fuchsia-500" />
          <span className="text-xs text-muted-foreground">Original</span>
        </div>
      )}
    </div>
  );
}
