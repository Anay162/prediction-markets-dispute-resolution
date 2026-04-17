// src/components/FindingCard.tsx
// Displays a single vulnerability finding with its severity badge,
// category label, description, diff view, and evidence.

import { useState } from "react";
import type { Finding } from "@/lib/types";
import { SEVERITY_META, CATEGORY_LABELS } from "@/lib/types";
import SeverityBadge from "./SeverityBadge";
import RewriteDiff from "./RewriteDiff";

interface FindingCardProps {
  finding: Finding;
}

export default function FindingCard({ finding }: FindingCardProps) {
  const [expanded, setExpanded] = useState(
    finding.severity === "critical" || finding.severity === "high"
  );

  return (
    <div
      className={`bg-white rounded-xl border ${SEVERITY_META[finding.severity].border} overflow-hidden`}
    >
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-start gap-3 px-5 py-4 text-left hover:bg-gray-50 transition-colors"
      >
        <SeverityBadge severity={finding.severity} />
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium text-gray-500 mb-0.5">
            {CATEGORY_LABELS[finding.category]}
          </p>
          <p className="text-sm text-gray-900 line-clamp-2">{finding.description}</p>
        </div>
        <span className="shrink-0 text-gray-400 text-xs mt-0.5">
          {expanded ? "▲" : "▼"}
        </span>
      </button>

      {/* Expanded body */}
      {expanded && (
        <div className="px-5 pb-5 space-y-4 border-t border-gray-100">
          {/* Affected clause */}
          <div>
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">
              Affected clause
            </p>
            <blockquote className="bg-gray-50 border-l-4 border-gray-300 pl-3 py-2 text-sm text-gray-700 rounded-r-md">
              {finding.affected_clause}
            </blockquote>
          </div>

          {/* Diff / Rewrite */}
          {finding.diff && finding.diff.length > 0 ? (
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">
                Suggested rewrite
              </p>
              <RewriteDiff diff={finding.diff} />
            </div>
          ) : finding.rewrite ? (
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">
                Suggested rewrite
              </p>
              <div className="bg-green-50 border-l-4 border-green-400 pl-3 py-2 text-sm text-green-900 rounded-r-md">
                {finding.rewrite}
              </div>
            </div>
          ) : null}

          {/* Evidence */}
          {finding.evidence.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">
                Evidence
              </p>
              <ul className="space-y-1">
                {finding.evidence.map((ev, i) => (
                  <li key={i} className="text-xs text-gray-600 flex gap-2">
                    <span className="text-gray-400 shrink-0">–</span>
                    <span>{ev}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Confidence */}
          <p className="text-xs text-gray-400">
            Confidence: {Math.round(finding.confidence * 100)}%
          </p>
        </div>
      )}
    </div>
  );
}
