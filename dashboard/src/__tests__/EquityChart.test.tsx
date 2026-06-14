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
