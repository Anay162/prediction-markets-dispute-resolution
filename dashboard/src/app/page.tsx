"use client";
// src/app/page.tsx
// Dashboard home: contract submission form + live polling for results.

import { useState } from "react";
import { submitAudit, getAuditStatus } from "@/lib/api";
import type { ReportOutput, AuditStatus, Platform } from "@/lib/types";
import RCSGauge from "@/components/RCSGauge";
import FindingCard from "@/components/FindingCard";

const PLATFORMS: Platform[] = [
  "generic",
  "kalshi",
  "polymarket",
  "manifold",
  "metaculus",
];

// Min close date = tomorrow
function minCloseDate(): string {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return d.toISOString().split("T")[0];
}

export default function Home() {
  const [question, setQuestion] = useState("");
  const [criteria, setCriteria] = useState("");
  const [source, setSource] = useState("");
  const [closeDate, setCloseDate] = useState("");
  const [platform, setPlatform] = useState<Platform>("generic");

  const [status, setStatus] = useState<AuditStatus | null>(null);
  const [stage, setStage] = useState("");
  const [progress, setProgress] = useState(0);
  const [report, setReport] = useState<ReportOutput | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    setReport(null);
    setStatus("pending");
    setProgress(0);
    setStage("Submitting…");

    try {
      const res = await submitAudit(
        { question, resolution_criteria: criteria, resolution_source: source, close_date: closeDate, platform },
        false
      );

      const jobId = res.job_id;
      setStatus("running");

      // Poll every 2 seconds until complete or failed
      const poll = setInterval(async () => {
        try {
          const s = await getAuditStatus(jobId);
          setProgress(s.progress_pct);
          setStage(s.current_stage);
          setStatus(s.status);

          if (s.status === "complete") {
            clearInterval(poll);
            setReport(s.report);
            setSubmitting(false);
          } else if (s.status === "failed") {
            clearInterval(poll);
            setError(s.error ?? "Audit failed");
            setSubmitting(false);
          }
        } catch {
          // Polling errors are transient — keep trying
        }
      }, 2000);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Submission failed");
      setStatus(null);
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">New audit</h1>
        <p className="mt-1 text-sm text-gray-500">
          Submit a contract to identify resolution vulnerabilities before it goes live.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5 bg-white rounded-xl border border-gray-200 p-6">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Question</label>
          <input
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Will US GDP growth exceed 2% in 2025?"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            required
            disabled={submitting}
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Resolution criteria</label>
          <textarea
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
            rows={4}
            placeholder="Resolves YES if…"
            value={criteria}
            onChange={(e) => setCriteria(e.target.value)}
            required
            disabled={submitting}
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Resolution source</label>
          <input
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="https://bea.gov/… or description of source"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            required
            disabled={submitting}
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Close date</label>
            <input
              type="date"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              min={minCloseDate()}
              value={closeDate}
              onChange={(e) => setCloseDate(e.target.value)}
              required
              disabled={submitting}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Platform</label>
            <select
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={platform}
              onChange={(e) => setPlatform(e.target.value as Platform)}
              disabled={submitting}
            >
              {PLATFORMS.map((p) => (
                <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>
              ))}
            </select>
          </div>
        </div>

        <button
          type="submit"
          disabled={submitting}
          className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white text-sm font-medium py-2.5 rounded-lg transition-colors"
        >
          {submitting ? "Auditing…" : "Run audit"}
        </button>
      </form>

      {/* Progress bar */}
      {submitting && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-3">
          <div className="flex justify-between text-sm text-gray-600">
            <span>{stage}</span>
            <span>{progress}%</span>
          </div>
          <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 rounded-full transition-all duration-500"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Report */}
      {report && <ReportView report={report} />}
    </div>
  );
}

function ReportView({ report }: { report: ReportOutput }) {
  return (
    <div className="space-y-6">
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <div className="flex items-start gap-6">
          <RCSGauge score={report.resolution_clarity_score} />
          <div className="flex-1 min-w-0">
            <p className="text-lg font-semibold text-gray-900">{report.score_label}</p>
            <p className="text-sm text-gray-500 mt-0.5">Resolution Clarity Score</p>
            <div className="flex gap-3 mt-3 flex-wrap">
              {report.critical_count > 0 && (
                <span className="text-xs font-medium bg-red-100 text-red-800 px-2.5 py-1 rounded-full">
                  {report.critical_count} critical
                </span>
              )}
              {report.high_count > 0 && (
                <span className="text-xs font-medium bg-amber-100 text-amber-800 px-2.5 py-1 rounded-full">
                  {report.high_count} high
                </span>
              )}
              {report.medium_count > 0 && (
                <span className="text-xs font-medium bg-blue-100 text-blue-800 px-2.5 py-1 rounded-full">
                  {report.medium_count} medium
                </span>
              )}
              {report.low_count > 0 && (
                <span className="text-xs font-medium bg-green-100 text-green-800 px-2.5 py-1 rounded-full">
                  {report.low_count} low
                </span>
              )}
            </div>
          </div>
          <a
            href={`/api/v1/reports/${report.id}/pdf`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-blue-600 hover:text-blue-800 font-medium whitespace-nowrap"
          >
            Download PDF
          </a>
        </div>
      </div>

      {report.findings.length === 0 ? (
        <div className="bg-green-50 border border-green-200 rounded-xl p-6 text-center">
          <p className="text-green-800 font-medium">No vulnerabilities found</p>
          <p className="text-green-600 text-sm mt-1">This contract appears well-specified.</p>
        </div>
      ) : (
        <div className="space-y-4">
          <h2 className="text-lg font-semibold text-gray-900">
            {report.findings.length} finding{report.findings.length !== 1 ? "s" : ""}
          </h2>
          {report.findings.map((finding) => (
            <FindingCard key={finding.id} finding={finding} />
          ))}
        </div>
      )}
    </div>
  );
}
