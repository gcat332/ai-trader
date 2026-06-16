// dashboard/src/pages/Backtest.tsx
import { useState } from "react";
import { useAvailableStrategies, useBacktestHistory, useBacktestRun, useRunBacktest } from "../api/client";
import { StatCard } from "../components/StatCard";
import { useToast } from "../components/Toast";

export default function Backtest() {
  const { data: runs = [], refetch } = useBacktestHistory();
  const { data: availableStrategies = ["rsi_macd"] } = useAvailableStrategies();
  const runBacktest = useRunBacktest();
  const toast = useToast();
  const [selectedId, setSelectedId] = useState("");
  const [strategy, setStrategy] = useState("rsi_macd");
  const [symbol, setSymbol] = useState("BTC/USDT");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const { data: detail } = useBacktestRun(selectedId);

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-gray-900">Backtest</h1>

      <div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm">
        <h2 className="text-base font-semibold text-gray-900 mb-3">Run Backtest</h2>
        <div className="flex flex-wrap gap-3 items-end">
          <div>
            <label className="text-xs text-gray-500 block mb-1">Strategy</label>
            <select value={strategy} onChange={(e) => setStrategy(e.target.value)}
              className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500">
              {availableStrategies.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">Symbol</label>
            <select value={symbol} onChange={(e) => setSymbol(e.target.value)}
              className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="BTC/USDT">BTC/USDT</option>
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
          <button
            onClick={() =>
              runBacktest.mutate(
                { strategy_id: strategy, symbol, from_date: fromDate, to_date: toDate },
                {
                  onSuccess: (data) => {
                    refetch();
                    setSelectedId(data.run_id);
                    if (data.candles === 0) {
                      toast("No candles in that date range — testnet history is limited, try recent dates", "error");
                    } else {
                      toast(`Backtest complete — ${data.candles} candles replayed`, "success");
                    }
                  },
                  onError: (e) => toast(`Backtest failed: ${(e as Error).message}`, "error"),
                },
              )
            }
            disabled={runBacktest.isPending}
            className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-full text-sm font-semibold transition-colors disabled:opacity-50">
            {runBacktest.isPending ? "Running…" : "Run"}
          </button>
        </div>
        {runBacktest.isError && (
          <p className="text-red-500 text-xs mt-2">{(runBacktest.error as Error)?.message}</p>
        )}
      </div>

      {detail && (
        <div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm">
          <h2 className="text-base font-semibold text-gray-900 mb-3">Run Detail — {detail.id}</h2>
          <div className="grid grid-cols-4 gap-4">
            <StatCard label="Total PnL" value={`$${detail.total_pnl.toFixed(2)}`} />
            <StatCard label="Win Rate" value={`${(detail.win_rate * 100).toFixed(1)}%`} />
            <StatCard label="Max Drawdown" value={`$${detail.max_drawdown.toFixed(2)}`} />
            <StatCard label="Sharpe" value={detail.sharpe_ratio.toFixed(2)} />
          </div>
        </div>
      )}

      <div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm">
        <h2 className="text-base font-semibold text-gray-900 mb-3">History</h2>
        <table className="w-full text-sm">
          <thead className="text-xs text-gray-400 uppercase tracking-wide border-b border-gray-200">
            <tr>
              <th className="py-2 text-left font-normal">Strategy</th>
              <th className="py-2 text-left font-normal">Symbol</th>
              <th className="py-2 text-left font-normal">Period</th>
              <th className="py-2 text-left font-normal">Trades</th>
              <th className="py-2 text-left font-normal">PnL</th>
              <th className="py-2 text-left font-normal">Sharpe</th>
              <th className="py-2 text-left font-normal">Win Rate</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id} onClick={() => setSelectedId(r.id)}
                className="border-b border-gray-100 hover:bg-gray-50 cursor-pointer transition-colors">
                <td className="py-3 pr-4 font-medium text-gray-700">{r.strategy_id}</td>
                <td className="py-3 pr-4 font-medium text-gray-700">{r.symbol}</td>
                <td className="py-3 pr-4 text-gray-400 text-xs">{r.from_date} → {r.to_date}</td>
                <td className="py-3 pr-4 font-medium text-gray-700">{r.total_trades}</td>
                <td className={`py-3 pr-4 font-semibold ${r.total_pnl >= 0 ? "text-green-500" : "text-red-500"}`}>
                  ${r.total_pnl.toFixed(2)}
                </td>
                <td className="py-3 pr-4 font-medium text-gray-700">{r.sharpe_ratio.toFixed(2)}</td>
                <td className="py-3 font-medium text-gray-700">{(r.win_rate * 100).toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
        {runs.length === 0 && <p className="text-gray-500 text-center py-4">No backtest runs yet</p>}
      </div>
    </div>
  );
}
