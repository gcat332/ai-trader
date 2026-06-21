# HANDOFF — Futures (M1 + M2 + M3 + §11 Telegram UX merged)

> เอกสารส่งงานสำหรับรัน/ทำต่อบนเครื่องอื่น • อัปเดต: 2026-06-20
> คู่กับ [`user_todo.md`](user_todo.md) (สิ่งที่ต้องทำก่อนเงินจริง)

## 0. สถานะ ณ ตอนนี้ (อ่านก่อน)

- **อยู่บน `main`** — M1 + M2 + M3 + cleanup + **§11 Telegram UX merge เข้า main หมดแล้ว** (HEAD `a279e07`)
- **main นำหน้า `origin/main` 34 commits และยังไม่ได้ push** (local-only)
- โค้ดผ่านรีวิวครบ (Opus บนทุก safety/live-order path); §11 final whole-branch review = **READY-TO-MERGE**
- เทสต์: **574 passed / 6 skipped** (offline; contract test ข้ามจนกว่าจะตั้ง `RUN_CONTRACT_TESTS=1`)
- **`LIVE_TRADING_ENABLED` ยังเป็น `false`** — infra พร้อมแต่ **ยังไม่เทรดเงินจริง** จนกว่าจะมี strategy ที่กำไรจริง (เฟส #2)

## 1. ⚠️ จะย้ายไปอีกเครื่องต้องทำก่อน

main ยังไม่ push — เครื่องอื่นดึงงานใหม่ไม่ได้จนกว่าจะ **push**:
```bash
git push origin main
```
(หรือ `git bundle create futures.bundle origin/main..main` แล้วก๊อปไฟล์ไป)

> หมายเหตุ: ledger `.superpowers/sdd/progress.md` และ memory เป็น gitignored/เครื่อง-local → **ไม่ติดไปกับ git**. สถานะที่จำเป็นสรุปไว้ในไฟล์นี้แล้ว

## 2. Setup บนเครื่องใหม่

```bash
git clone <repo-url> && cd ai-trader
git checkout main
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .          # deps จาก pyproject.toml (ccxt, pandas-ta, aiosqlite, python-dotenv, pytest, pytest-asyncio, ...)
```
- **`.env` ไม่อยู่ใน git** (โดยตั้งใจ) — ต้องสร้างใหม่: Binance USDT-M **testnet** key/secret + `binance_testnet=true` (ดูคีย์ที่ `core/config.Settings` อ่าน)
- Python 3.12

## 3. ยืนยันว่าใช้ได้

```bash
.venv/bin/python -m pytest -q          # คาดหวัง: 574 passed, 6 skipped (offline, ไม่แตะ network)
```

## 4. งานที่เสร็จแล้ว (M1 + M2 + M3 + §11)

- **M1**: paper futures core — long/short, isolated, leverage, liquidation modeled, time-stop, close-only flip, risk gate, §9 strategy selection
- **M2**: live USDT-M **testnet** adapter + funding gate + exchange-truth liquidation + live wiring
  - `exchange/binance_futures.py` — adapter (set_leverage/isolated, closePosition STOP+TP บน MARK price, reduceOnly exits, `fetch_positions` liquidationPrice จริง, funding rate, add-margin liq guard, symbol-based futures matching)
  - `risk/manager.py` — funding skip gate; `core/engine.py` — funding fetch + post-open liq guard
  - `main.py` — per-(market,network) exchange isolation; config `LOOPn_FUNDING_SKIP_THRESHOLD`, `LIQ_BUFFER_PCT`
- **M3**: mainnet enablement + hardening (**real money ยังปิด**)
  - go-live gate one-way enforcement (`verify_account_mode()` fail-closed บน hedge/missing key) + `_verify_futures_accounts` pre-arm
  - **DryRunExchange** (`exchange/dry_run.py`) — wrap live adapter, read=passthrough / write=intercept "WOULD" (ไม่ส่ง order จริง); เลือกด้วย `DRY_RUN=true`
  - #6 partial-TP ที่ TP1 (sized reduceOnly) + move SL → breakeven (never-naked), `LOOPn_PARTIAL_TP_PCT` (default 0=off)
  - #7 config-driven correlation groups (`CORRELATION_GROUPS`); #8 macro blackout (`MACRO_BLACKOUT_FILE`, opens-only)
  - hardening seams: live tier mmr, slippage pad บน liq guard (`LIQ_SLIPPAGE_PAD`), config-time leverage-conflict rejection
  - `docs/mainnet-futures-runbook.md` (dry-run procedure + "อย่าเปิด LIVE จนกว่า strategy ผ่าน")
- **cleanup**: เคลียร์ deferred minors (partial-TP guards, engine reorder, dry-run hygiene, test gaps) — merge `04d4dcf`
- **§11 Telegram UX** (merge `a279e07`, 9 tasks, Opus final review READY-TO-MERGE)
  - controller position dicts widened (side/mode/leverage/liq/initial-margin); direction-aware alert formatters; futures-aware position lines (liq-first) + SPOT/FUTURES label
  - **leverage-aware 2-tier proactive liq warning** (`notifier/telegram.py` `maybe_warn_liquidation`, wired ใน `core/trading_loop.py`) — soft once+rearm / hard repeat; band table `_LIQ_BANDS`
  - **close-by-identity** (`core/live_controller.py`): short fix (LONG→SELL/SHORT→BUY reduce-only), read-back, routed through owning engine; `flatten()`; `move_to_breakeven()`
  - inline `[Close][SL→BE]` buttons (identity callback `close:<loop>:<symbol>:<side>`) + confirmation infra (nonce+TTL, re-read, auth); `/flatten` panic (scope-count confirm); `/close` ผ่าน confirm
  - autocomplete (8 cmds), drawdown headroom ใน `/status`, quiet routine summaries
  - **gates:** SL→BE button default-off (`TELEGRAM_ENABLE_BE_BUTTON=false`); confirm TTL `TELEGRAM_CONFIRM_TTL_SECONDS` (120s)
- **แผน/สเปค:** `docs/superpowers/specs/2026-06-19-futures-trading-design.md`, `.../2026-06-20-futures-m3-mainnet-design.md`, `.../2026-06-20-telegram-futures-ux-design.md` + plans คู่กัน

## 5. งานที่เหลือ (ทำต่อ — ตามลำดับที่ user กำหนด)

1. **strategy edge (#2)** — เฟสถัดไป (blocker สุดท้ายก่อนเงินจริง): ขยาย 2 → 4 loops (loop3 futures LONG, loop4 futures SHORT), หา strategy **RR 2:1→3:1, winrate ~60%** บนตลาด **2 เดือนล่าสุด** (ดู memory `strategy-edge-requirements.md`)
2. **Validate testnet** ก่อนเงินจริง — ดู [`user_todo.md`](user_todo.md) (รัน contract test + supervised testnet, user ทำเอง ต้องมี key)

### 5.1 §11 pre-arming follow-ups (ปิดก่อนเปิดฟีเจอร์/ก่อน mainnet — จาก final review)

- **BE wrong-side guard (spec C6) ยังไม่มี** ใน `move_to_breakeven` (`core/live_controller.py` ~307) — ต้อง thread mark price เข้ามา; **ปิดอยู่** (`TELEGRAM_ENABLE_BE_BUTTON=false`). **ต้องแก้ก่อนเปิดปุ่ม SL→BE**
- liq-warning **integration test** ที่ยืนยันว่า `trading_loop` เรียก `maybe_warn_liquidation` จริง + คอมเมนต์ 1 บรรทัด pin invariant single-symbol-per-loop
- callback-parse robustness สำหรับ symbol แบบ `BTC/USDT:USDT` (settle-suffix) — เช็คกับ `fetch_positions` symbol จริงก่อน mainnet
- (Minor) `/stop_bot` confirm ยังไม่ wired (dead `_execute_action` branch); รวม `_authorized`/`_authorized_callback`; test invalid-side `/close`

## 6. ข้อควรรู้ก่อนรัน (สำคัญ)

- **`LIVE_TRADING_ENABLED=false`** — gate ปฏิเสธการ arm จริงอยู่ (มีเทสต์ยืนยัน non-tautological); mainnet path ทดสอบผ่าน **DRY_RUN** เท่านั้น
- **`LIQ_BUFFER_PCT` / `LIQ_SLIPPAGE_PAD` default `0.0`** → buffer ทั้งคู่หลับ; ตั้ง > 0 ถึงจะ tighten liq guard (ทั้งสองตอนนี้ tighten ทิศเดียวกันแล้ว — fix `7d4de90`)
- **`LOOPn_PARTIAL_TP_PCT` default `0`** → partial-TP/breakeven ปิด (พฤติกรรมเดิม full-close-at-TP); ถ้าตั้ง >0 ระวัง sub-step qty (ดู runbook note)
- **อย่าใช้ `supertrend` ลง live** — re-validate แล้วขาดทุนทั้งสองฝั่งบน 60 วันล่าสุด
- 1 symbol = 1 leverage (บังคับที่ config validation); spot path ไม่แตะ (byte-for-byte)

## 7. Workflow agents (ต่อจากนี้)

- implementer = **Codex** (`codex:codex-rescue`); design/review/accept = **Claude (Opus บน safety-critical)**; staff-review อีกรอบก่อนส่ง
- การส่งงานระหว่าง agent: append เข้า `changes.log` (append-only)
- ใช้ subagent-driven-development กับแผนใหม่; SDD ledger ที่ `.superpowers/sdd/progress.md` (เครื่องใหม่จะไม่มี — สร้างใหม่จากแผน)
