import type { ReactNode } from "react";

/** A titled block of report content — `{typography.subhead}` heading over
 * its children, spaced from the previous section on the 8px grid. */
export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-6 first:mt-0">
      <h2 className="text-subhead mb-2" style={{ color: "var(--color-ink)" }}>
        {title}
      </h2>
      {children}
    </section>
  );
}
