// dashboard/src/pages/TradeHistory.tsx
import { useState } from "react";
import { useTradeHistory } from "../api/client";
import { TradeTable } from "../components/TradeTable";
import { EquityChart } from "../components/EquityChart";

export default function TradeHistory() {
  const [symbol, setSymbol] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const { data: trades = [] } = useTradeHistory({
    symbol: symbol || undefined,
    from_date: fromDate || undefined,
    to_date: toDate || undefined,
  });

  let cumulative = 0;
  const equityData = trades.map((t) => {
    cumulative += t.realized_pnl;
    return { time: t.exit_time.slice(0, 10), cumulative_pnl: cumulative };
  });

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-gray-900">Trade History</h1>

      <div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm">
        <h2 className="text-base font-semibold text-gray-900 mb-3">Filters</h2>
        <div className="flex flex-wrap gap-3">
          <input
            value={symbol} onChange={(e) => setSymbol(e.target.value)}
            placeholder="Symbol (e.g. BTC/USDT)"
            className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700 w-48 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)}
            className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500" />
          <input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)}
            className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
      </div>

      <div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm">
        <h2 className="text-base font-semibold text-gray-900 mb-3">Equity Curve</h2>
        <EquityChart data={equityData} />
      </div>

      <div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm">
        <h2 className="text-base font-semibold text-gray-900 mb-3">Trade Log ({trades.length})</h2>
        <TradeTable trades={trades} />
      </div>
    </div>
  );
}
