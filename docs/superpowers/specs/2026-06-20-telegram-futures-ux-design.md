# Telegram Futures UX (§11) — Design

> Sub-project of the futures roadmap (`docs/superpowers/specs/2026-06-19-futures-trading-design.md` §11).
> Builds on M1+M2+M3 (all merged to `main`). Date: 2026-06-20.
> Reviewed by an expert Telegram/financial-UX reviewer and an expert USDT-M futures trader; their Critical/Important findings are folded into the scope below.

## 1. Goal

Make the Telegram bot **futures-aware** (long+short, leverage, liquidation) and **safer/friendlier to operate**, by extending the existing `notifier/telegram.py` formatters + `EngineController` plumbing. **Extend, do not rewrite.** Spot messages stay **byte-for-byte unchanged**; every futures field appears only when `mode == "FUTURES"`.

**Binding:** real money stays OFF (`LIVE_TRADING_ENABLED=false`) — this milestone is notification/control UX, validated on paper + testnet. The proactive liquidation warning is the **load-bearing safety feature** and is designed leverage-aware (see C4).

## 2. Locked scope decisions (from brainstorming + expert review)

- **Liq warning:** leverage-aware, price-distance, **two-tier** (soft once / hard repeating). NOT a single 10%-of-liq buffer (expert: leverage-blind, warns too late at high leverage).
- **Surfacing depth — Basic:** show `side / leverage / liquidation_price / initial_margin`. **Funding rate and ROE are deferred** to a later UX pass (data path exists from M2 but out of scope now).
- **Position identity:** all close/breakeven actions address a **specific position** (`loop_id : symbol : side`), never a bare symbol — long+short can coexist on one symbol in the 4-loop layout.
- **`/menu` reply keyboard (was 11.B/B4): CUT** (expert: weakest item, hijacks the input area, low value for a single authorized user).
- **`set_my_commands` autocomplete:** keep, **trimmed to ~8 core commands** (autocomplete is a menu, not a manifest).
- **SL→BE inline button:** kept but **default-off-gated** like the underlying partial-TP feature until a strategy is validated.
- Spot path unchanged; new code futures-gated.

## 3. Components

### C1 — Controller field widening (`core/live_controller.py`, `notifier/engine_controller.py`)
Position dicts today carry only `{symbol, quantity, unrealized_pnl}`. Widen the dicts returned by `get_status`, `get_strategies`, `get_strategy_status` to include the fields the `Position` model already has:
`side` (LONG/SHORT), `mode` (SPOT/FUTURES), `leverage`, `entry_price`, `liquidation_price`, and derived `initial_margin = entry_price * quantity / leverage`. Add a per-loop `market: "SPOT"|"FUTURES"` label to strategy summaries.
- Spot positions keep `mode="SPOT"`, `leverage=1`, `liquidation_price=None` → formatters render them exactly as today.
- Update the `EngineController` ABC docstrings to document the widened dict.
- `api/main.py` (the other `EngineController` consumer) must keep compiling; it does not need the new fields but must not break on them.

### C2 — Direction-aware alerts (`format_signal_alert`, `format_order_alert`)
For futures (`mode=="FUTURES"`): glyph `🟢 LONG` / `🔴 SHORT` and extra lines `Leverage: Nx`, `Liq: <price>`, `Margin: <initial_margin>`. For spot: **unchanged output** (no leverage/liq/margin line, existing BUY/SELL glyph logic intact). The futures-vs-spot branch keys on `mode`.

### C3 — Position formatters (`format_strategy_list`, `cmd_open_positions`, `/status` header)
Per futures position render: `side · leverage · liq · initial_margin` plus leverage-aware unrealized PnL. Label each loop **SPOT** or **FUTURES** so mixed setups read clearly. **Liq price is rendered first / made skimmable** in the futures block (the survival number must not be buried). Spot rendering unchanged.

### C4 — Proactive liquidation warning ⭐ (load-bearing safety)
A notifier method that pushes `⚠️ near liquidation` based on **price-distance to liquidation scaled by leverage**, fired from the existing futures position-poll path (`core/engine.py` ~288/375, which holds positions + mark price; paper `tick()` likewise).

**Threshold model (price-distance = `abs(mark - liq) / mark`), tiered by leverage:**
| Leverage | Soft warn (once) | Hard warn (repeating) |
|---|---|---|
| ≤ 5x  | 8% | 4% |
| 6–10x | 4% | 2% |
| 11–20x| 2% | 1% |
| > 20x | 1% | 0.5% |

(Defaults; the table is config-overridable via env. Tiers chosen so a slow-grind position warns with room, a high-leverage position still gets a soft ping before the hard zone.)

**Two-tier cadence:**
- **Soft tier:** entered the soft band → warn **once**; dedup until mark exits the soft band, then re-arm. (Avoids spamming a slow drift.)
- **Hard tier:** entered the hard band → warn **every poll, no dedup**, until the position exits the band or closes. (The fatal fast-wick case must not be silenced.)

**Alert is self-contained:** `side`, `leverage`, current `mark`, `liq`, **distance %** (price-distance), and `uPnL`. The warning carries an inline `[Close]` button (C6 identity-keyed) so the user acts in one tap.

**Buffer-vs-poll safety (expert C3):** a warning band narrower than the worst-case price move between two polls is unenforceable. Document the constraint and add a test asserting the hard band for the highest configured leverage tier is wider than a stated max per-poll move assumption; surface a startup log if the configured poll interval makes the tightest band unreliable. Futures-only (liq=None → skip).

### C5 — `/close` + position identity (`core/live_controller.py:close_position`, handler)
`close_position` today hardcodes `side="SELL"` (closes a LONG, **cannot close a SHORT**) and resolves by symbol only. Fix:
- Resolve the **specific** position by `loop_id + symbol + side` (or a stable position id), not bare symbol.
- Derive the closing side from the position: LONG→SELL, SHORT→BUY, with `reduce_only=True`.
- **Read back** the result: treat "no position / reduce-only-on-empty (-2022)" as success-equivalent (already flat), report partial fills with residual qty, and cancel/flag any resting SL/TP that a reduce-only close would leave behind.
- `/close` argument disambiguates when a symbol has both legs (e.g. `/close BTC SHORT` or pick from an inline list).

### C6 — Inline buttons + confirmation (`CallbackQueryHandler`)
- Entry/position alerts attach `InlineKeyboardMarkup`: `[Close] [SL→BE]`, `callback_data = "close:<loop>:<symbol>:<side>"` / `"be:<loop>:<symbol>:<side>"` (**identity-keyed**, not symbol-only).
- A `CallbackQueryHandler` routes callbacks, **reuses the existing `_authorized` gate** (callback query exposes `effective_chat`), and `answerCallbackQuery` on every callback to clear the spinner.
- **Destructive actions** (`Close`, `/close`, `/flatten`, `/stop_bot`) → inline **Yes/No confirmation**. The confirm step:
  - **echoes the exact position** being acted on (`Close loop3 BTC LONG 3x, uPnL +1.2%?`),
  - **re-reads live state at execution time** (not the render-time snapshot — positions move between prompt and tap),
  - carries a short **nonce + TTL** in the callback_data; a stale/expired tap answers explicitly and recoverably (`This alert is old — /open_positions to act on current positions.`).
- `SL→BE` callback → `controller.move_to_breakeven(<identity>)` → adapter `move_stop_to_breakeven` (exists from M3); **gated default-off** with the partial-TP feature; guard that BE is not the wrong side of entry (below entry on a short / above on a long) → no-op with a clear reply rather than a silent move.

### C7 — `/flatten` panic command
New command + `controller.flatten()`: close **all** positions across **all** loops, reduce-only each, behind a confirmation that **states the scope** (`Close ALL N positions across M loops?`). Execution **reads back per-position outcome** and posts a summary (closed / partial w/ residual / already-flat / failed) — never a single optimistic "flat." Cancels or flags resting SL/TP per position as in C5.

### C8 — Native autocomplete + drawdown headroom
- `set_my_commands(BotCommand[...])` at startup for the **~8 core** commands (`/status /pnl /open_positions /close /flatten /pause /resume /help`).
- `/status` (`format_risk_status` / status header): add a **drawdown headroom** line = `max_drawdown_limit_pct − current_drawdown` (account-level realized+unrealized), ties to the 10%-max-loss mandate.

### Notification loudness
Liquidation/critical alerts buzz (default); routine pushes (daily/weekly summary, status-ish) send with `disable_notification=True` so the one alert that matters is not drowned out.

## 4. Plan ordering (one spec, sequenced plan)

C1 (field plumbing) → C2+C3 (read-only formatters, lowest risk) → C5 (close+identity fix, the short bug) → C4 (proactive liq warning) → C6 (inline buttons+confirm) → C7 (/flatten) → C8 (autocomplete + drawdown). Each lands behind tests; spot output asserted unchanged throughout.

## 5. Out of scope (deliberate)

- **Funding-rate and ROE surfacing** (deferred — data path exists, not this milestone).
- **Margin-ratio / maintenance-margin** display (would need extra adapter reads; `initial_margin` only this round).
- `/menu` reply keyboard (cut).
- "Add margin" action flow.
- Any real-money arming (`LIVE_TRADING_ENABLED` stays false).

## 6. Testing

- **Spot unchanged:** golden-output assertions that `format_signal_alert`/`format_order_alert`/`format_strategy_list` produce today's exact strings for spot positions.
- **Futures fields present:** side/leverage/liq/initial-margin render for `mode="FUTURES"`.
- **Liq warning:** soft fires once + re-arms on exit; hard repeats every poll without dedup; tier selection by leverage; distance% math; buffer-vs-poll guard test; futures-only (spot skipped).
- **Close-short:** SHORT→BUY reduce-only side derivation; identity resolves the correct leg when both legs exist; -2022/empty treated as already-flat; partial-fill reported.
- **Callbacks:** routing + auth rejection on wrong chat; confirmation required for destructive; stale-nonce rejected with recoverable message; BE wrong-side guard.
- **/flatten:** closes all loops, per-position read-back summary, partial/failed reflected.
- **set_my_commands** called at startup with the trimmed list; drawdown-headroom math.
- Reuse the patterns in `tests/test_telegram.py` / `tests/test_telegram_multiloop.py`.
