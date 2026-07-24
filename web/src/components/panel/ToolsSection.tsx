import { Button } from "../form/Button";
import { TOOL_GROUPS } from "../../lib/panelTools";

/** Tools section (Fase 6.4) — grouped action buttons mirroring the native
 * Tools tab. Action-only: each button runs its op and toasts the result;
 * no read state, no confirm (nothing destructive). "Asset Hub" opens the
 * Hub window via the `open_hub` palette action instead of a tools op. */
export function ToolsSection({
  busy,
  onRunTool,
  onOpenHub,
}: {
  busy: string | null;
  onRunTool: (id: string) => void;
  onOpenHub: () => void;
}) {
  const isBusy = busy !== null;
  return (
    <div className="flex flex-col gap-3 p-3">
      {TOOL_GROUPS.map((group) => (
        <div
          key={group.title}
          className="flex flex-col gap-2 rounded-lg border p-3"
          style={{ borderColor: "var(--color-hairline)", backgroundColor: "var(--color-surface-1)" }}
        >
          <p className="text-label" style={{ color: "var(--color-ink-secondary)" }}>
            {group.title.toUpperCase()}
          </p>
          <div className="flex flex-wrap gap-2">
            {group.tools.map((tool) => (
              <Button
                key={tool.id}
                variant="secondary"
                disabled={isBusy}
                onClick={() => (tool.id === "open_hub" ? onOpenHub() : onRunTool(tool.id))}
              >
                {tool.label}
              </Button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
