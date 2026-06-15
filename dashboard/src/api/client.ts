// dashboard/src/api/client.ts
import axios from "axios";
import { useQuery, useMutation } from "@tanstack/react-query";

// Attach X-API-Key when VITE_API_KEY is configured (required for control
// endpoints when the backend has API_KEY set). Empty/undefined → header omitted.
const apiKey = import.meta.env.VITE_API_KEY;
const api = axios.create({
  baseURL: "/api",
  headers: apiKey ? { "X-API-Key": apiKey } : {},
});

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

export type Decision = {
  id: string;
  timestamp: string;
  symbol: string;
  strategy_id: string;
  signal_side: string;
  confidence: number;
  narrative: string;
  final_decision: string;
  rejection_reason: string | null;
  entry_price: number;
};

export interface StrategyHealth {
  win_rate_30: number;
  total_outcomes: number;
  avg_pnl: number;
  confidence_calibration: number;
}

export interface ABTestRun {
  id: string;
  start_time: string;
  end_time: string | null;
  champion_id: string;
  challenger_id: string;
  champion_win_rate: number | null;
  challenger_win_rate: number | null;
  p_value: number | null;
  outcome: string | null;
  notes: string | null;
}

export function useDecisionLog(limit = 50) {
  return useQuery<Decision[]>({
    queryKey: ["decisions", limit],
    queryFn: () =>
      api.get("/decisions", { params: { limit } }).then((r) => r.data.decisions),
    refetchInterval: 30_000,
  });
}

export function useStrategyHealth() {
  return useQuery<StrategyHealth>({
    queryKey: ["strategy-health"],
    queryFn: () => fetch("/api/health/strategy").then((r) => r.json()),
    refetchInterval: 60_000,
  });
}

export function useABTests() {
  return useQuery<ABTestRun[]>({
    queryKey: ["ab-tests"],
    queryFn: () => fetch("/api/ab-tests").then((r) => r.json()),
    refetchInterval: 120_000,
  });
}

export interface StrategyProfile {
  strategy_id: string; regime: string;
  win_rate: number; avg_pnl: number; sample_count: number;
}
export interface StrategySwitch {
  id: string; timestamp: string; regime: string;
  from_strategy: string; to_strategy: string; decision: string; reason: string;
}
export function useStrategyProfiles() {
  return useQuery<StrategyProfile[]>({
    queryKey: ["strategy-profiles"],
    queryFn: () => fetch("/api/strategy-profiles").then((r) => r.json()),
    refetchInterval: 60_000,
  });
}
export function useStrategySwitches() {
  return useQuery<StrategySwitch[]>({
    queryKey: ["strategy-switches"],
    queryFn: () => fetch("/api/strategy-switches").then((r) => r.json()),
    refetchInterval: 60_000,
  });
}
