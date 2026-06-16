// dashboard/src/pages/LiveTrading.tsx
import { useEffect, useRef, useState } from "react";
import { usePnl, useStrategies, useStartStrategy, useStopStrategy, useTradeHistory, useDecisionLog, useStrategySwitches } from "../api/client";
import { EquityChart } from "../components/EquityChart";
import { TradeTable } from "../components/TradeTable";
import { StatCard } from "../components/StatCard";
import { DecisionFeed } from "../components/DecisionFeed";
import { useToast } from "../components/Toast";

export default function LiveTrading() {
  const { data: pnl } = usePnl();
  const { data: strategies, refetch } = useStrategies();
  // Engine controls act on the active technique (arbiter-managed in multi mode).
  const activeId = strategies?.find((s) => s.active)?.id ?? strategies?.[0]?.id ?? "";
  const { data: trades = [] } = useTradeHistory();
  const startStrategy = useStartStrategy();
  const stopStrategy = useStopStrategy();
  const toast = useToast();
  const { data: decisions = [] } = useDecisionLog();
  const { data: switches = [] } = useStrategySwitches();
  const engineRunning = strategies?.some((s) => s.status === "active") ?? false;
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 5000);
    return () => clearInterval(id);
  }, []);
  const lastTs = decisions[0]?.timestamp;
  const agoSec = lastTs ? Math.max(0, Math.round((now - new Date(lastTs).getTime()) / 1000)) : null;
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

      {/* AI status indicator */}
      <div className="flex items-center gap-4 text-sm">
        <span className="flex items-center gap-2">
          <span className={`w-2.5 h-2.5 rounded-full ${engineRunning ? "bg-green-500" : "bg-gray-400"}`} />
          <span className={engineRunning ? "text-gray-900 font-medium" : "text-gray-500"}>
            {engineRunning ? "Engine running" : "Engine stopped"}
          </span>
        </span>
        <span className="text-gray-500">
          AI last acted {agoSec !== null ? `${agoSec}s ago` : "—"}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <StatCard label="Total PnL" value={`$${(pnl?.total ?? 0).toFixed(2)}`} />
        <StatCard label="Daily PnL" value={`$${(pnl?.daily ?? 0).toFixed(2)}`} />
        <StatCard label="Last Price" value={lastPrice} />
      </div>

      <div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm">
        <h2 className="text-base font-semibold text-gray-900 mb-3">Equity Curve</h2>
        <EquityChart data={equityData} />
      </div>

      <DecisionFeed decisions={decisions} limit={8} title="AI Activity" />

      <div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm">
        <h2 className="text-base font-semibold text-gray-900 mb-3">Recent Strategy Switches</h2>
        {switches.slice(0, 3).map((sw) => (
          <div key={sw.id} className="text-xs text-gray-600 py-1 border-b border-gray-50 last:border-0">
            <span className="font-medium">{sw.decision}</span> · {sw.regime} — {sw.from_strategy} → {sw.to_strategy}
            <span className="text-gray-400 ml-2">{new Date(sw.timestamp).toLocaleString()}</span>
          </div>
        ))}
        {switches.length === 0 && <p className="text-gray-400 text-xs py-2">No strategy switches yet</p>}
      </div>

      <div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-semibold text-gray-900">
            Strategies
            {(strategies?.length ?? 0) > 1 && (
              <span className="ml-2 text-xs font-normal text-gray-400">multi · arbiter-managed</span>
            )}
          </h2>
          {/* One engine-level control — pause/resume the whole engine. The active
              technique is selected automatically by the arbiter in multi mode. */}
          <div className="flex gap-2">
            <button
              onClick={() => { startStrategy.mutate(activeId, { onSuccess: () => { refetch(); toast("Engine started", "success"); }, onError: (e) => toast((e as Error).message, "error") }); }}
              disabled={startStrategy.isPending}
              className="px-4 py-1.5 bg-green-500 hover:bg-green-600 text-white rounded-full text-xs font-semibold transition-colors disabled:opacity-50"
            >{startStrategy.isPending ? "Starting…" : "Start"}</button>
            <button
              onClick={() => {
                if (!window.confirm("Stop the trading engine? Open positions stay protected by their exchange-side OCO.")) return;
                stopStrategy.mutate(activeId, { onSuccess: () => { refetch(); toast("Engine stopped", "info"); }, onError: (e) => toast((e as Error).message, "error") });
              }}
              disabled={stopStrategy.isPending}
              className="px-4 py-1.5 bg-red-500 hover:bg-red-600 text-white rounded-full text-xs font-semibold transition-colors disabled:opacity-50"
            >{stopStrategy.isPending ? "Stopping…" : "Stop"}</button>
          </div>
        </div>
        {(startStrategy.error || stopStrategy.error) && (
          <p className="text-red-500 text-xs mt-1">{((startStrategy.error || stopStrategy.error) as Error).message}</p>
        )}
        <div className="flex flex-col gap-2">
          {strategies?.map((s) => (
            <div key={s.id} className="flex items-center justify-between py-2 border-b border-gray-100 last:border-0">
              <span className={`text-sm ${s.active ? "font-semibold text-gray-900" : "text-gray-500"}`}>
                {s.id}{s.active && <span className="ml-1 text-blue-500">●</span>}
              </span>
              <span className={`text-xs px-2 py-0.5 rounded-full ${
                s.status === "active" ? "bg-green-100 text-green-600"
                : s.status === "idle" ? "bg-gray-100 text-gray-500"
                : "bg-gray-100 text-gray-400"}`}>
                {s.status}
              </span>
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
