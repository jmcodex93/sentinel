/** The host's undo key for text the artist reads (Windows round 7 showed
 * "Cmd+Z"): `Cmd+Z` only when the web view says it runs on a Mac, `Ctrl+Z`
 * otherwise — an unusual Windows viewer string still gets the right key.
 * The server's own labels use `common.helpers.undo_shortcut`. */
export function undoShortcut(userAgent: string = typeof navigator === "undefined" ? "" : navigator.userAgent): string {
  return /Mac/i.test(userAgent) ? "Cmd+Z" : "Ctrl+Z";
}
