import type { ToastOptions } from "./toast";

/** What `selectOwner` needs from the Hub page — injected so the flow is
 * testable without rendering the page. `refresh` resolves `false` when the
 * page held the refresh back (staged repaths: it shows its scene-changed
 * banner instead). */
export interface OwnerDeps {
  currentStamp: () => string | null;
  select: (key: string, expectedStamp: string) => Promise<{ ok: boolean; stamp?: string; error?: string }>;
  acknowledge: (stamp: string, previous: string) => void;
  refresh: () => Promise<boolean>;
}

const OWNER_ERRORS: Record<string, string> = {
  "unknown key": "That asset is no longer in the scene.",
};

/** A row click's owner selection (`hub/select_owner`). The server refuses
 * with `scene_changed` when the Hub's stamp is stale — legitimately, so the
 * Hub never adopts another snapshot's stamp. After an Undo/Redo, C4D keeps
 * bumping material dirty counters for a few seconds (measured 2026-10-30:
 * +4 within ~2.5 s), and the Windows round 7 tester got one raw
 * `scene_changed` toast per click (19–26). So: refresh quietly, retry once
 * with the fresh stamp, and only then say — readably — that the scene is
 * still settling. Returns the toast to show, or `null`. */
export async function selectOwner(key: string, deps: OwnerDeps): Promise<ToastOptions | null> {
  const previous = deps.currentStamp();
  if (previous === null) return null;
  let res = await deps.select(key, previous);
  let expected = previous;
  if (!res.ok && res.error === "scene_changed") {
    if (!(await deps.refresh())) return null;
    const fresh = deps.currentStamp();
    if (fresh === null) return null;
    expected = fresh;
    res = await deps.select(key, fresh);
    if (!res.ok && res.error === "scene_changed") {
      return { message: "The scene is still updating — click the row again in a moment.", variant: "info" };
    }
  }
  if (res.ok) {
    if (res.stamp) deps.acknowledge(res.stamp, expected);
    return null;
  }
  return { message: OWNER_ERRORS[res.error ?? ""] ?? "Couldn't select the owner.", variant: "warn" };
}
