# สิ่งที่ต้องทำก่อนรันเงินจริง — Futures (USDT-M)

> สรุป ณ M2 (Binance USDT-M testnet) — branch `feat/futures-m2-testnet`
> ปรับปรุงล่าสุด: 2026-06-20

## ⚠️ อ่านก่อน: ตอนนี้อยู่แค่ระดับ "testnet"

โค้ด M2 ที่เพิ่งทำเสร็จ = **ต่อ Binance USDT-M testnet** (เงินปลอม) เท่านั้น
การรัน **เงินจริง (mainnet)** ยังต้องทำ **M3** ก่อน (ดูส่วนท้าย) — ตอนนี้ยังไม่ได้ทำ
อย่าข้ามไป mainnet ก่อนที่ testnet จะผ่านและ M3 เสร็จ

---

## Phase 1 — Validate บน Testnet (ด่าน M2 บังคับผ่าน)

- [ ] ใส่ Binance **USDT-M futures testnet** API key/secret ใน `.env` (ตามที่ `core/config.Settings` อ่าน) — เปิด futures permission, ตั้ง `binance_testnet=true`
- [ ] รัน contract test (ยิง testnet จริง):
  ```bash
  RUN_CONTRACT_TESTS=1 .venv/bin/python -m pytest tests/test_contract_binance_futures_testnet.py -v
  ```
  ต้องเขียว: set leverage/isolated → เปิด → วาง stop/TP → `get_positions` รายงาน `liquidationPrice` จริง → ปิด reduce-only
- [ ] **Supervised testnet run** (รันบอทจริงสัก 2-3 ชม. แล้วเฝ้าดู) — ยืนยันด้วยตา:
  - [ ] position reconcile ตรงกับ `fetch_positions` ของ exchange
  - [ ] `liquidation_price` มาจาก exchange จริง (ไม่ใช่สูตรคำนวณ)
  - [ ] funding skip เด้งเข้า Telegram เมื่อ funding เกิน threshold
  - [ ] liq-buffer guard ทำงาน (ลอง leverage สูง + stop แคบ ให้ liq ใกล้ → ดูว่ามัน add margin)
  - [ ] opposite signal = **ปิดอย่างเดียว ไม่ flip** / re-entry ไม่ซ้อน / time-stop ปิดได้จริง

---

## Phase 2 — ตั้งค่า config ก่อนเปิด live

- [ ] **`LIQ_BUFFER_PCT` ตั้งค่า > 0** ⚠️ — ค่า default `0.0` ทำให้ liq guard หลังเปิด position **หลับ** (ไม่ทำงาน). ต้องตั้งเอง เช่น `LIQ_BUFFER_PCT=0.02` ถึงจะ arm
- [ ] ตั้ง per-loop futures config (ต่อ loop):
  - [ ] `LOOPn_MARKET=futures`
  - [ ] `LOOPn_LEVERAGE=` (เริ่ม **ต่ำ** เช่น 2-3 — risk-first)
  - [ ] `LOOPn_RISK_PER_TRADE=` (เช่น 0.01 = เสี่ยง 1% ของ equity ต่อไม้)
  - [ ] `LOOPn_MAX_HOLD_HOURS=` (time-stop)
  - [ ] `LOOPn_REENTRY_COOLDOWN_BARS=`
  - [ ] `LOOPn_FUNDING_SKIP_THRESHOLD=0.001` (default = 0.1%/8h; ปรับได้)
- [ ] ตั้ง portfolio risk (ตาม goal: กำไร ~10-20%/เดือน, ขาดทุนไม่เกิน 10% ของสินทรัพย์):
  - [ ] `MAX_DRAWDOWN_LIMIT_PCT=` (circuit breaker — แนะนำ ≤ 0.10)
  - [ ] `DAILY_LOSS_LIMIT_PCT=` (เช่น 0.03)
  - [ ] `MAX_POSITION_PCT=`, `MAX_OPEN_POSITIONS=`
- [ ] **กฎ leverage ข้าม loop:** 1 symbol = 1 leverage; ให้แต่ละ futures loop เทรด **คนละ symbol**
  (สอง loop เทรด symbol เดียวกันผ่านคนละ adapter จะไม่ share lock — leverage race ปิดไม่สนิท; เลี่ยงไว้ก่อน — รอแก้ M3)

---

## Phase 3 — เรื่อง strategy

- [ ] **อย่าเปิด `supertrend` ลง live** ❌ — ผล re-validate บน futures bench 60 วันล่าสุด: ฝั่ง short ทำงานได้ แต่ **ขาดทุนทั้งสองฝั่ง** ทุก timeframe (อันดับ #1 เดิมเป็น artifact ของ spot ที่ทิ้ง SELL)
- [ ] strategy rule-based แบบ long-only ตัวอื่นก็ **ขาดทุนหมด**บน 60 วันล่าสุด → ต้องมี strategy ที่ validate แล้วว่ามี edge ก่อนเปิดเงินจริง (รอ §10 ML / param sweep)

---

## Phase 4 — ก่อนแตะ Mainnet จริง (M3 — ยังไม่ได้ทำ)

สิ่งเหล่านี้ยัง**ไม่มีในโค้ด** ต้องทำเป็น milestone ถัดไปก่อนเงินจริง:

- [ ] Wire futures เข้า go-live safety gate (`docs/release-safety-validation-gate.md`)
- [ ] `LIVE_TRADING_ENABLED=true` ถึงจะ arm คำสั่งจริง (มี guard แล้ว แต่ทดสอบ futures path ให้ครบ)
- [ ] เคลียร์ deferred 3 ข้อ (อยู่ใน memory): mmr ผูก shared constant ให้ live ใช้ tier จริง, reconcile risk-guard vs exchange-fill, ปิด cross-loop leverage race
- [ ] partial-TP / move-SL-to-breakeven (#6), correlation-aware exposure (#7), macro blackout (#8)
- [ ] mainnet validation runbook + เริ่มด้วยเงิน **ก้อนเล็กมาก** แล้วค่อยขยาย

---

## ข้อควรระวังถาวร

- [ ] อย่า commit `.env` / API key / secret / Telegram token / logs / db — เด็ดขาด
- [ ] เริ่ม leverage ต่ำ + เงินน้อย เสมอ ค่อยขยายเมื่อพิสูจน์แล้ว
- [ ] ทุกครั้งที่แก้ live-trading path → ต้อง validate บน testnet ก่อน
- [ ] เก็บ `MAX_DRAWDOWN_LIMIT_PCT` ให้สอดคล้องกับเพดานขาดทุน 10% ของสินทรัพย์ทั้งหมด
