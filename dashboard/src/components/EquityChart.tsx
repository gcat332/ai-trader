// dashboard/src/components/EquityChart.tsx
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";

type DataPoint = { time: string; cumulative_pnl: number; backtest_pnl?: number };

export function EquityChart({ data, showBacktest = false }: { data: DataPoint[]; showBacktest?: boolean }) {
  if (data.length === 0) return <p className="text-gray-500 text-center py-8">No data</p>;

  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
        <XAxis dataKey="time" tick={{ fontSize: 11, fill: "#9CA3AF" }} />
        <YAxis tick={{ fontSize: 11, fill: "#9CA3AF" }} />
        <Tooltip
          contentStyle={{ backgroundColor: "#FFFFFF", border: "1px solid #E5E7EB", borderRadius: 6 }}
          labelStyle={{ color: "#111827" }}
        />
        <Line type="monotone" dataKey="cumulative_pnl" stroke="#22C55E" dot={false} name="Live" strokeWidth={2} />
        {showBacktest && (
          <Line type="monotone" dataKey="backtest_pnl" stroke="#6366F1" dot={false} name="Backtest" strokeWidth={2} strokeDasharray="5 5" />
        )}
      </LineChart>
    </ResponsiveContainer>
  );
}
