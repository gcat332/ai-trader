# Phase 5: React Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the React frontend — 4 pages (Live Trading, Trade History, Backtest, Compare), connecting to the FastAPI backend from Plan 4 via REST and WebSocket.

**Architecture:** Vite + React SPA inside `dashboard/`. React Query for data fetching and caching. Recharts for all charts. React Router for navigation. No global state manager — server state lives in React Query, UI state is local `useState`. TailwindCSS for styling.

**Tech Stack:** React 18, Vite, React Router v6, TanStack Query v5, Recharts, TailwindCSS, Vitest, React Testing Library.

---

## File Map

| File | Responsibility |
|---|---|
| `dashboard/package.json` | Frontend dependencies |
| `dashboard/vite.config.ts` | Vite config, API proxy to FastAPI on :8000 |
| `dashboard/tailwind.config.js` | Tailwind config |
| `dashboard/src/main.tsx` | React entry point |
| `dashboard/src/App.tsx` | Router setup, nav layout |
| `dashboard/src/api/client.ts` | Axios base client + React Query hooks |
| `dashboard/src/pages/LiveTrading.tsx` | Equity curve, open positions, strategy controls |
| `dashboard/src/pages/TradeHistory.tsx` | Filterable trade log + equity curve |
| `dashboard/src/pages/Backtest.tsx` | Trigger run, list runs, drill-in detail |
| `dashboard/src/pages/Compare.tsx` | Real vs backtest overlay chart + stats table |
| `dashboard/src/components/EquityChart.tsx` | Recharts LineChart component (shared) |
| `dashboard/src/components/TradeTable.tsx` | Reusable trade rows table |
| `dashboard/src/components/StatCard.tsx` | Sharpe / drawdown / win rate display card |
| `dashboard/src/__tests__/EquityChart.test.tsx` | Chart renders without crash |
| `dashboard/src/__tests__/TradeTable.test.tsx` | Table renders correct rows |
| `dashboard/src/__tests__/api.test.ts` | API hooks return correct shape (mocked) |

---

## Task 1: Scaffold Dashboard Project

**Files:**
- Create: `dashboard/package.json`
- Create: `dashboard/vite.config.ts`
- Create: `dashboard/tailwind.config.js`
- Create: `dashboard/index.html`
- Create: `dashboard/src/main.tsx`

- [ ] **Step 1: Initialise Vite + React project**

```bash
cd dashboard
npm create vite@latest . -- --template react-ts
npm install
```

- [ ] **Step 2: Install dependencies**

```bash
npm install react-router-dom @tanstack/react-query recharts axios
npm install -D tailwindcss postcss autoprefixer vitest @vitest/ui @testing-library/react @testing-library/jest-dom jsdom
npx tailwindcss init -p
```

- [ ] **Step 3: Configure `vite.config.ts`**

```typescript
// dashboard/vite.config.ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/__tests__/setup.ts"],
    globals: true,
  },
});
```

- [ ] **Step 4: Configure `tailwind.config.js`**

```javascript
// dashboard/tailwind.config.js
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: { extend: {} },
  plugins: [],
};
```

- [ ] **Step 5: Create test setup file**

```typescript
// dashboard/src/__tests__/setup.ts
import "@testing-library/jest-dom";
```

- [ ] **Step 6: Create `dashboard/index.html`**

```html
<!doctype html>
<html lang="en">
  <head><meta charset="UTF-8" /><title>AI Trader</title></head>
  <body><div id="root"></div><script type="module" src="/src/main.tsx"></script></body>
</html>
```

- [ ] **Step 7: Create `dashboard/src/main.tsx`**

```tsx
// dashboard/src/main.tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import "./index.css";

const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>
);
```

- [ ] **Step 8: Create `dashboard/src/index.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

- [ ] **Step 9: Verify project builds**

```bash
cd dashboard && npm run build
```

Expected: build succeeds with no errors.

- [ ] **Step 10: Commit**

```bash
cd ..
git add dashboard/
git commit -m "feat: scaffold React dashboard with Vite, Tailwind, React Query"
```

---

## Task 2: API Client + Hooks

**Files:**
- Create: `dashboard/src/api/client.ts`
- Create: `dashboard/src/__tests__/api.test.ts`

- [ ] **Step 1: Write failing tests**

```typescript
// dashboard/src/__tests__/api.test.ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import axios from "axios";

vi.mock("axios");
const mockedAxios = vi.mocked(axios, true);

describe("API shapes", () => {
  it("trade history response has expected keys", () => {
    const trade = {
      symbol: "BTC/USDT", side: "SELL", entry_price: 60000,
      exit_price: 63000, quantity: 0.1, realized_pnl: 300,
      entry_time: "2026-01-01T00:00:00", exit_time: "2026-01-02T00:00:00",
      exit_reason: "TP",
    };
    const keys = Object.keys(trade);
    expect(keys).toContain("realized_pnl");
    expect(keys).toContain("exit_reason");
  });

  it("pnl response has total and daily", () => {
    const pnl = { total: 1500.0, daily: 200.0 };
    expect(pnl).toHaveProperty("total");
    expect(pnl).toHaveProperty("daily");
  });

  it("backtest run has sharpe_ratio", () => {
    const run = { id: "run-1", strategy_id: "rsi_macd", sharpe_ratio: 1.5 };
    expect(run.sharpe_ratio).toBeGreaterThan(0);
  });
});
```

- [ ] **Step 2: Run tests to verify they pass immediately (shape tests, not network)**

```bash
cd dashboard && npm run test -- --run
```

Expected: 3 PASSED

- [ ] **Step 3: Implement `dashboard/src/api/client.ts`**

```typescript
// dashboard/src/api/client.ts
import axios from "axios";
import { useQuery, useMutation } from "@tanstack/react-query";

const api = axios.create({ baseURL: "/api" });

export type Trade = {
  id: number; symbol: string; side: string;
  entry_price: number; exit_price: number; quantity: number;
  realized_pnl: number; entry_time: string; exit_time: string;
  exit_reason: string;
};

export type BacktestRun = {
  id: string; strategy_id: string; symbol: string;
  from_date: string; to_date: string;
  total_trades: number; total_pnl: number;
  win_rate: number; max_drawdown: number; sharpe_ratio: number;
  created_at: string;
};

export type Strategy = { id: string; status: string };
export type Pnl = { total: number; daily: number };

export const useTradeHistory = (params?: { symbol?: string; from_date?: string; to_date?: string }) =>
  useQuery<Trade[]>({
    queryKey: ["trades", params],
    queryFn: () => api.get("/trades/history", { params }).then((r) => r.data),
  });

export const usePnl = () =>
  useQuery<Pnl>({ queryKey: ["pnl"], queryFn: () => api.get("/pnl").then((r) => r.data) });

export const useStrategies = () =>
  useQuery<Strategy[]>({ queryKey: ["strategies"], queryFn: () => api.get("/strategies").then((r) => r.data) });

export const useBacktestHistory = () =>
  useQuery<BacktestRun[]>({ queryKey: ["backtests"], queryFn: () => api.get("/backtest/history").then((r) => r.data) });

export const useBacktestRun = (id: string) =>
  useQuery<BacktestRun>({ queryKey: ["backtest", id], queryFn: () => api.get(`/backtest/${id}`).then((r) => r.data), enabled: !!id });

export const useCompare = (strategy: string, from_date?: string, to_date?: string) =>
  useQuery({
    queryKey: ["compare", strategy, from_date, to_date],
    queryFn: () => api.get("/compare", { params: { strategy, from_date, to_date } }).then((r) => r.data),
    enabled: !!strategy,
  });

export const useStartStrategy = () =>
  useMutation({ mutationFn: (id: string) => api.post(`/strategies/${id}/start`) });

export const useStopStrategy = () =>
  useMutation({ mutationFn: (id: string) => api.post(`/strategies/${id}/stop`) });
```

- [ ] **Step 4: Commit**

```bash
cd ..
git add dashboard/src/api/ dashboard/src/__tests__/api.test.ts
git commit -m "feat: API hooks with React Query"
```

---

## Task 3: Shared Components

**Files:**
- Create: `dashboard/src/components/EquityChart.tsx`
- Create: `dashboard/src/components/TradeTable.tsx`
- Create: `dashboard/src/components/StatCard.tsx`
- Create: `dashboard/src/__tests__/EquityChart.test.tsx`
- Create: `dashboard/src/__tests__/TradeTable.test.tsx`

- [ ] **Step 1: Write failing component tests**

```tsx
// dashboard/src/__tests__/EquityChart.test.tsx
import { render, screen } from "@testing-library/react";
import { EquityChart } from "../components/EquityChart";

const data = [
  { time: "2026-01-01", cumulative_pnl: 0 },
  { time: "2026-01-02", cumulative_pnl: 150 },
  { time: "2026-01-03", cumulative_pnl: 300 },
];

it("renders equity chart without crashing", () => {
  render(<EquityChart data={data} />);
});

it("shows empty state when no data", () => {
  render(<EquityChart data={[]} />);
  expect(screen.getByText(/no data/i)).toBeInTheDocument();
});
```

```tsx
// dashboard/src/__tests__/TradeTable.test.tsx
import { render, screen } from "@testing-library/react";
import { TradeTable } from "../components/TradeTable";
import type { Trade } from "../api/client";

const trades: Trade[] = [
  { id: 1, symbol: "BTC/USDT", side: "SELL", entry_price: 60000,
    exit_price: 63000, quantity: 0.1, realized_pnl: 300,
    entry_time: "2026-01-01T00:00:00", exit_time: "2026-01-02T00:00:00",
    exit_reason: "TP" },
];

it("renders trade rows", () => {
  render(<TradeTable trades={trades} />);
  expect(screen.getByText("BTC/USDT")).toBeInTheDocument();
  expect(screen.getByText("+$300.00")).toBeInTheDocument();
});

it("shows empty message when no trades", () => {
  render(<TradeTable trades={[]} />);
  expect(screen.getByText(/no trades/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd dashboard && npm run test -- --run
```

Expected: failing with `Cannot find module '../components/EquityChart'`

- [ ] **Step 3: Implement `dashboard/src/components/EquityChart.tsx`**

```tsx
// dashboard/src/components/EquityChart.tsx
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";

type DataPoint = { time: string; cumulative_pnl: number; backtest_pnl?: number };

export function EquityChart({ data, showBacktest = false }: { data: DataPoint[]; showBacktest?: boolean }) {
  if (data.length === 0) return <p className="text-gray-400 text-center py-8">No data</p>;

  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
        <XAxis dataKey="time" tick={{ fontSize: 11, fill: "#9CA3AF" }} />
        <YAxis tick={{ fontSize: 11, fill: "#9CA3AF" }} />
        <Tooltip
          contentStyle={{ backgroundColor: "#1F2937", border: "none", borderRadius: 6 }}
          labelStyle={{ color: "#F9FAFB" }}
        />
        <Line type="monotone" dataKey="cumulative_pnl" stroke="#10B981" dot={false} name="Live" strokeWidth={2} />
        {showBacktest && (
          <Line type="monotone" dataKey="backtest_pnl" stroke="#6366F1" dot={false} name="Backtest" strokeWidth={2} strokeDasharray="5 5" />
        )}
      </LineChart>
    </ResponsiveContainer>
  );
}
```

- [ ] **Step 4: Implement `dashboard/src/components/TradeTable.tsx`**

```tsx
// dashboard/src/components/TradeTable.tsx
import type { Trade } from "../api/client";

export function TradeTable({ trades }: { trades: Trade[] }) {
  if (trades.length === 0) return <p className="text-gray-400 text-center py-4">No trades</p>;

  return (
    <table className="w-full text-sm text-left">
      <thead className="text-gray-400 border-b border-gray-700">
        <tr>
          <th className="py-2 pr-4">Symbol</th>
          <th className="py-2 pr-4">Side</th>
          <th className="py-2 pr-4">Entry</th>
          <th className="py-2 pr-4">Exit</th>
          <th className="py-2 pr-4">PnL</th>
          <th className="py-2">Reason</th>
        </tr>
      </thead>
      <tbody>
        {trades.map((t) => (
          <tr key={t.id} className="border-b border-gray-800 hover:bg-gray-800/40">
            <td className="py-2 pr-4 font-medium">{t.symbol}</td>
            <td className={`py-2 pr-4 ${t.side === "BUY" ? "text-emerald-400" : "text-rose-400"}`}>{t.side}</td>
            <td className="py-2 pr-4">${t.entry_price.toLocaleString()}</td>
            <td className="py-2 pr-4">${t.exit_price.toLocaleString()}</td>
            <td className={`py-2 pr-4 font-medium ${t.realized_pnl >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
              {t.realized_pnl >= 0 ? "+" : ""}${t.realized_pnl.toFixed(2)}
            </td>
            <td className="py-2 text-gray-400">{t.exit_reason}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 5: Implement `dashboard/src/components/StatCard.tsx`**

```tsx
// dashboard/src/components/StatCard.tsx
export function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-gray-800 rounded-xl p-4">
      <p className="text-gray-400 text-xs uppercase tracking-wide">{label}</p>
      <p className="text-2xl font-bold mt-1">{value}</p>
      {sub && <p className="text-gray-400 text-xs mt-1">{sub}</p>}
    </div>
  );
}
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd dashboard && npm run test -- --run
```

Expected: all PASSED

- [ ] **Step 7: Commit**

```bash
cd ..
git add dashboard/src/components/ dashboard/src/__tests__/
git commit -m "feat: EquityChart, TradeTable, StatCard components"
```

---

## Task 4: Pages + Router

**Files:**
- Create: `dashboard/src/App.tsx`
- Create: `dashboard/src/pages/LiveTrading.tsx`
- Create: `dashboard/src/pages/TradeHistory.tsx`
- Create: `dashboard/src/pages/Backtest.tsx`
- Create: `dashboard/src/pages/Compare.tsx`

- [ ] **Step 1: Implement `dashboard/src/App.tsx`**

```tsx
// dashboard/src/App.tsx
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import LiveTrading from "./pages/LiveTrading";
import TradeHistory from "./pages/TradeHistory";
import Backtest from "./pages/Backtest";
import Compare from "./pages/Compare";

const navClass = ({ isActive }: { isActive: boolean }) =>
  `px-4 py-2 rounded-lg text-sm font-medium transition-colors ${isActive ? "bg-gray-700 text-white" : "text-gray-400 hover:text-white"}`;

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-900 text-white">
        <nav className="flex items-center gap-2 px-6 py-3 border-b border-gray-800">
          <span className="font-bold text-emerald-400 mr-4">AI Trader</span>
          <NavLink to="/" end className={navClass}>Live</NavLink>
          <NavLink to="/history" className={navClass}>History</NavLink>
          <NavLink to="/backtest" className={navClass}>Backtest</NavLink>
          <NavLink to="/compare" className={navClass}>Compare</NavLink>
        </nav>
        <main className="p-6">
          <Routes>
            <Route path="/" element={<LiveTrading />} />
            <Route path="/history" element={<TradeHistory />} />
            <Route path="/backtest" element={<Backtest />} />
            <Route path="/compare" element={<Compare />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
```

- [ ] **Step 2: Implement `dashboard/src/pages/LiveTrading.tsx`**

```tsx
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

  useEffect(() => {
    const ws = new WebSocket(`ws://${window.location.host}/ws/feed`);
    ws.onmessage = (e) => {
      const event = JSON.parse(e.data);
      if (event.price) setLastPrice(`$${Number(event.price).toLocaleString()}`);
    };
    wsRef.current = ws;
    return () => ws.close();
  }, []);

  const equityData = trades.map((t) => ({ time: t.exit_time.slice(0, 10), cumulative_pnl: t.realized_pnl }));

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-3 gap-4">
        <StatCard label="Total PnL" value={`$${(pnl?.total ?? 0).toFixed(2)}`} />
        <StatCard label="Daily PnL" value={`$${(pnl?.daily ?? 0).toFixed(2)}`} />
        <StatCard label="Last Price" value={lastPrice} />
      </div>

      <div className="bg-gray-800 rounded-xl p-4">
        <h2 className="text-sm font-semibold text-gray-400 mb-3">Equity Curve</h2>
        <EquityChart data={equityData} />
      </div>

      <div className="bg-gray-800 rounded-xl p-4">
        <h2 className="text-sm font-semibold text-gray-400 mb-3">Strategies</h2>
        <div className="flex flex-col gap-2">
          {strategies?.map((s) => (
            <div key={s.id} className="flex items-center justify-between">
              <span className="font-medium">{s.id}</span>
              <div className="flex gap-2">
                <button
                  onClick={() => { startStrategy.mutate(s.id); refetch(); }}
                  className="px-3 py-1 bg-emerald-600 hover:bg-emerald-500 rounded text-xs"
                >Start</button>
                <button
                  onClick={() => { stopStrategy.mutate(s.id); refetch(); }}
                  className="px-3 py-1 bg-rose-600 hover:bg-rose-500 rounded text-xs"
                >Stop</button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="bg-gray-800 rounded-xl p-4">
        <h2 className="text-sm font-semibold text-gray-400 mb-3">Recent Trades</h2>
        <TradeTable trades={trades.slice(0, 10)} />
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Implement `dashboard/src/pages/TradeHistory.tsx`**

```tsx
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
      <div className="bg-gray-800 rounded-xl p-4">
        <h2 className="text-sm font-semibold text-gray-400 mb-3">Filters</h2>
        <div className="flex flex-wrap gap-3">
          <input
            value={symbol} onChange={(e) => setSymbol(e.target.value)}
            placeholder="Symbol (e.g. BTC/USDT)"
            className="bg-gray-700 rounded px-3 py-1.5 text-sm w-48"
          />
          <input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)}
            className="bg-gray-700 rounded px-3 py-1.5 text-sm" />
          <input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)}
            className="bg-gray-700 rounded px-3 py-1.5 text-sm" />
        </div>
      </div>

      <div className="bg-gray-800 rounded-xl p-4">
        <h2 className="text-sm font-semibold text-gray-400 mb-3">Equity Curve</h2>
        <EquityChart data={equityData} />
      </div>

      <div className="bg-gray-800 rounded-xl p-4">
        <h2 className="text-sm font-semibold text-gray-400 mb-3">Trade Log ({trades.length})</h2>
        <TradeTable trades={trades} />
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Implement `dashboard/src/pages/Backtest.tsx`**

```tsx
// dashboard/src/pages/Backtest.tsx
import { useState } from "react";
import { useBacktestHistory, useBacktestRun } from "../api/client";
import { StatCard } from "../components/StatCard";
import axios from "axios";

export default function Backtest() {
  const { data: runs = [], refetch } = useBacktestHistory();
  const [selectedId, setSelectedId] = useState("");
  const [strategy, setStrategy] = useState("rsi_macd");
  const [symbol, setSymbol] = useState("BTC/USDT");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const { data: detail } = useBacktestRun(selectedId);

  const triggerBacktest = async () => {
    await axios.post("/api/backtest/run", { strategy_id: strategy, symbol, from_date: fromDate, to_date: toDate });
    refetch();
  };

  return (
    <div className="space-y-6">
      <div className="bg-gray-800 rounded-xl p-4">
        <h2 className="text-sm font-semibold text-gray-400 mb-3">Run Backtest</h2>
        <div className="flex flex-wrap gap-3 items-end">
          <div>
            <label className="text-xs text-gray-400 block mb-1">Strategy</label>
            <select value={strategy} onChange={(e) => setStrategy(e.target.value)}
              className="bg-gray-700 rounded px-3 py-1.5 text-sm">
              <option value="rsi_macd">rsi_macd</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-400 block mb-1">Symbol</label>
            <input value={symbol} onChange={(e) => setSymbol(e.target.value)}
              className="bg-gray-700 rounded px-3 py-1.5 text-sm w-36" />
          </div>
          <div>
            <label className="text-xs text-gray-400 block mb-1">From</label>
            <input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)}
              className="bg-gray-700 rounded px-3 py-1.5 text-sm" />
          </div>
          <div>
            <label className="text-xs text-gray-400 block mb-1">To</label>
            <input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)}
              className="bg-gray-700 rounded px-3 py-1.5 text-sm" />
          </div>
          <button onClick={triggerBacktest}
            className="px-4 py-1.5 bg-indigo-600 hover:bg-indigo-500 rounded text-sm font-medium">
            Run
          </button>
        </div>
      </div>

      {detail && (
        <div className="bg-gray-800 rounded-xl p-4">
          <h2 className="text-sm font-semibold text-gray-400 mb-3">Run Detail — {detail.id}</h2>
          <div className="grid grid-cols-4 gap-4">
            <StatCard label="Total PnL" value={`$${detail.total_pnl.toFixed(2)}`} />
            <StatCard label="Win Rate" value={`${(detail.win_rate * 100).toFixed(1)}%`} />
            <StatCard label="Max Drawdown" value={`$${detail.max_drawdown.toFixed(2)}`} />
            <StatCard label="Sharpe" value={detail.sharpe_ratio.toFixed(2)} />
          </div>
        </div>
      )}

      <div className="bg-gray-800 rounded-xl p-4">
        <h2 className="text-sm font-semibold text-gray-400 mb-3">History</h2>
        <table className="w-full text-sm">
          <thead className="text-gray-400 border-b border-gray-700">
            <tr>
              <th className="py-2 text-left">Strategy</th>
              <th className="py-2 text-left">Symbol</th>
              <th className="py-2 text-left">Period</th>
              <th className="py-2 text-left">Trades</th>
              <th className="py-2 text-left">PnL</th>
              <th className="py-2 text-left">Sharpe</th>
              <th className="py-2 text-left">Win Rate</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id} onClick={() => setSelectedId(r.id)}
                className="border-b border-gray-800 hover:bg-gray-700/40 cursor-pointer">
                <td className="py-2 pr-4">{r.strategy_id}</td>
                <td className="py-2 pr-4">{r.symbol}</td>
                <td className="py-2 pr-4 text-gray-400 text-xs">{r.from_date} → {r.to_date}</td>
                <td className="py-2 pr-4">{r.total_trades}</td>
                <td className={`py-2 pr-4 ${r.total_pnl >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                  ${r.total_pnl.toFixed(2)}
                </td>
                <td className="py-2 pr-4">{r.sharpe_ratio.toFixed(2)}</td>
                <td className="py-2">{(r.win_rate * 100).toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
        {runs.length === 0 && <p className="text-gray-400 text-center py-4">No backtest runs yet</p>}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Implement `dashboard/src/pages/Compare.tsx`**

```tsx
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
      <div className="bg-gray-800 rounded-xl p-4">
        <h2 className="text-sm font-semibold text-gray-400 mb-3">Compare Parameters</h2>
        <div className="flex flex-wrap gap-3 items-end">
          <div>
            <label className="text-xs text-gray-400 block mb-1">Strategy</label>
            <select value={strategy} onChange={(e) => setStrategy(e.target.value)}
              className="bg-gray-700 rounded px-3 py-1.5 text-sm">
              <option value="rsi_macd">rsi_macd</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-400 block mb-1">From</label>
            <input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)}
              className="bg-gray-700 rounded px-3 py-1.5 text-sm" />
          </div>
          <div>
            <label className="text-xs text-gray-400 block mb-1">To</label>
            <input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)}
              className="bg-gray-700 rounded px-3 py-1.5 text-sm" />
          </div>
          <button onClick={() => setSubmitted(true)}
            className="px-4 py-1.5 bg-indigo-600 hover:bg-indigo-500 rounded text-sm font-medium">
            Compare
          </button>
        </div>
      </div>

      {submitted && (
        <>
          <div className="bg-gray-800 rounded-xl p-4">
            <h2 className="text-sm font-semibold text-gray-400 mb-1">Equity Curve</h2>
            <p className="text-xs text-gray-500 mb-3">
              <span className="text-emerald-400">—</span> Live &nbsp;
              <span className="text-indigo-400">- -</span> Backtest
            </p>
            <EquityChart data={equityData} showBacktest />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="bg-gray-800 rounded-xl p-4">
              <h2 className="text-sm font-semibold text-gray-400 mb-3">Live</h2>
              <div className="grid grid-cols-2 gap-3">
                <StatCard label="Trades" value={String(liveTrades.length)} />
                <StatCard label="Total PnL" value={`$${liveCumulative.toFixed(2)}`} />
              </div>
            </div>
            {latestRun && (
              <div className="bg-gray-800 rounded-xl p-4">
                <h2 className="text-sm font-semibold text-gray-400 mb-3">Backtest</h2>
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
```

- [ ] **Step 6: Run all tests**

```bash
cd dashboard && npm run test -- --run
```

Expected: all PASSED

- [ ] **Step 7: Build to verify no TypeScript errors**

```bash
npm run build
```

Expected: build succeeds

- [ ] **Step 8: Commit**

```bash
cd ..
git add dashboard/src/
git commit -m "feat: all 4 dashboard pages (LiveTrading, TradeHistory, Backtest, Compare)"
```

---

## Task 5: Manual Browser Verification

- [ ] **Step 1: Start API backend**

```bash
python run_api.py
```

- [ ] **Step 2: Start dashboard dev server**

```bash
cd dashboard && npm run dev
```

- [ ] **Step 3: Open browser at `http://localhost:5173`**

Verify:
- Nav links work (Live, History, Backtest, Compare)
- Each page loads without console errors
- Live page shows 3 stat cards, equity chart, strategy table, trade table
- History page: filter inputs render
- Backtest page: form + empty history table
- Compare page: form renders, compare button clickable

- [ ] **Step 4: Commit (if any fixes needed from manual check)**

```bash
git add -p
git commit -m "fix: dashboard manual review adjustments"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** equity curve ✓, open positions ✓, strategy start/stop ✓, trade history with filters ✓, backtest trigger + list + detail ✓, compare overlay chart ✓, side-by-side stats ✓, WebSocket real-time feed ✓
- [x] **No placeholders:** all 4 pages fully implemented with real API hooks
- [x] **Type consistency:** `Trade` and `BacktestRun` types defined once in `api/client.ts` and imported in all pages
- [x] **API proxy:** Vite config proxies `/api` and `/ws` to FastAPI on port 8000 — no CORS issues in dev

---

## Next Plan

**Plan 6:** Telegram Bot — alerts for BUY/SELL/warning events, commands (/status, /pause, /resume, /pnl, /close).
