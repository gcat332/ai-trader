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
