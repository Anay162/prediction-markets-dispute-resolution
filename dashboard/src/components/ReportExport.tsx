// src/components/ReportExport.tsx
// PDF download button for an audit report.
// Opens the PDF in a new tab via the /v1/reports/{id}/pdf endpoint.

import { reportPdfUrl } from "@/lib/api";

interface ReportExportProps {
  reportId: string;
  className?: string;
}

export default function ReportExport({ reportId, className = "" }: ReportExportProps) {
  return (
    <a
      href={reportPdfUrl(reportId)}
      target="_blank"
      rel="noopener noreferrer"
      className={`inline-flex items-center gap-1.5 text-sm font-medium text-blue-600 hover:text-blue-800 transition-colors ${className}`}
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
        <polyline points="7 10 12 15 17 10" />
        <line x1="12" y1="15" x2="12" y2="3" />
      </svg>
      Download PDF
    </a>
  );
}
