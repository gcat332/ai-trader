// dashboard/src/pages/LiveTrading.tsx
import { useEffect, useRef, useState } from "react";
import { usePnl, useStrategies, useStartStrategy, useStopStrategy, useTradeHistory } from "../api/client";
import { EquityChart } from "../components/EquityChart";
import { TradeTable } from "../components/TradeTable";
import { StatCard } from "../components/StatCard";

export default function LiveTrading() {
  const { data: pnl } = usePnl();
  const { data: strategies, refetch } = useStrategies();
  const { data: trades = [] } = useTradeHistory();
  const startStrategy = useStartStrategy();
  const stopStrategy = useStopStrategy();
  const [lastPrice, setLastPrice] = useState<string>("—");
  const wsRef = useRef<WebSocket | null>(null);
  const unmountedRef = useRef(false);

  useEffect(() => {
    unmountedRef.current = false;

    const connect = () => {
      if (unmountedRef.current) return;
      const ws = new WebSocket(`ws://${window.location.host}/ws/feed`);
      ws.onmessage = (e) => {
        const event = JSON.parse(e.data);
        // Ignore heartbeat messages; only update price when event.price exists
        if (event.price) setLastPrice(`$${Number(event.price).toLocaleString()}`);
      };
      ws.onclose = () => {
        // Auto-reconnect after 3s, but only if component is still mounted
        if (!unmountedRef.current) {
          setTimeout(connect, 3000);
        }
      };
      wsRef.current = ws;
    };

    connect();

    return () => {
      unmountedRef.current = true;
      wsRef.current?.close();
    };
  }, []);

  let cumulative = 0;
  const equityData = trades.map((t) => {
    cumulative += t.realized_pnl;
    return { time: t.exit_time.slice(0, 10), cumulative_pnl: cumulative };
  });

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-gray-900">Live Trading</h1>

      <div className="grid grid-cols-3 gap-4">
        <StatCard label="Total PnL" value={`$${(pnl?.total ?? 0).toFixed(2)}`} />
        <StatCard label="Daily PnL" value={`$${(pnl?.daily ?? 0).toFixed(2)}`} />
        <StatCard label="Last Price" value={lastPrice} />
      </div>

      <div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm">
        <h2 className="text-base font-semibold text-gray-900 mb-3">Equity Curve</h2>
        <EquityChart data={equityData} />
      </div>

      <div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm">
        <h2 className="text-base font-semibold text-gray-900 mb-3">Strategies</h2>
        <div className="flex flex-col gap-3">
          {strategies?.map((s) => (
            <div key={s.id} className="flex items-center justify-between py-2 border-b border-gray-100 last:border-0">
              <div>
                <span className="font-semibold text-gray-900 text-sm">{s.id}</span>
                <span className={`ml-2 text-xs px-2 py-0.5 rounded-full ${s.status === "running" ? "bg-green-100 text-green-600" : "bg-gray-100 text-gray-500"}`}>
                  {s.status}
                </span>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => { startStrategy.mutate(s.id); refetch(); }}
                  className="px-4 py-1.5 bg-green-500 hover:bg-green-600 text-white rounded-full text-xs font-semibold transition-colors"
                >Start</button>
                <button
                  onClick={() => { stopStrategy.mutate(s.id); refetch(); }}
                  className="px-4 py-1.5 bg-red-500 hover:bg-red-600 text-white rounded-full text-xs font-semibold transition-colors"
                >Stop</button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm">
        <h2 className="text-base font-semibold text-gray-900 mb-3">Recent Trades</h2>
        <TradeTable trades={trades.slice(0, 10)} />
      </div>
    </div>
  );
}
