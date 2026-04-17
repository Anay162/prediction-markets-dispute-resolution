// src/components/AuditForm.tsx
// Standalone contract submission form component.
// Extracted so it can be embedded in other pages (e.g. a contract
// detail page with a "Re-audit" button).

import type { ContractInput, Platform } from "@/lib/types";

const PLATFORMS: { value: Platform; label: string }[] = [
  { value: "generic", label: "Generic" },
  { value: "kalshi", label: "Kalshi" },
  { value: "polymarket", label: "Polymarket" },
  { value: "manifold", label: "Manifold" },
  { value: "metaculus", label: "Metaculus" },
];

function minCloseDate(): string {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return d.toISOString().split("T")[0];
}

interface AuditFormProps {
  onSubmit: (contract: ContractInput) => void;
  loading?: boolean;
  defaultValues?: Partial<ContractInput>;
}

export default function AuditForm({
  onSubmit,
  loading = false,
  defaultValues = {},
}: AuditFormProps) {
  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    onSubmit({
      question: fd.get("question") as string,
      resolution_criteria: fd.get("resolution_criteria") as string,
      resolution_source: fd.get("resolution_source") as string,
      close_date: fd.get("close_date") as string,
      platform: fd.get("platform") as Platform,
    });
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-5 bg-white rounded-xl border border-gray-200 p-6"
    >
      <div>
        <label
          htmlFor="question"
          className="block text-sm font-medium text-gray-700 mb-1"
        >
          Question
        </label>
        <input
          id="question"
          name="question"
          required
          disabled={loading}
          defaultValue={defaultValues.question ?? ""}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-50"
          placeholder="Will US GDP growth exceed 2% in 2025?"
        />
      </div>

      <div>
        <label
          htmlFor="resolution_criteria"
          className="block text-sm font-medium text-gray-700 mb-1"
        >
          Resolution criteria
        </label>
        <textarea
          id="resolution_criteria"
          name="resolution_criteria"
          required
          disabled={loading}
          defaultValue={defaultValues.resolution_criteria ?? ""}
          rows={4}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-50 resize-y"
          placeholder="Resolves YES if…"
        />
      </div>

      <div>
        <label
          htmlFor="resolution_source"
          className="block text-sm font-medium text-gray-700 mb-1"
        >
          Resolution source
        </label>
        <input
          id="resolution_source"
          name="resolution_source"
          required
          disabled={loading}
          defaultValue={defaultValues.resolution_source ?? ""}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-50"
          placeholder="https://bea.gov/… or plain-text description"
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label
            htmlFor="close_date"
            className="block text-sm font-medium text-gray-700 mb-1"
          >
            Close date
          </label>
          <input
            id="close_date"
            name="close_date"
            type="date"
            required
            disabled={loading}
            min={minCloseDate()}
            defaultValue={defaultValues.close_date ?? ""}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-50"
          />
        </div>
        <div>
          <label
            htmlFor="platform"
            className="block text-sm font-medium text-gray-700 mb-1"
          >
            Platform
          </label>
          <select
            id="platform"
            name="platform"
            disabled={loading}
            defaultValue={defaultValues.platform ?? "generic"}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-50"
          >
            {PLATFORMS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <button
        type="submit"
        disabled={loading}
        className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white text-sm font-medium py-2.5 rounded-lg transition-colors"
      >
        {loading ? "Auditing…" : "Run audit"}
      </button>
    </form>
  );
}
