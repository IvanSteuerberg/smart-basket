import {
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
  type MouseEvent,
  type RefObject,
} from "react";
import type { SavedList } from "../storage";
import {
  SAVED_LISTS_EMPTY,
  SAVED_LISTS_MINE_TITLE,
  SAVED_LISTS_NAME_LABEL,
  SAVED_LISTS_NAME_REPLACES,
  SAVED_LISTS_NAME_REQUIRED,
  SAVED_LISTS_NAME_TAKEN,
  SAVED_LISTS_NOTHING_TO_SAVE,
  SAVED_LISTS_SAVE_TITLE,
  SAVED_LISTS_TITLE,
} from "../texts";
import { isOutsideRect } from "./PreferencesDialog";

export interface ModalDialogBindings {
  ref: RefObject<HTMLDialogElement | null>;
  onCancel: (event: { preventDefault: () => void }) => void;
  onClose: () => void;
  onClick: (event: MouseEvent<HTMLDialogElement>) => void;
}

/**
 * Wires a native `<dialog>` to an `open` flag: `showModal()` / `close()`, light dismiss with
 * `closedby="any"` and a backdrop-click fallback for Safari. Spread the result on the dialog.
 */
export function useModalDialog(open: boolean, onClose: () => void): ModalDialogBindings {
  const ref = useRef<HTMLDialogElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const openRef = useRef(open);
  openRef.current = open;

  useEffect(() => {
    // React 19 types do not know `closedby` yet; Chromium closes on outside click with it.
    ref.current?.setAttribute("closedby", "any");
  }, []);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    } else if (!open && dialog.open) {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
    }
  }, [open]);

  return {
    ref,
    onCancel: (event) => {
      event.preventDefault();
      onCloseRef.current();
    },
    onClose: () => {
      // A close the parent asked for must not be reported back as a new request.
      if (openRef.current) onCloseRef.current();
    },
    onClick: (event) => {
      // Only clicks on the dialog element itself can be backdrop clicks; children are inside.
      if (event.target !== event.currentTarget) return;
      if (isOutsideRect(event.currentTarget.getBoundingClientRect(), event.clientX, event.clientY)) {
        onCloseRef.current();
      }
    },
  };
}

/** True when another list (not `excludeId`) already uses the name, ignoring case. */
export function sameNameExists(name: string, lists: SavedList[], excludeId: string | null): boolean {
  const wanted = name.trim().toLowerCase();
  if (wanted === "") return false;
  return lists.some((list) => list.id !== excludeId && list.name.trim().toLowerCase() === wanted);
}

/** «1 producto», «3 productos». */
export function productCountLabel(count: number): string {
  return `${count} ${count === 1 ? "producto" : "productos"}`;
}

const BUTTON =
  "inline-flex min-h-11 items-center justify-center rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] px-4 text-[0.9375rem] font-semibold text-[var(--ink-primary)] transition-colors hover:border-[var(--accent-primary)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-primary)] disabled:cursor-not-allowed disabled:opacity-50";
const PRIMARY =
  "inline-flex min-h-11 items-center justify-center rounded-xl bg-[var(--accent-primary)] px-4 text-[0.9375rem] font-bold text-[var(--accent-on-primary)] transition-colors hover:bg-[var(--accent-primary-hover)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-primary)] disabled:cursor-not-allowed disabled:opacity-50";
const DANGER =
  "inline-flex min-h-11 items-center justify-center rounded-xl border border-[var(--danger-fg)] bg-[var(--surface-card)] px-4 text-[0.9375rem] font-semibold text-[var(--danger-fg)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--danger-fg)]";
const INPUT =
  "min-h-11 w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] px-3 font-sans text-[0.9375rem] text-[var(--ink-primary)] outline-none focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]";

export interface SavedListsDialogProps {
  open: boolean;
  onClose: () => void;
  lists: SavedList[];
  /** Lines of the current list; saving needs at least one. */
  currentCount: number;
  onSave: (name: string) => void;
  onLoad: (id: string) => void;
  onRename: (id: string, name: string) => void;
  onDelete: (id: string) => void;
}

/** Native modal dialog to save the current list with a name and to load, rename or delete saved ones. */
export function SavedListsDialog({
  open,
  onClose,
  lists,
  currentCount,
  onSave,
  onLoad,
  onRename,
  onDelete,
}: SavedListsDialogProps) {
  const dialog = useModalDialog(open, onClose);
  const titleId = useId();
  const saveInputId = useId();
  const [name, setName] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [renameError, setRenameError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setName("");
    setNameError(null);
    setSaved(false);
    setRenamingId(null);
    setRenameError(null);
    setDeletingId(null);
  }, [open]);

  const replaces = sameNameExists(name, lists, null);

  function submitSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = name.trim();
    if (trimmed === "") {
      setNameError(SAVED_LISTS_NAME_REQUIRED);
      return;
    }
    onSave(trimmed);
    setName("");
    setNameError(null);
    setSaved(true);
  }

  function startRename(list: SavedList) {
    setDeletingId(null);
    setRenamingId(list.id);
    setRenameValue(list.name);
    setRenameError(null);
  }

  function submitRename(event: FormEvent<HTMLFormElement>, id: string) {
    event.preventDefault();
    const trimmed = renameValue.trim();
    if (trimmed === "") {
      setRenameError(SAVED_LISTS_NAME_REQUIRED);
      return;
    }
    if (sameNameExists(trimmed, lists, id)) {
      setRenameError(SAVED_LISTS_NAME_TAKEN);
      return;
    }
    onRename(id, trimmed);
    setRenamingId(null);
    setRenameError(null);
  }

  return (
    <dialog
      ref={dialog.ref}
      aria-labelledby={titleId}
      onCancel={dialog.onCancel}
      onClose={dialog.onClose}
      onClick={dialog.onClick}
      className="m-auto max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-md overflow-y-auto rounded-2xl border border-[var(--border-subtle)] bg-[var(--surface-card)] p-0 text-[var(--ink-primary)] backdrop:bg-black/55"
    >
      <div className="flex flex-col gap-5 p-5">
        <div className="flex items-center justify-between gap-3">
          <h2 id={titleId} className="text-[1.375rem] font-bold tracking-tight">
            {SAVED_LISTS_TITLE}
          </h2>
          <button type="button" onClick={onClose} autoFocus className={BUTTON}>
            Cerrar
          </button>
        </div>

        <section className="flex flex-col gap-3 border-t border-[var(--border-subtle)] pt-5">
          <h3 className="text-[0.9375rem] font-bold">{SAVED_LISTS_SAVE_TITLE}</h3>
          {currentCount === 0 ? (
            <p className="text-[0.8125rem] text-[var(--ink-secondary)]">
              {SAVED_LISTS_NOTHING_TO_SAVE}
            </p>
          ) : (
            <form onSubmit={submitSave} noValidate className="flex flex-col gap-2">
              <label htmlFor={saveInputId} className="text-[0.9375rem] font-semibold">
                {SAVED_LISTS_NAME_LABEL}
              </label>
              <div className="flex gap-2">
                <input
                  id={saveInputId}
                  type="text"
                  value={name}
                  autoComplete="off"
                  aria-invalid={nameError !== null}
                  aria-describedby={`${saveInputId}-hint`}
                  onChange={(event) => {
                    setName(event.target.value);
                    setNameError(null);
                    setSaved(false);
                  }}
                  className={INPUT}
                />
                <button type="submit" className={PRIMARY}>
                  Guardar
                </button>
              </div>
              <p
                id={`${saveInputId}-hint`}
                role={nameError ? "alert" : undefined}
                className={`text-[0.8125rem] ${
                  nameError ? "font-semibold text-[var(--danger-fg)]" : "text-[var(--ink-secondary)]"
                }`}
              >
                {nameError ?? (replaces ? SAVED_LISTS_NAME_REPLACES : "")}
              </p>
              {saved && (
                <p role="status" className="text-[0.8125rem] font-semibold text-[var(--savings-fg)]">
                  Lista guardada.
                </p>
              )}
            </form>
          )}
        </section>

        <section className="flex flex-col gap-3 border-t border-[var(--border-subtle)] pt-5">
          <h3 className="text-[0.9375rem] font-bold">{SAVED_LISTS_MINE_TITLE}</h3>
          {lists.length === 0 ? (
            <p className="text-[0.8125rem] text-[var(--ink-secondary)]">{SAVED_LISTS_EMPTY}</p>
          ) : (
            <ul className="flex flex-col divide-y divide-[var(--border-subtle)]">
              {lists.map((list) => (
                <li key={list.id} className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0">
                  {renamingId === list.id ? (
                    <form
                      onSubmit={(event) => submitRename(event, list.id)}
                      noValidate
                      className="flex flex-col gap-2"
                    >
                      <input
                        type="text"
                        value={renameValue}
                        autoFocus
                        autoComplete="off"
                        aria-label={`Nuevo nombre de ${list.name}`}
                        aria-invalid={renameError !== null}
                        onChange={(event) => {
                          setRenameValue(event.target.value);
                          setRenameError(null);
                        }}
                        className={INPUT}
                      />
                      {renameError && (
                        <p role="alert" className="text-[0.8125rem] font-semibold text-[var(--danger-fg)]">
                          {renameError}
                        </p>
                      )}
                      <div className="flex gap-2">
                        <button type="submit" className={PRIMARY}>
                          Guardar
                        </button>
                        <button type="button" onClick={() => setRenamingId(null)} className={BUTTON}>
                          Cancelar
                        </button>
                      </div>
                    </form>
                  ) : (
                    <>
                      <div className="flex items-baseline justify-between gap-3">
                        <p className="min-w-0 truncate text-[0.9375rem] font-semibold">{list.name}</p>
                        <p className="shrink-0 text-[0.8125rem] tabular-nums text-[var(--ink-secondary)]">
                          {productCountLabel(list.items.length)}
                        </p>
                      </div>
                      {deletingId === list.id ? (
                        <div className="flex flex-wrap items-center gap-2" role="group" aria-label={`Borrar ${list.name}`}>
                          <span className="text-[0.9375rem] font-semibold">¿Seguro?</span>
                          <button
                            type="button"
                            onClick={() => {
                              onDelete(list.id);
                              setDeletingId(null);
                            }}
                            className={DANGER}
                          >
                            Sí, borrar
                          </button>
                          <button type="button" onClick={() => setDeletingId(null)} className={BUTTON}>
                            Cancelar
                          </button>
                        </div>
                      ) : (
                        <div className="flex flex-wrap gap-2">
                          <button type="button" onClick={() => onLoad(list.id)} className={PRIMARY}>
                            Cargar
                          </button>
                          <button type="button" onClick={() => startRename(list)} className={BUTTON}>
                            Renombrar
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setRenamingId(null);
                              setDeletingId(list.id);
                            }}
                            className={BUTTON}
                          >
                            Borrar
                          </button>
                        </div>
                      )}
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </dialog>
  );
}
