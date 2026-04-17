"use client";
// src/app/contracts/page.tsx
// Audit history — lists all contracts that have been submitted.

import { useEffect, useState } from "react";
import { listContracts, deleteContract } from "@/lib/api";
import type { ContractSummary, Platform } from "@/lib/types";

const PLATFORM_LABELS: Record<Platform, string> = {
  generic: "Generic",
  kalshi: "Kalshi",
  polymarket: "Polymarket",
  manifold: "Manifold",
  metaculus: "Metaculus",
};

export default function ContractsPage() {
  const [contracts, setContracts] = useState<ContractSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  useEffect(() => {
    listContracts({ limit: 50 })
      .then(setContracts)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  async function handleDelete(id: string) {
    if (!confirm("Delete this contract and all its reports?")) return;
    setDeleting(id);
    try {
      await deleteContract(id);
      setContracts((prev) => prev.filter((c) => c.id !== id));
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setDeleting(null);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48 text-gray-400 text-sm">
        Loading…
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-red-700 text-sm">
        {error}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Audit history</h1>
          <p className="text-sm text-gray-500 mt-1">
            {contracts.length} contract{contracts.length !== 1 ? "s" : ""} audited
          </p>
        </div>
        <a
          href="/"
          className="bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
        >
          New audit
        </a>
      </div>

      {contracts.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center">
          <p className="text-gray-500 text-sm">No contracts audited yet.</p>
          <a href="/" className="mt-3 inline-block text-blue-600 text-sm hover:underline">
            Run your first audit →
          </a>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100">
          {contracts.map((contract) => (
            <div
              key={contract.id}
              className="flex items-start gap-4 px-5 py-4 hover:bg-gray-50 transition-colors"
            >
              <div className="flex-1 min-w-0">
                <a
                  href={`/contracts/${contract.id}`}
                  className="text-sm font-medium text-gray-900 hover:text-blue-600 line-clamp-2 transition-colors"
                >
                  {contract.question}
                </a>
                <div className="flex gap-3 mt-1 text-xs text-gray-500">
                  <span>{PLATFORM_LABELS[contract.platform] ?? contract.platform}</span>
                  <span>Closes {contract.close_date}</span>
                  <span>{new Date(contract.created_at).toLocaleDateString()}</span>
                </div>
              </div>
              <button
                onClick={() => handleDelete(contract.id)}
                disabled={deleting === contract.id}
                className="shrink-0 text-xs text-gray-400 hover:text-red-600 disabled:opacity-40 transition-colors"
              >
                {deleting === contract.id ? "Deleting…" : "Delete"}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
