import * as Tooltip from "@radix-ui/react-tooltip";
import type { CSSProperties } from "react";
import type { DeliveryAsset } from "../types";
import { StatusBadge } from "./StatusBadge";

const headerCellStyle: CSSProperties = {
  backgroundColor: "var(--color-surface-1)",
  borderBottom: "1px solid var(--color-hairline-strong)",
  color: "var(--color-ink-secondary)",
};

const rowCellStyle: CSSProperties = {
  borderBottom: "1px solid var(--color-hairline)",
};

export function AssetsTable({ assets }: { assets: DeliveryAsset[] }) {
  if (assets.length === 0) {
    return (
      <p className="text-body p-4" style={{ color: "var(--color-muted)" }}>
        No assets recorded in this manifest.
      </p>
    );
  }

  return (
    <Tooltip.Provider delayDuration={300}>
      <div
        className="overflow-auto rounded-lg border"
        style={{ borderColor: "var(--color-hairline)", maxHeight: "60vh" }}
      >
        <table className="w-full table-fixed border-collapse">
          <colgroup>
            <col className="w-[46%]" />
            <col className="w-[18%]" />
            <col className="w-[36%]" />
          </colgroup>
          <thead>
            <tr>
              <th className="text-label sticky top-0 z-10 px-4 py-2 text-left" style={headerCellStyle}>
                Path
              </th>
              <th className="text-label sticky top-0 z-10 px-4 py-2 text-left" style={headerCellStyle}>
                Status
              </th>
              <th className="text-label sticky top-0 z-10 px-4 py-2 text-left" style={headerCellStyle}>
                Provenance
              </th>
            </tr>
          </thead>
          <tbody>
            {assets.map((asset, index) => (
              <tr
                key={`${asset.status}:${asset.path}:${index}`}
                className="h-8 transition-colors duration-100 ease-out hover:bg-[var(--color-surface-2)]"
              >
                <td className="text-body px-4" style={rowCellStyle}>
                  <Tooltip.Root>
                    <Tooltip.Trigger asChild>
                      <span className="block truncate">{asset.path}</span>
                    </Tooltip.Trigger>
                    <Tooltip.Portal>
                      <Tooltip.Content
                        side="top"
                        align="start"
                        sideOffset={4}
                        className="text-caption max-w-md rounded-md px-2 py-1 shadow-lg"
                        style={{
                          backgroundColor: "var(--color-surface-2)",
                          color: "var(--color-ink)",
                          border: "1px solid var(--color-hairline-strong)",
                        }}
                      >
                        {asset.path}
                      </Tooltip.Content>
                    </Tooltip.Portal>
                  </Tooltip.Root>
                </td>
                <td className="px-4" style={rowCellStyle}>
                  <StatusBadge status={asset.status} />
                </td>
                <td
                  className="text-body truncate px-4"
                  style={{ ...rowCellStyle, color: "var(--color-ink-secondary)" }}
                >
                  {asset.provenance}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Tooltip.Provider>
  );
}
