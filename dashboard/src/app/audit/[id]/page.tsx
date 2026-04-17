"use client";
// src/app/audit/[id]/page.tsx
// Full report view for a completed audit, fetched by report ID.

import { useEffect, useState } from "react";
import { getReport, reportPdfUrl } from "@/lib/api";
import type { ReportOutput } from "@/lib/types";
import RCSGauge from "@/components/RCSGauge";
import FindingCard from "@/components/FindingCard";
import SeverityBadge from "@/components/SeverityBadge";

export default function AuditReportPage({
  params,
}: {
  params: { id: string };
}) {
  const [report, setReport] = useState<ReportOutput | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getReport(params.id)
      .then(setReport)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [params.id]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48 text-gray-400 text-sm">
        Loading report…
      </div>
    );
  }

  if (error || !report) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-red-700 text-sm">
        {error ?? "Report not found"}
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Audit report</h1>
          <p className="text-sm text-gray-500 mt-1 font-mono">{report.id}</p>
        </div>
        <a
          href={reportPdfUrl(report.id)}
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 bg-white border border-gray-300 hover:border-gray-400 text-gray-700 text-sm font-medium px-4 py-2 rounded-lg transition-colors"
        >
          Download PDF
        </a>
      </div>

      {/* Score block */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <div className="flex items-start gap-6">
          <RCSGauge score={report.resolution_clarity_score} />
          <div className="flex-1">
            <p className="text-xl font-semibold text-gray-900">{report.score_label}</p>
            <p className="text-sm text-gray-500">Resolution Clarity Score</p>
            <div className="flex gap-3 mt-3 flex-wrap">
              {[
                { count: report.critical_count, severity: "critical" as const },
                { count: report.high_count, severity: "high" as const },
                { count: report.medium_count, severity: "medium" as const },
                { count: report.low_count, severity: "low" as const },
              ]
                .filter((s) => s.count > 0)
                .map(({ count, severity }) => (
                  <SeverityBadge key={severity} severity={severity} count={count} />
                ))}
            </div>
          </div>
        </div>
        <div className="mt-4 pt-4 border-t border-gray-100 flex gap-6 text-sm text-gray-500">
          <span>Duration: {report.audit_duration_seconds.toFixed(1)}s</span>
          <span>Model: {report.model_version}</span>
          <span>
            Generated: {new Date(report.created_at).toLocaleString()}
          </span>
        </div>
      </div>

      {/* Findings */}
      {report.findings.length === 0 ? (
        <div className="bg-green-50 border border-green-200 rounded-xl p-8 text-center">
          <p className="text-green-800 font-medium text-lg">No vulnerabilities found</p>
          <p className="text-green-600 text-sm mt-1">
            This contract appears well-specified across all six vulnerability categories.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          <h2 className="text-lg font-semibold text-gray-900">
            {report.findings.length} finding
            {report.findings.length !== 1 ? "s" : ""}
          </h2>
          {report.findings.map((finding) => (
            <FindingCard key={finding.id} finding={finding} />
          ))}
        </div>
      )}

      {/* Rewritten contract */}
      {report.rewritten_contract && (
        <div className="space-y-3">
          <h2 className="text-lg font-semibold text-gray-900">Rewritten contract</h2>
          <pre className="bg-white border border-gray-200 rounded-xl p-6 text-sm text-gray-700 whitespace-pre-wrap font-mono leading-relaxed overflow-x-auto">
            {report.rewritten_contract}
          </pre>
        </div>
      )}
    </div>
  );
}
