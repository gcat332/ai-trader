// dashboard/src/pages/Compare.tsx
import { useState } from "react";
import { useCompare } from "../api/client";
import { EquityChart } from "../components/EquityChart";
import { StatCard } from "../components/StatCard";

export default function Compare() {
  const [strategy, setStrategy] = useState("rsi_macd");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const { data } = useCompare(submitted ? strategy : "", fromDate, toDate);

  const liveTrades: any[] = data?.live_trades ?? [];
  const backtestRuns: any[] = data?.backtest_runs ?? [];

  let liveCumulative = 0;
  const equityData = liveTrades.map((t: any, i: number) => {
    liveCumulative += t.realized_pnl;
    const matchingRun = backtestRuns[0];
    return {
      time: t.exit_time?.slice(0, 10) ?? `t${i}`,
      cumulative_pnl: liveCumulative,
      backtest_pnl: matchingRun ? (matchingRun.total_pnl / liveTrades.length) * (i + 1) : undefined,
    };
  });

  const latestRun = backtestRuns[0];

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-gray-900">Compare</h1>

      <div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm">
        <h2 className="text-base font-semibold text-gray-900 mb-3">Compare Parameters</h2>
        <div className="flex flex-wrap gap-3 items-end">
          <div>
            <label className="text-xs text-gray-500 block mb-1">Strategy</label>
            <select value={strategy} onChange={(e) => setStrategy(e.target.value)}
              className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="rsi_macd">rsi_macd</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">From</label>
            <input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)}
              className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">To</label>
            <input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)}
              className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <button onClick={() => setSubmitted(true)}
            className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-full text-sm font-semibold transition-colors">
            Compare
          </button>
        </div>
      </div>

      {submitted && (
        <>
          <div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm">
            <h2 className="text-base font-semibold text-gray-900 mb-1">Equity Curve</h2>
            <p className="text-xs text-gray-400 mb-3">
              <span className="text-green-500">—</span> Live &nbsp;
              <span className="text-indigo-400">- -</span> Backtest
            </p>
            <EquityChart data={equityData} showBacktest />
            {/* TODO: replace synthetic projection with real per-trade backtest equity from /api/compare */}
            <p className="text-xs text-gray-400 mt-2">
              Note: the backtest line is a linear projection of total PnL, not a per-trade equity curve.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm">
              <h2 className="text-base font-semibold text-gray-900 mb-3">Live</h2>
              <div className="grid grid-cols-2 gap-3">
                <StatCard label="Trades" value={String(liveTrades.length)} />
                <StatCard label="Total PnL" value={`$${liveCumulative.toFixed(2)}`} />
              </div>
            </div>
            {latestRun && (
              <div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm">
                <h2 className="text-base font-semibold text-gray-900 mb-3">Backtest</h2>
                <div className="grid grid-cols-2 gap-3">
                  <StatCard label="Trades" value={String(latestRun.total_trades)} />
                  <StatCard label="Total PnL" value={`$${latestRun.total_pnl.toFixed(2)}`} />
                  <StatCard label="Sharpe" value={latestRun.sharpe_ratio.toFixed(2)} />
                  <StatCard label="Win Rate" value={`${(latestRun.win_rate * 100).toFixed(1)}%`} />
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
