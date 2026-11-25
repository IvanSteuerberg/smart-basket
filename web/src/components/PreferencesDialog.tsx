import { useEffect, useId, useRef, useState, type MouseEvent } from "react";
import { useTheme, type ThemePreference } from "../theme";
import { DIETARY_LABELS } from "../texts";

export const DIETARY_RULES = ["sin_gluten", "sin_lactosa"] as const;
export const PREFERENCES_DIETARY_NOTICE =
  "Comprueba siempre la etiqueta del fabricante. El filtro se basa en el nombre publicado por el supermercado.";
export const IMPORT_OK = "Preferencias importadas.";
export const IMPORT_ERROR = "No se ha podido importar: el archivo no es válido.";
export const EXPORT_OK = "Preferencias exportadas.";

export const THEME_CHOICES: { value: ThemePreference; label: string }[] = [
  { value: "system", label: "Sistema" },
  { value: "light", label: "Claro" },
  { value: "dark", label: "Oscuro" },
];

export interface ActionStatus {
  kind: "ok" | "error";
  message: string;
}

interface RectLike {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

/** True when a click landed outside the dialog box, i.e. on its backdrop (Safari fallback). */
export function isOutsideRect(rect: RectLike, x: number, y: number): boolean {
  return x < rect.left || x > rect.right || y < rect.top || y > rect.bottom;
}

/** Runs an import and turns its success or failure into the message the dialog shows. */
export async function runImport(
  text: string,
  onImport: (json: string) => void | Promise<void>,
): Promise<ActionStatus> {
  try {
    await onImport(text);
    return { kind: "ok", message: IMPORT_OK };
  } catch {
    return { kind: "error", message: IMPORT_ERROR };
  }
}

const BUTTON =
  "inline-flex min-h-11 items-center justify-center rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] px-4 text-[0.9375rem] font-semibold text-[var(--ink-primary)] transition-colors hover:border-[var(--accent-primary)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-primary)]";

export interface PreferencesDialogProps {
  open: boolean;
  onClose: () => void;
  /** Active dietary rule keys of the browser profile (`sin_gluten`, `sin_lactosa`). */
  dietaryRules: string[];
  onToggleDietaryRule: (rule: string) => void;
  onExportProfile: () => void;
  onImportProfile: (json: string) => void | Promise<void>;
}

/** Native modal dialog with appearance, dietary preferences and the local data backup. */
export function PreferencesDialog({
  open,
  onClose,
  dietaryRules,
  onToggleDietaryRule,
  onExportProfile,
  onImportProfile,
}: PreferencesDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const titleId = useId();
  const { preference, setPreference } = useTheme();
  const [status, setStatus] = useState<ActionStatus | null>(null);

  useEffect(() => {
    // React 19 types do not know `closedby` yet; Chromium closes on outside click with it.
    dialogRef.current?.setAttribute("closedby", "any");
  }, []);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
      setStatus(null);
    } else if (!open && dialog.open) {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
    }
  }, [open]);

  function handleBackdropClick(event: MouseEvent<HTMLDialogElement>) {
    // Only clicks on the dialog element itself can be backdrop clicks; children are inside.
    if (event.target !== event.currentTarget) return;
    if (isOutsideRect(event.currentTarget.getBoundingClientRect(), event.clientX, event.clientY)) {
      onCloseRef.current();
    }
  }

  async function handleFile(file: File | undefined) {
    if (!file) return;
    setStatus(await runImport(await file.text(), onImportProfile));
  }

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onCloseRef.current();
      }}
      onClose={() => onCloseRef.current()}
      onClick={handleBackdropClick}
      className="m-auto max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-md overflow-y-auto rounded-2xl border border-[var(--border-subtle)] bg-[var(--surface-card)] p-0 text-[var(--ink-primary)] backdrop:bg-black/55"
    >
      <div className="flex flex-col gap-5 p-5">
        <div className="flex items-center justify-between gap-3">
          <h2 id={titleId} className="text-[1.375rem] font-bold tracking-tight">
            Ajustes
          </h2>
          <button type="button" onClick={onClose} autoFocus className={BUTTON}>
            Cerrar
          </button>
        </div>

        <section className="flex flex-col gap-3 border-t border-[var(--border-subtle)] pt-5">
          <h3 className="text-[0.9375rem] font-bold">Apariencia</h3>
          <div
            role="group"
            aria-label="Tema de color"
            className="inline-flex self-start rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-elevated)] p-0.5"
          >
            {THEME_CHOICES.map((choice) => {
              const selected = preference === choice.value;
              return (
                <button
                  key={choice.value}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => setPreference(choice.value)}
                  className={`min-h-11 rounded-[0.625rem] px-4 text-[0.9375rem] font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-primary)] ${
                    selected
                      ? "bg-[var(--accent-primary)] text-[var(--accent-on-primary)]"
                      : "text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]"
                  }`}
                >
                  {choice.label}
                </button>
              );
            })}
          </div>
        </section>

        <section className="flex flex-col gap-2 border-t border-[var(--border-subtle)] pt-5">
          <h3 className="text-[0.9375rem] font-bold">Preferencias alimentarias</h3>
          {DIETARY_RULES.map((rule) => (
            <label key={rule} className="flex min-h-11 cursor-pointer items-center gap-3 text-[0.9375rem]">
              <input
                type="checkbox"
                checked={dietaryRules.includes(rule)}
                onChange={() => onToggleDietaryRule(rule)}
                className="h-5 w-5 shrink-0"
              />
              {DIETARY_LABELS[rule]}
            </label>
          ))}
          <p className="text-[0.8125rem] text-[var(--ink-secondary)]">{PREFERENCES_DIETARY_NOTICE}</p>
        </section>

        <section className="flex flex-col gap-3 border-t border-[var(--border-subtle)] pt-5">
          <h3 className="text-[0.9375rem] font-bold">Tus datos en este navegador</h3>
          <p className="text-[0.8125rem] text-[var(--ink-secondary)]">
            Tus preferencias se guardan solo aquí. Si borras los datos del navegador, se pierden.
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => {
                onExportProfile();
                setStatus({ kind: "ok", message: EXPORT_OK });
              }}
              className={BUTTON}
            >
              Exportar preferencias (JSON)
            </button>
            <button type="button" onClick={() => fileRef.current?.click()} className={BUTTON}>
              Importar preferencias (JSON)
            </button>
            <input
              ref={fileRef}
              type="file"
              accept="application/json,.json"
              hidden
              tabIndex={-1}
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                void handleFile(file);
              }}
            />
          </div>
          {status && (
            <p
              role={status.kind === "error" ? "alert" : "status"}
              className={`text-[0.8125rem] font-semibold ${
                status.kind === "error" ? "text-[var(--danger-fg)]" : "text-[var(--savings-fg)]"
              }`}
            >
              {status.message}
            </p>
          )}
        </section>
      </div>
    </dialog>
  );
}
