// dashboard/src/components/DecisionFeed.tsx
import type { Decision } from "../api/client";

export function DecisionFeed({
  decisions,
  limit = 20,
  title = "Recent Decisions",
}: {
  decisions: Decision[];
  limit?: number;
  title?: string;
}) {
  return (
    <div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm">
      <h2 className="text-base font-semibold text-gray-900 mb-4">{title}</h2>
      <div className="space-y-2 max-h-80 overflow-y-auto">
        {decisions.slice(0, limit).map((d) => (
          <div key={d.id} className="border border-gray-100 rounded-lg p-3">
            <div className="flex items-center justify-between mb-1">
              <span className="text-gray-900 font-medium text-sm">{d.symbol}</span>
              <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                d.final_decision === "PLACED"
                  ? "bg-green-50 text-green-600"
                  : d.final_decision === "REJECTED"
                  ? "bg-red-50 text-red-500"
                  : "bg-gray-50 text-gray-500"
              }`}>
                {d.final_decision}
              </span>
              <span className="text-gray-400 text-xs">
                {new Date(d.timestamp).toLocaleTimeString()}
              </span>
            </div>
            <p className="text-gray-500 text-xs leading-relaxed">
              <span className="text-gray-400 text-xs mr-2">{d.signal_side} · {(d.confidence * 100).toFixed(0)}%</span>
              {d.narrative}
            </p>
          </div>
        ))}
        {decisions.length === 0 && (
          <p className="text-gray-400 text-center py-6 text-sm">No decisions logged yet</p>
        )}
      </div>
    </div>
  );
}
