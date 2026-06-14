// dashboard/src/components/TradeTable.tsx
import type { Trade } from "../api/client";

export function TradeTable({ trades }: { trades: Trade[] }) {
  if (trades.length === 0) return <p className="text-gray-500 text-center py-4">No trades</p>;

  return (
    <table className="w-full text-sm text-left">
      <thead className="text-xs text-gray-400 uppercase tracking-wide border-b border-gray-200">
        <tr>
          <th className="py-2 pr-4 font-normal">Symbol</th>
          <th className="py-2 pr-4 font-normal">Side</th>
          <th className="py-2 pr-4 font-normal">Entry</th>
          <th className="py-2 pr-4 font-normal">Exit</th>
          <th className="py-2 pr-4 font-normal">PnL</th>
          <th className="py-2 font-normal">Reason</th>
        </tr>
      </thead>
      <tbody>
        {trades.map((t) => (
          <tr key={t.id} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
            <td className="py-3 pr-4 font-semibold text-gray-900">{t.symbol}</td>
            <td className={`py-3 pr-4 font-medium ${t.side === "BUY" ? "text-green-500" : "text-red-500"}`}>{t.side}</td>
            <td className="py-3 pr-4 font-medium text-gray-700">${t.entry_price.toLocaleString()}</td>
            <td className="py-3 pr-4 font-medium text-gray-700">${t.exit_price.toLocaleString()}</td>
            <td className={`py-3 pr-4 font-semibold ${t.realized_pnl >= 0 ? "text-green-500" : "text-red-500"}`}>
              {t.realized_pnl >= 0 ? "+" : ""}${t.realized_pnl.toFixed(2)}
            </td>
            <td className="py-3 text-gray-400 text-xs">{t.exit_reason}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
