# Dashboard Design Specification

Reference image: `docs/design/dashboard-reference.png`

This document is the visual contract for all dashboard pages (Phase 5, 8, 9 frontend work).
Every React component must conform to this design system.

---

## Theme: Light

The dashboard uses a **light theme** (white/off-white backgrounds, dark text).
All Tailwind classes in the plans that reference dark theme (`bg-gray-800`, `text-white`, etc.)
must be replaced with the light equivalents defined here.

---

## Color Palette

| Token | Hex | Tailwind class | Usage |
|---|---|---|---|
| `bg-app` | `#F5F6FA` | `bg-gray-50` | Page background |
| `bg-card` | `#FFFFFF` | `bg-white` | Cards, panels |
| `bg-sidebar` | `#FFFFFF` | `bg-white` | Left sidebar |
| `bg-active-nav` | `#F0F4FF` | `bg-blue-50` | Active nav item highlight |
| `text-primary` | `#111827` | `text-gray-900` | Headings, bold values |
| `text-secondary` | `#6B7280` | `text-gray-500` | Labels, subtitles |
| `text-muted` | `#9CA3AF` | `text-gray-400` | Placeholders, disabled |
| `accent-blue` | `#4F6EF7` | `text-blue-500` / `bg-blue-500` | Active nav, buttons, links |
| `up-green` | `#22C55E` | `text-green-500` | Positive PnL, price up |
| `down-red` | `#EF4444` | `text-red-500` | Negative PnL, price down |
| `border` | `#E5E7EB` | `border-gray-200` | Card borders, dividers |
| `shadow` | — | `shadow-sm` | Subtle card elevation |

---

## Typography

Font family: **Inter** (Google Fonts) — fallback `system-ui, sans-serif`.

```html
<!-- index.html -->
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
```

```css
/* tailwind.config.js */
fontFamily: { sans: ['Inter', 'system-ui', 'sans-serif'] }
```

| Role | Size | Weight | Class |
|---|---|---|---|
| Page title | 20px | 700 | `text-xl font-bold text-gray-900` |
| Section title | 16px | 600 | `text-base font-semibold text-gray-900` |
| Card label | 13px | 400 | `text-sm text-gray-500` |
| Card value | 15px | 700 | `text-sm font-bold text-gray-900` |
| Table header | 13px | 400 | `text-xs text-gray-400 uppercase tracking-wide` |
| Table cell | 14px | 500 | `text-sm font-medium text-gray-700` |
| Small / subtext | 12px | 400 | `text-xs text-gray-400` |

---

## Layout

```
┌──────────────────────────────────────────────────────┐
│  Sidebar (180px)  │  Top Header (64px)               │
│                   ├──────────────────────────────────│
│  [Logo]           │  Content Area                    │
│  ─────            │                                  │
│  Dashboard        │  [Portfolio Cards Row]           │
│  Stock            │                                  │
│  Favorit          │  [Chart Panel] [Favorites Panel] │
│  Wallet           │                                  │
│  ─────            │  [Market Trend Table]            │
│  Our community    │                                  │
│  Profile          │                                  │
│  Contact Us       │                                  │
│  Logout           │                                  │
└──────────────────────────────────────────────────────┘
```

- **Sidebar:** `w-44` (176px), full height, `border-r border-gray-200`
- **Header:** `h-16`, `border-b border-gray-200`, flex with search center + user right
- **Content:** `p-6`, scrollable, `bg-gray-50`

---

## Component Specs

### Sidebar Navigation

```tsx
// Active item
<NavLink className="flex items-center gap-3 px-4 py-2.5 rounded-lg
  bg-blue-50 text-blue-600 font-medium text-sm">
  <Icon className="w-4 h-4" />
  Dashboard
</NavLink>

// Inactive item
<NavLink className="flex items-center gap-3 px-4 py-2.5 rounded-lg
  text-gray-500 hover:bg-gray-100 hover:text-gray-900 text-sm transition-colors">
```

Section label (e.g. "Account"):
```tsx
<p className="px-4 py-2 text-xs font-semibold text-gray-400 uppercase tracking-widest">
  Account
</p>
```

Logo area:
```tsx
<div className="flex items-center gap-2 px-4 py-5">
  <span className="text-orange-400 text-xl">◆</span>
  <span className="font-bold text-gray-900 text-base">AI Trader</span>
</div>
```

---

### Top Header

```tsx
<header className="h-16 bg-white border-b border-gray-200 flex items-center justify-between px-6">
  {/* Search */}
  <div className="relative">
    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
    <input className="pl-9 pr-4 py-2 bg-gray-50 border border-gray-200 rounded-lg
      text-sm text-gray-700 placeholder-gray-400 w-64 focus:outline-none focus:ring-2 focus:ring-blue-500" />
  </div>

  {/* Right: notifications + avatar + name */}
  <div className="flex items-center gap-4">
    <button className="text-gray-400 hover:text-gray-600"><Mail className="w-5 h-5" /></button>
    <button className="text-gray-400 hover:text-gray-600"><Bell className="w-5 h-5" /></button>
    <img className="w-8 h-8 rounded-full object-cover" />
    <span className="text-sm font-medium text-gray-700">John Marker</span>
  </div>
</header>
```

---

### Portfolio Cards (horizontal scrollable row)

```tsx
<div className="flex gap-4 overflow-x-auto pb-2">
  {/* Each card */}
  <div className="flex-shrink-0 w-56 bg-white rounded-xl p-4 border border-gray-200 shadow-sm">
    {/* Header: logo + name + sparkline */}
    <div className="flex items-center justify-between mb-3">
      <div className="flex items-center gap-2">
        <img className="w-8 h-8 rounded-full" />
        <span className="font-semibold text-gray-900 text-sm">BTC/USDT</span>
      </div>
      {/* Sparkline: use Recharts LineChart, 80×30, no axes */}
      <Sparkline data={priceHistory} color="#22C55E" />
    </div>
    {/* Metrics */}
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-gray-500">Total Share</span>
        <span className="text-green-500 font-semibold">+ 2.4%</span>
      </div>
      <div className="flex justify-between text-xs">
        <span className="text-gray-500">Total Return</span>
        <span className="font-bold text-gray-900">$ 201.01</span>
      </div>
    </div>
  </div>
</div>
```

Sparkline component (no axes, just the line):
```tsx
import { LineChart, Line, ResponsiveContainer } from "recharts";
function Sparkline({ data, color }: { data: number[]; color: string }) {
  return (
    <ResponsiveContainer width={80} height={30}>
      <LineChart data={data.map(v => ({ v }))}>
        <Line type="monotone" dataKey="v" stroke={color} strokeWidth={1.5} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}
```

---

### Main Chart Panel

```tsx
<div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
  {/* Header row */}
  <div className="flex items-center justify-between mb-4">
    <div className="flex items-center gap-3">
      <img className="w-10 h-10 rounded-full" />
      <div>
        <h2 className="font-bold text-gray-900 text-base">BTC/USDT</h2>
        <p className="text-xs text-gray-400">Bitcoin</p>
      </div>
    </div>
    <div className="text-right">
      <p className="font-bold text-gray-900 text-lg">$ 65,234</p>
      <p className="text-xs text-green-500">▲ 2.4%  Last update 15:40</p>
    </div>
  </div>

  {/* Time period tabs */}
  <div className="flex gap-2 mb-4">
    {["1D","1W","1M","3M","6M","1Y","3Y","ALL"].map(t => (
      <button className={`px-3 py-1 rounded-full text-xs font-medium transition-colors
        ${active === t
          ? "bg-gray-900 text-white"
          : "bg-gray-100 text-gray-500 hover:bg-gray-200"}`}>
        {t}
      </button>
    ))}
  </div>

  {/* Candlestick chart via recharts-stockcharts or lightweight-charts */}
  <div className="h-72">
    <CandlestickChart data={ohlcvData} />
  </div>
</div>
```

**Candlestick library:** Use `lightweight-charts` (TradingView) — better performance than Recharts for OHLCV.
```bash
npm install lightweight-charts
```

---

### My Favorite / Watchlist Panel

```tsx
<div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5 w-72 flex-shrink-0">
  <div className="flex items-center justify-between mb-4">
    <h3 className="font-semibold text-gray-900">My Favorite</h3>
    <button className="text-blue-500 text-sm">See All</button>
  </div>
  <div className="space-y-3">
    {favorites.map(f => (
      <div className="flex items-center justify-between py-2 border-b border-gray-100 last:border-0">
        <div className="flex items-center gap-3">
          <img className="w-8 h-8 rounded-full" />
          <div>
            <p className="text-sm font-semibold text-gray-900">{f.symbol}</p>
            <p className="text-xs text-gray-400">{f.name}</p>
          </div>
        </div>
        <div className="text-right">
          <p className="text-sm font-bold text-gray-900">$ {f.price}</p>
          <p className={`text-xs font-medium ${f.change > 0 ? "text-green-500" : "text-red-500"}`}>
            {f.change > 0 ? "+" : ""}{f.change}
          </p>
        </div>
      </div>
    ))}
  </div>
</div>
```

---

### Market Trend Table

```tsx
<div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5 mt-6">
  <div className="flex items-center justify-between mb-4">
    <h3 className="font-semibold text-gray-900 text-base">Market Trend</h3>
    <button className="text-blue-500 text-sm">See All</button>
  </div>
  <table className="w-full">
    <thead>
      <tr className="text-xs text-gray-400 uppercase tracking-wide border-b border-gray-100">
        <th className="text-left pb-3 font-normal">Name</th>
        <th className="text-right pb-3 font-normal">Price</th>
        <th className="text-right pb-3 font-normal">Balance</th>
        <th className="text-right pb-3 font-normal">Value</th>
        <th className="text-center pb-3 font-normal">Watchlist</th>
        <th className="pb-3"></th>
      </tr>
    </thead>
    <tbody>
      {markets.map(m => (
        <tr key={m.symbol} className="border-b border-gray-50 hover:bg-gray-50 transition-colors">
          <td className="py-3.5">
            <div className="flex items-center gap-3">
              <img className="w-9 h-9 rounded-full" />
              <div>
                <p className="text-sm font-semibold text-gray-900">{m.symbol}</p>
                <p className="text-xs text-gray-400">{m.name}</p>
              </div>
            </div>
          </td>
          <td className="text-right text-sm font-medium text-gray-700">$ {m.price}</td>
          <td className="text-right">
            <span className={`text-sm font-semibold ${m.change > 0 ? "text-green-500" : "text-red-500"}`}>
              {m.change > 0 ? "+" : ""}{m.change}
            </span>
          </td>
          <td className="text-right text-sm font-medium text-gray-700">$ {m.value}</td>
          <td className="text-center">
            <button className="text-gray-300 hover:text-blue-500 transition-colors">
              <Bookmark className="w-4 h-4" />
            </button>
          </td>
          <td className="text-right pl-4">
            <button className="px-4 py-1.5 bg-blue-500 hover:bg-blue-600 text-white
              text-xs font-semibold rounded-full transition-colors">
              Get Started
            </button>
          </td>
        </tr>
      ))}
    </tbody>
  </table>
</div>
```

---

## Spacing System

| Context | Value | Class |
|---|---|---|
| Page padding | 24px | `p-6` |
| Card padding | 20px | `p-5` |
| Card gap | 16px | `gap-4` |
| Section gap | 24px | `mt-6` |
| Row item gap | 12px | `gap-3` |
| Border radius (card) | 12px | `rounded-xl` |
| Border radius (button pill) | 9999px | `rounded-full` |
| Border radius (input) | 8px | `rounded-lg` |

---

## Corrections to Phase 5 + 8 + 9 Plans

The plans in this repo were written assuming a **dark theme**. Replace all dark theme classes with light equivalents per the table below before implementing:

| Phase 8/9 dark class | Replace with (light) |
|---|---|
| `bg-gray-800` (card) | `bg-white border border-gray-200` |
| `bg-gray-700` (divider) | `border-gray-100` |
| `text-white` (heading) | `text-gray-900` |
| `text-gray-300` (body) | `text-gray-700` |
| `text-gray-400` (label) | `text-gray-500` |
| `text-gray-500` (muted) | `text-gray-400` |
| `border-gray-700` | `border-gray-200` |
| `text-green-400` | `text-green-500` |
| `text-red-400` | `text-red-500` |
| `text-orange-400` | `text-orange-500` |

---

## Additional npm Dependencies for Dashboard

```bash
npm install lightweight-charts   # TradingView candlestick charts
npm install lucide-react         # icons (Mail, Bell, Search, Bookmark, etc.)
```

`recharts` (already in plan) is used for sparklines and equity curves only.
`lightweight-charts` is used for OHLCV candlestick charts (better performance).
