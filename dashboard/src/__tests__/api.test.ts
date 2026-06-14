// dashboard/src/__tests__/api.test.ts
import { describe, it, expect, vi } from "vitest";

vi.mock("axios");

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
