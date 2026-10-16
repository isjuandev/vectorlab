"use client";

import { ImageUp } from "lucide-react";
import { useRef, useState } from "react";

import { cn } from "@/lib/utils";

interface Props {
  disabled?: boolean;
  onFile: (file: File) => void;
  compact?: boolean;
}

export function UploadZone({ disabled, onFile, compact }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  const pick = (files: FileList | null) => {
    const f = files?.[0];
    if (f) onFile(f);
  };

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label="Cargar imagen (PNG, JPEG o WebP)"
      aria-disabled={disabled}
      data-testid="upload-zone"
      onClick={() => !disabled && input.current?.click()}
      onKeyDown={(e) => {
        if (!disabled && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          input.current?.click();
        }
      }}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        if (!disabled) pick(e.dataTransfer.files);
      }}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed text-center transition-colors",
        "border-border bg-muted/30 hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
        compact ? "px-3 py-3" : "px-6 py-10",
        over && "border-primary bg-primary/5",
        disabled && "pointer-events-none opacity-50",
      )}
    >
      <ImageUp className={cn("text-muted-foreground", compact ? "size-5" : "size-8")} aria-hidden />
      <div className="text-sm">
        <span className="font-medium">{compact ? "Cambiar imagen" : "Arrastra una imagen o haz clic"}</span>
        {!compact && <p className="mt-1 text-xs text-muted-foreground">PNG, JPEG o WebP · se valida el contenido real</p>}
      </div>
      <input
        ref={input}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="sr-only"
        data-testid="file-input"
        onChange={(e) => {
          pick(e.target.files);
          e.target.value = "";
        }}
      />
    </div>
  );
}
