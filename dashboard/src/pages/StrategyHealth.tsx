// dashboard/src/pages/StrategyHealth.tsx
import { useStrategyHealth, useABTests, useDecisionLog } from "../api/client";
import { StatCard } from "../components/StatCard";

export default function StrategyHealth() {
  const { data: health } = useStrategyHealth();
  const { data: abTests = [] } = useABTests();
  const { data: decisions = [] } = useDecisionLog();

  const winRateValue = health?.win_rate_30 ?? 0;
  const calibrationValue = health?.confidence_calibration ?? 0;
  const avgPnl = health?.avg_pnl ?? 0;
  const totalOutcomes = health?.total_outcomes ?? 0;

  const winRateColor =
    winRateValue >= 0.4 ? "text-green-600" : "text-red-500";
  const calibrationColor =
    calibrationValue >= 0.2 ? "text-green-600" : "text-red-500";

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-gray-900">Strategy Health</h1>

      {/* KPI Row — reuse StatCard for light-theme consistency */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm">
          <p className="text-sm text-gray-500">Win Rate (last 30)</p>
          <p className={`text-2xl font-bold mt-1 ${winRateColor}`}>
            {(winRateValue * 100).toFixed(1)}%
          </p>
          <p className="text-xs text-gray-400 mt-1">Threshold: 40%</p>
        </div>
        <div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm">
          <p className="text-sm text-gray-500">Confidence Calibration</p>
          <p className={`text-2xl font-bold mt-1 ${calibrationColor}`}>
            {calibrationValue.toFixed(2)}
          </p>
          <p className="text-xs text-gray-400 mt-1">Threshold: 0.20</p>
        </div>
        <StatCard
          label="Avg PnL per Trade"
          value={`${avgPnl >= 0 ? "+" : ""}$${avgPnl.toFixed(2)}`}
          sub={avgPnl >= 0 ? "Profitable" : "Losing"}
        />
        <StatCard
          label="Outcomes Tracked"
          value={String(totalOutcomes)}
          sub="Signal outcomes"
        />
      </div>

      {/* A/B Test History */}
      <div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm">
        <h2 className="text-base font-semibold text-gray-900 mb-4">A/B Test History</h2>
        {abTests.length === 0 ? (
          <p className="text-gray-400 text-center py-6 text-sm">No A/B tests run yet</p>
        ) : (
          <table className="w-full text-sm text-left">
            <thead>
              <tr className="text-gray-500 border-b border-gray-100">
                <th className="pb-2 font-medium">Date</th>
                <th className="pb-2 font-medium">Champion</th>
                <th className="pb-2 font-medium">Challenger</th>
                <th className="pb-2 font-medium">p-value</th>
                <th className="pb-2 font-medium">Outcome</th>
              </tr>
            </thead>
            <tbody>
              {abTests.map((run) => (
                <tr key={run.id} className="border-b border-gray-50 text-gray-700">
                  <td className="py-2 text-gray-500">{run.start_time.slice(0, 10)}</td>
                  <td className="py-2">{((run.champion_win_rate ?? 0) * 100).toFixed(1)}%</td>
                  <td className="py-2">{((run.challenger_win_rate ?? 0) * 100).toFixed(1)}%</td>
                  <td className="py-2 text-gray-500">{run.p_value?.toFixed(4) ?? "—"}</td>
                  <td className={`py-2 font-semibold ${
                    run.outcome === "CHALLENGER_APPLIED" ? "text-green-600" : "text-gray-500"
                  }`}>
                    {run.outcome ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Recent Decision Log */}
      <div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm">
        <h2 className="text-base font-semibold text-gray-900 mb-4">Recent Decisions</h2>
        <div className="space-y-2 max-h-80 overflow-y-auto">
          {decisions.slice(0, 20).map((d) => (
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
              <p className="text-gray-500 text-xs leading-relaxed">{d.narrative}</p>
            </div>
          ))}
          {decisions.length === 0 && (
            <p className="text-gray-400 text-center py-6 text-sm">No decisions logged yet</p>
          )}
        </div>
      </div>
    </div>
  );
}
