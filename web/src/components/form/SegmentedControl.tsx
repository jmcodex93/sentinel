interface SegmentedOption {
  value: string;
  label: string;
}

interface SegmentedControlProps {
  options: SegmentedOption[];
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}

/** DESIGN.md `segmented-control` — surface-1 track, active segment lifts to
 * surface-2 with a primary underline (the one non-status use of the accent:
 * "marking selected, not passed"). Inactive segments get a hover fill (Rule
 * 3: "hover and focus states are mandatory on every interactive component"),
 * same surface-1/surface-2 swap `Button`'s secondary variant uses. Used by
 * Save Version's WIP/TR/CR/FINAL/Custom status picker and the Render
 * section's Multi-Part EXR / Direct output switch. */
export function SegmentedControl({ options, value, onChange, disabled }: SegmentedControlProps) {
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
            disabled={disabled}
            onClick={() => onChange(option.value)}
            className="text-label rounded-sm px-3 py-1 transition-colors duration-150 ease-out disabled:cursor-not-allowed disabled:opacity-50"
            style={{
              backgroundColor: active ? "var(--color-surface-2)" : "transparent",
              color: active ? "var(--color-ink)" : "var(--color-ink-secondary)",
              boxShadow: active ? "inset 0 -2px 0 0 var(--color-primary)" : "none",
            }}
            onMouseEnter={(e) => {
              if (!active && !disabled) e.currentTarget.style.backgroundColor = "var(--color-surface-2)";
            }}
            onMouseLeave={(e) => {
              if (!active) e.currentTarget.style.backgroundColor = "transparent";
            }}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
