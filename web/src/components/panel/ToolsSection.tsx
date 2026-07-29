import { Fragment, useState } from "react";
import { Button } from "../form/Button";
import { TextInput } from "../form/TextInput";
import { TOOL_GROUPS } from "../../lib/panelTools";
import { SectionGroup } from "../SectionGroup";
import { RenameSubview } from "./RenameSubview";

/** Tools section (Fase 6.4, Cleanup + Frames row added later) — grouped
 * action buttons for scene-authoring utilities. Action-only: each button
 * runs its op and toasts the result; no read state, no confirm (nothing
 * destructive). The Asset Hub is reached from Overview / QC #6 / Deliver,
 * not from here. The Frames row is the first parameterized Tools action —
 * `frames` is local UI state forwarded as the op payload; the toast itself
 * always reads the frames value back from the op RESULT, never from this
 * state, so it stays truthful to what actually ran. */
export function ToolsSection({
  busy,
  onRunTool,
}: {
  busy: string | null;
  onRunTool: (id: string, payload?: Record<string, unknown>) => void;
}) {
  const isBusy = busy !== null;
  const [frames, setFrames] = useState(5);
  // Local sub-router (the Render→Frame / Deliver idiom): "rename" swaps the
  // whole section for the Batch Rename sub-view, which owns its own fetches
  // and busy state (server-driven preview — see RenameSubview).
  const [view, setView] = useState<"main" | "rename">("main");
  if (view === "rename") {
    return <RenameSubview onBack={() => setView("main")} />;
  }
  return (
    // During a mutation we lock interaction at the container (`pointerEvents`)
    // instead of `disabled`-ing every button: `disabled` dims with
    // `opacity-50`, so each press flashed the whole section to 50% and back —
    // the exact live-caught v1.26.0 Render flicker, same root, same fix.
    <div className="flex flex-col p-3" style={{ pointerEvents: isBusy ? "none" : undefined }}>
      {TOOL_GROUPS.map((group, index) => (
        <Fragment key={group.title}>
        <SectionGroup title={group.title} first={index === 0}>
          <div className="flex flex-wrap gap-2">
            {group.tools.map((tool) => (
              <Button
                key={tool.id}
                variant="secondary"
                onClick={() => onRunTool(tool.id)}
              >
                {tool.label}
              </Button>
            ))}
          </div>
          {group.title === "Animation" && (
            <div className="mt-2 flex items-center gap-2">
              <label className="text-xs text-[var(--color-text-secondary)]">Frames</label>
              <div className="w-16">
                <TextInput
                  type="number"
                  value={frames}
                  onChange={(e) => setFrames(parseInt(e.target.value || "0", 10))}
                />
              </div>
              <Button
                variant="secondary"
                onClick={() => onRunTool("panel/tools/keyframe_offset", { frames })}
              >
                Offset
              </Button>
              <Button
                variant="secondary"
                onClick={() => onRunTool("panel/tools/keyframe_stagger", { frames })}
              >
                Stagger
              </Button>
            </div>
          )}
        </SectionGroup>
        {group.title === "Cleanup" && (
          // Naming is a sub-router trigger, not an op button, so it lives
          // outside TOOL_GROUPS (which stays op-only for `toolToast`).
          <SectionGroup title="Naming">
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" onClick={() => setView("rename")}>
                Batch Rename →
              </Button>
            </div>
          </SectionGroup>
        )}
        </Fragment>
      ))}
    </div>
  );
}
