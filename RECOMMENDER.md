# Savings recommendation — `POST /v1/savings/recommend`

เพิ่มเข้ามาใหม่ **ยังไม่ commit** — ฝากเจ้าของ repo review ก่อนครับ

ตอบคำถามว่า *"เดือนนี้คนนี้ควรออมเท่าไร"* ซึ่งเดิมคิดอยู่ในฝั่ง Go (savings-api)
ตอนนี้ย้ายมาที่นี่ service เดียวกับ `/analyze-upload` แต่คนละ endpoint คนละสัญญา

## ไฟล์ที่เพิ่ม

```
src/config/savings_config.py                      SavingsConfig dataclass
src/recommender/__init__.py
src/recommender/savings_recommendation_module.py  ตัวคิด (pure ไม่มี I/O)
tests/test_recommend.py                           30 tests
main.py                                           + models + route
```

## ⚠️ หน่วยเงินเป็น **สตางค์ (int)** ไม่ใช่บาท (float)

ต่างจาก `/analyze-upload` ที่เหลือใน service นี้ **ตั้งใจให้ต่าง**

ตัวเลขจาก endpoint นี้กลายเป็นการโอนเงินระหว่างบัญชีจริง float64 เก็บ `399.00`
ไม่ได้เป๊ะ ระบบออมเงินที่หายไปเดือนละสตางค์คือระบบที่ reconcile ไม่ลง
สัญญาของฝั่ง analysis ยังเป็น float เหมือนเดิม ไม่ได้แตะ

## สูตร

```
surplus  = income − fixed_costs − spent_so_far − (avg_daily_spend × days_remaining)
proposed = surplus × aggressiveness × data_quality
```

**กันเงินไว้ใช้จนสิ้นเดือน** — วันที่ 1 ยังไม่ได้ใช้อะไร ถ้าเอา income − costs ตรง ๆ
จะเห็นเงินเหลือเป็นกองแล้วกวาดเข้ากระปุก จากนั้นเจ้าของก็ใช้ชีวิตอีก 29 วันตามปกติ
แล้วเดือนนั้นไม่พอ

**อ่านมาน้อย ออมน้อยลง** — `data_quality = months_factor × parse_factor` ∈ [0.6, 1.0]
กันเคสเฉพาะ: เบี้ยประกันรายปีมาลงในเดือนที่กวาดเงินไปหมดแล้ว

`data_months = 0` → quality 1.0 **ไม่ใช่โทษ** แปลว่าผู้เรียกไม่มี statement
เลยใช้ ledger ตัวเองแทน ซึ่งคือบัญชีเดียวกันอ่านจากต้นทาง

> ไม่ได้เอา `confidence` รายตัวมาคูณ — รายการ confidence 0.5 ถูกกันไว้เต็มจำนวน
> ใน `fixed_costs` อยู่แล้ว หักซ้ำคือลงโทษความไม่แน่นอนเดียวกันสองครั้งในทิศทางเดียวกัน

## `skip` ไม่ใช่ error

ส่ง `recommended_amount: 0` เฉย ๆ ฝั่ง Go อ่านว่า "โมเดลตอบอะไรไม่ได้" แล้วถอยไปใช้สูตรตัวเอง
ถ้าตั้งใจว่าเดือนนี้ไม่ควรออมจริง ต้องส่ง `skip: true` Go ถึงจะเคารพคำตัดสิน

## สัญญาณที่ผู้เรียกหาเองไม่ได้ (Phase 2)

`/analyze-upload` คืนเพิ่มจากเดิม — ทั้งหมดนี้ pipeline คำนวณไว้อยู่แล้วแต่ทิ้งไปก่อนส่งกลับ

| field | มาจากไหน |
|---|---|
| `closing_balance` | `RawTransaction.balance_after` ของรายการล่าสุด |
| `observed_income` / `income_months` / `payday_day_of_month` | credit (`รับโอนเงิน`) ที่ detector กรองทิ้งก่อนเริ่มทำงาน |
| `variable_spend_monthly` | pattern ที่ `_filter_active_expenses` คัดออก |
| `avg_daily_spend` | debit รวม ÷ จำนวนวันที่ statement ครอบ |
| `recurring_type` / `amount_cv` / `day_of_month` / `n_months_present` | บน `RecurringPattern` อยู่แล้ว แค่ไม่เคยถูกส่งออก |

`parse_success_rate` **นับจริงแล้ว** (`ParseStats` ใน `record_parser.py`) ไม่ได้ hardcode 1.0 อีกต่อไป
แถว `ยอดยกมา` ไม่นับเป็นความล้มเหลว — การทิ้งมันคือความสำเร็จ จึงตัดออกจากตัวหาร

### สองกฎที่ใช้สัญญาณพวกนี้

**กันเงินไว้จ่ายบิลที่ยังไม่ออก** — สูตร surplus เป็นมุมมองทั้งเดือน บอกได้ว่าเดือนนี้เหลือเท่าไร
แต่ไม่บอกว่า *เมื่อไร* คนที่เงินพอทั้งเดือนยังจ่ายค่าเช่าวันที่ 25 ไม่ได้ ถ้าเงินออมออกไปวันที่ 20
บิลที่ผันผวนกันไว้มากกว่ายอดเฉลี่ย (`× (1 + cv)` เพดาน 2 เท่า) เพราะค่าไฟเฉลี่ย ฿1,200 ที่ cv 0.3
มาได้ถึง ฿1,600 และกันแค่ค่าเฉลี่ยคือกันน้อยไปพอดีในเดือนที่ต้องการมันที่สุด
**บิลที่ไม่รู้วันนับว่ายังไม่ออก** — การเดาว่าจ่ายไปแล้วคือการเดาที่ทำให้เงินติดลบ

**ใช้รายได้ที่เห็นจริงถ้าต่ำกว่าที่แจ้ง** — แต่ต้องเห็นอย่างน้อย `min_income_months` (2) เดือนก่อน
เงินเข้าครั้งเดียวไม่ใช่ pattern อาจเป็นแค่ statement ตัดคร่อมวันเงินเดือนออกพอดี
การเขียนทับตัวเลขที่ผู้ใช้บอกเองต้องมีหลักฐานดีกว่าการเห็นครั้งเดียว
รายได้ที่ *สูงกว่า* ที่แจ้งไม่ชนะ — เงินที่โผล่มาครั้งเดียวไม่ใช่การขึ้นเงินเดือน

## สิ่งที่ service นี้ **ไม่** ตัดสิน

วงเงินของผู้ใช้ (`min_per_month` / `max_per_month` / `buffer_balance`) ส่งเข้ามาเพื่อให้
เล็งให้อยู่ในกรอบได้ **แต่ฝั่ง Go บังคับซ้ำเสมอ** โมเดลที่ตอบเพี้ยนทำให้ยอดออมน้อยลง
หรือข้ามเดือนได้ แต่ทำให้เงินผู้ใช้ติดลบไม่ได้ — การแยกชั้นนี้ไม่ย้ายเข้ามาในไฟล์นี้

ทดสอบแล้ว: stub ที่แนะนำออมทั้งบัญชี ฿128,450.75 → Go ตัดเหลือ ฿5,000 ตามเพดานผู้ใช้

## รัน

```bash
.venv/bin/python -m pytest tests/test_recommend.py -q     # 30 passed
.venv/bin/uvicorn main:app --port 8000
curl -X POST localhost:8000/v1/savings/recommend -H 'Content-Type: application/json' -d '{
  "income": 4500000, "fixedCosts": 700000, "variableSpend": 750000,
  "avgDailySpend": 50000, "daysRemaining": 15, "dataMonths": 4, "aggressiveness": "BALANCED"}'
```

รับทั้ง camelCase (Go ส่งมาแบบนี้) และ snake_case

## หมายเหตุถึงเจ้าของ repo

**`config/*.json` ไม่ได้ถูกโหลดเลย** — `from_json_file` ไม่มีคนเรียกสักที่
pipeline สร้าง dataclass default ตลอด (`stateless_pipeline.py:108`) แก้ JSON แล้วไม่มีผลอะไร
`DETECTION_CONFIG_PATH` / `FORECAST_CONFIG_PATH` ใน `.env.example` ก็ตายตาม
ผมเลย **ไม่ได้เพิ่ม `config/savings_config.json`** เพราะจะเป็นปุ่มที่กดไม่ติดอีกอัน

`UserLabelingConfig` และ `src/config/logging_config.py` ก็ไม่มีคนเรียกเหมือนกัน
(`aggregation_service.py:331` hardcode ค่าไว้แทน, `main.py:23` ใช้ `logging.basicConfig`)

`parse_success_rate` ยัง hardcode `1.0` อยู่ (`stateless_pipeline.py:299`) — ตัว parser
log record ที่ skip ไว้ครบแล้ว แค่ยังไม่ได้นับ ถ้านับเมื่อไหร่ `data_quality` จะทำงานเต็มสูตร
ตอนนี้มีแค่ `data_months` ที่ขับมัน
