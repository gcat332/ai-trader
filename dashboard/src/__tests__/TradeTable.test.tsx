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
