import { Button } from "../form/Button";
import { TOOL_GROUPS } from "../../lib/panelTools";
import { SectionGroup } from "../SectionGroup";

/** Tools section (Fase 6.4) — grouped action buttons for scene-authoring
 * utilities. Action-only: each button runs its op and toasts the result;
 * no read state, no confirm (nothing destructive). The Asset Hub is reached
 * from Overview / QC #6 / Deliver, not from here. */
export function ToolsSection({
  busy,
  onRunTool,
}: {
  busy: string | null;
  onRunTool: (id: string) => void;
}) {
  const isBusy = busy !== null;
  return (
    <div className="flex flex-col p-3">
      {TOOL_GROUPS.map((group, index) => (
        <SectionGroup key={group.title} title={group.title} first={index === 0}>
          <div className="flex flex-wrap gap-2">
            {group.tools.map((tool) => (
              <Button
                key={tool.id}
                variant="secondary"
                disabled={isBusy}
                onClick={() => onRunTool(tool.id)}
              >
                {tool.label}
              </Button>
            ))}
          </div>
        </SectionGroup>
      ))}
    </div>
  );
}
