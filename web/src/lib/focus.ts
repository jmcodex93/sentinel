/** Webview focus restoration (v1.18 lesson, live-diagnosed in the Hub):
 * the C4D webview needs SOME live focused element for Cmd+Z to pass through
 * to C4D's key handling. When the focused element (a dialog button, a
 * sub-view's controls) is removed from the DOM on close/unmount, nothing is
 * focused and the very next Cmd+Z is swallowed until the user clicks.
 * Call this whenever a focused surface is about to unmount (or just did).
 *
 * `target` — a persistent element to receive focus (e.g. the Hub's table
 * wrapper). Without one, falls back to the SPA root (given tabindex="-1" so
 * it is programmatically focusable), then to document.body. */
export function restoreFocus(target?: HTMLElement | null) {
  let el: HTMLElement | null = target ?? document.getElementById("root");
  if (el && el !== document.body && !el.hasAttribute("tabindex")) {
    el.setAttribute("tabindex", "-1");
  }
  if (!el) el = document.body;
  el.focus({ preventScroll: true });
}
