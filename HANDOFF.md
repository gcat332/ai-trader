# HANDOFF — Futures M2 (Binance USDT-M Testnet)

> เอกสารส่งงานสำหรับรัน/ทำต่อบนเครื่องอื่น • อัปเดต: 2026-06-20
> คู่กับ [`user_todo.md`](user_todo.md) (สิ่งที่ต้องทำก่อนเงินจริง)

## 0. สถานะ ณ ตอนนี้ (อ่านก่อน)

- **Branch:** `feat/futures-m2-testnet` — แตกจาก `main` ที่ commit `7f36982` (M1 merge)
- **นำหน้า main 19 commits** และ **ยังไม่ได้ push** (local-only) และ **ยังไม่ merge**
- โค้ด M2 เสร็จ + รีวิวครบ (Opus บนทุก live-order path), final review = **READY-TO-MERGE**
- เทสต์: **474 passed / 6 skipped** (offline; contract test ข้ามจนกว่าจะตั้ง `RUN_CONTRACT_TESTS=1`)

## 1. ⚠️ จะย้ายไปอีกเครื่องต้องทำก่อน

branch นี้อยู่ในเครื่องนี้เครื่องเดียว — เครื่องอื่นดึงไม่ได้จนกว่าจะ **push**:
```bash
git push -u origin feat/futures-m2-testnet
```
(หรือ `git bundle create m2.bundle main..feat/futures-m2-testnet` แล้วก๊อปไฟล์ไป)

> หมายเหตุ: ledger `.superpowers/sdd/progress.md` และ memory เป็น gitignored/เครื่อง-local → **ไม่ติดไปกับ git**. สถานะที่จำเป็นสรุปไว้ในไฟล์นี้แล้ว

## 2. Setup บนเครื่องใหม่

```bash
git clone <repo-url> && cd ai-trader
git checkout feat/futures-m2-testnet
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .          # deps จาก pyproject.toml (ccxt, pandas-ta, aiosqlite, python-dotenv, pytest, pytest-asyncio, ...)
```
- **`.env` ไม่อยู่ใน git** (โดยตั้งใจ) — ต้องสร้างใหม่: Binance USDT-M **testnet** key/secret + `binance_testnet=true` (ดูคีย์ที่ `core/config.Settings` อ่าน)
- Python 3.12

## 3. ยืนยันว่าใช้ได้

```bash
.venv/bin/python -m pytest -q          # คาดหวัง: 474 passed, 6 skipped (offline, ไม่แตะ network)
```

## 4. งานที่เสร็จแล้ว (M1 + M2)

- **M1** (merged ใน main แล้ว): paper futures core — long/short, isolated, leverage, liquidation modeled, time-stop, close-only flip, risk gate, §9 strategy selection
- **M2** (branch นี้): live USDT-M **testnet** adapter + funding gate + exchange-truth liquidation + live wiring
  - `exchange/binance_futures.py` — adapter (set_leverage/isolated, closePosition STOP+TP บน MARK price, reduceOnly exits, `fetch_positions` liquidationPrice จริง, funding rate, add-margin liq guard)
  - `risk/manager.py` — funding skip gate; `core/engine.py` — funding fetch + post-open liq guard + **symbol-based futures position matching** (one-way)
  - `main.py` — per-(market,network) exchange isolation; config `LOOPn_FUNDING_SKIP_THRESHOLD`, `LIQ_BUFFER_PCT`
  - `analysis/select_strategy_futures.py` — §9 short re-validation
  - contract test (opt-in): `tests/test_contract_binance_futures_testnet.py`
- **แผน/สเปค:** `docs/superpowers/plans/2026-06-20-futures-m2-testnet.md`, `docs/superpowers/specs/2026-06-19-futures-trading-design.md`

## 5. งานที่เหลือ (ทำต่อ)

1. **Validate testnet (ด่าน M2)** — ดู [`user_todo.md`](user_todo.md) Phase 1: รัน contract test + supervised testnet run (ผู้ใช้ทำเอง ต้องมี key)
2. **M3 (mainnet — ยังไม่ได้ทำ)** — wire เข้า go-live gate, `LIVE_TRADING_ENABLED`, partial-TP/breakeven (#6), correlation exposure (#7), macro blackout (#8), เคลียร์ deferred seams. ต้องเขียนแผนใหม่ก่อน (workflow: brainstorm → spec → plan → SDD)

## 6. ข้อควรรู้ก่อนรัน (สำคัญ)

- **`LIQ_BUFFER_PCT` default `0.0` → liq guard หลังเปิด position หลับ** ต้องตั้ง > 0 ถึง arm
- **อย่าใช้ `supertrend` ลง live** — re-validate แล้วขาดทุนทั้งสองฝั่งบน 60 วันล่าสุด (อันดับ #1 เดิมเป็น artifact ของ spot harness)
- 1 symbol = 1 leverage; futures loop เทรดคนละ symbol (cross-loop leverage race ปิดไม่สนิท — รอ M3)
- spot path ไม่แตะ (byte-for-byte) — เทสต์ spot เดิมผ่านหมด

## 7. Workflow agents (ต่อจากนี้)

- implementer = **Codex** (`codex:codex-rescue`); design/review/accept = **Claude (Opus บน safety-critical)**
- การส่งงานระหว่าง agent: append เข้า `changes.log` (append-only) — entry ล่าสุดคือ C1 fix (commit `7c0a241`)
- ถ้าทำ M3 ต่อ: ใช้ subagent-driven-development กับแผนใหม่; SDD ledger เริ่มที่ `.superpowers/sdd/progress.md` (เครื่องใหม่จะไม่มี — สร้างใหม่จากแผน)
