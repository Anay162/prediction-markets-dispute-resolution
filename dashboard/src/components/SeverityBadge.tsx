// src/components/SeverityBadge.tsx
// Small coloured pill showing a severity level.
// Accepts an optional count to show "2 critical" style labels.

import type { Severity } from "@/lib/types";
import { SEVERITY_META } from "@/lib/types";

interface SeverityBadgeProps {
  severity: Severity;
  count?: number;
}

export default function SeverityBadge({ severity, count }: SeverityBadgeProps) {
  const meta = SEVERITY_META[severity];
  const label = count !== undefined
    ? `${count} ${meta.label.toLowerCase()}`
    : meta.label;

  return (
    <span
      className={`inline-flex items-center text-xs font-semibold px-2.5 py-0.5 rounded-full ${meta.bg} ${meta.color}`}
    >
      {label}
    </span>
  );
}
