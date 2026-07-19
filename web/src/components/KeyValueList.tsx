import { Fragment } from "react";

export interface KeyValueItem {
  label: string;
  value: string;
}

/** A dense label/value grid — Doctor's meta block, Render Validation's
 * context block. Blank values render as an em dash rather than empty
 * space, so a missing field reads as "known and empty," not layout drift. */
export function KeyValueList({ items }: { items: KeyValueItem[] }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1.5">
      {items.map(({ label, value }) => (
        <Fragment key={label}>
          <dt className="text-label" style={{ color: "var(--color-ink-secondary)" }}>
            {label}
          </dt>
          <dd className="text-body truncate" style={{ color: "var(--color-ink)" }}>
            {value || "—"}
          </dd>
        </Fragment>
      ))}
    </dl>
  );
}
