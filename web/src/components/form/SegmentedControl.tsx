interface SegmentedOption {
  value: string;
  label: string;
}

interface SegmentedControlProps {
  options: SegmentedOption[];
  value: string;
  onChange: (value: string) => void;
}

/** DESIGN.md `segmented-control` — surface-1 track, active segment lifts to
 * surface-2 with a primary underline (the one non-status use of the accent:
 * "marking selected, not passed"). Used by Save Version's WIP/TR/CR/FINAL/
 * Custom status picker. */
export function SegmentedControl({ options, value, onChange }: SegmentedControlProps) {
  return (
    <div role="tablist" className="inline-flex gap-0.5 rounded-md p-1" style={{ backgroundColor: "var(--color-surface-1)" }}>
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(option.value)}
            className="text-label rounded-sm px-3 py-1 transition-colors duration-150 ease-out"
            style={{
              backgroundColor: active ? "var(--color-surface-2)" : "transparent",
              color: active ? "var(--color-ink)" : "var(--color-ink-secondary)",
              boxShadow: active ? "inset 0 -2px 0 0 var(--color-primary)" : "none",
            }}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
