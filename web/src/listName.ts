/** Asks for a saved-list name; null when the user cancels or leaves it empty. */
export function askListName(): string | null {
  const name = window.prompt("Nombre de la lista");
  if (name === null) return null;
  const trimmed = name.trim();
  return trimmed === "" ? null : trimmed;
}
