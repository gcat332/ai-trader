// dashboard/src/App.tsx
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import { BarChart2, Clock, FlaskConical, GitCompare, Search, Bell, Mail, Activity } from "lucide-react";
import LiveTrading from "./pages/LiveTrading";
import TradeHistory from "./pages/TradeHistory";
import Backtest from "./pages/Backtest";
import Compare from "./pages/Compare";
import StrategyHealth from "./pages/StrategyHealth";

const navItems = [
  { to: "/", label: "Live", icon: BarChart2, end: true },
  { to: "/history", label: "History", icon: Clock, end: false },
  { to: "/backtest", label: "Backtest", icon: FlaskConical, end: false },
  { to: "/compare", label: "Compare", icon: GitCompare, end: false },
  { to: "/health", label: "Health", icon: Activity, end: false },
];

export default function App() {
  return (
    <BrowserRouter>
      <div className="flex min-h-screen bg-gray-50">
        {/* Sidebar */}
        <aside className="w-44 flex-shrink-0 bg-white border-r border-gray-200 flex flex-col">
          {/* Logo */}
          <div className="flex items-center gap-2 px-4 py-5">
            <span className="text-orange-400 text-xl">◆</span>
            <span className="font-bold text-gray-900 text-base">AI Trader</span>
          </div>

          {/* Nav section label */}
          <p className="px-4 py-2 text-xs font-semibold text-gray-400 uppercase tracking-widest">
            Trading
          </p>

          {/* Nav links */}
          <nav className="flex flex-col gap-1 px-2">
            {navItems.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm transition-colors ${
                    isActive
                      ? "bg-blue-50 text-blue-600 font-medium"
                      : "text-gray-500 hover:bg-gray-100 hover:text-gray-900"
                  }`
                }
              >
                <Icon className="w-4 h-4" />
                {label}
              </NavLink>
            ))}
          </nav>

          {/* Account section */}
          <p className="px-4 pt-6 pb-2 text-xs font-semibold text-gray-400 uppercase tracking-widest">
            Account
          </p>
        </aside>

        {/* Main area */}
        <div className="flex flex-col flex-1 min-w-0">
          {/* Top Header */}
          <header className="h-16 bg-white border-b border-gray-200 flex items-center justify-between px-6 flex-shrink-0">
            {/* Search */}
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                className="pl-9 pr-4 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-700 placeholder-gray-400 w-64 focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="Search..."
              />
            </div>

            {/* Right: notifications + user */}
            <div className="flex items-center gap-4">
              <button className="text-gray-400 hover:text-gray-600">
                <Mail className="w-5 h-5" />
              </button>
              <button className="text-gray-400 hover:text-gray-600">
                <Bell className="w-5 h-5" />
              </button>
              <div className="w-8 h-8 rounded-full bg-blue-500 flex items-center justify-center text-white text-xs font-bold">
                AT
              </div>
              <span className="text-sm font-medium text-gray-700">AI Trader</span>
            </div>
          </header>

          {/* Page content */}
          <main className="flex-1 p-6 overflow-auto">
            <Routes>
              <Route path="/" element={<LiveTrading />} />
              <Route path="/history" element={<TradeHistory />} />
              <Route path="/backtest" element={<Backtest />} />
              <Route path="/compare" element={<Compare />} />
              <Route path="/health" element={<StrategyHealth />} />
            </Routes>
          </main>
        </div>
      </div>
    </BrowserRouter>
  );
}
