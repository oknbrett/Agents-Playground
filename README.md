# Agents Playground

Experiments in LLM agent reasoning. Starting point: **Lily**, a demand planning agent.

---

## Lily — Demand Planning Reasoning Agent

Lily reads historical sales data and helps demand planners decide whether to **RAISE**, **LOWER**, or **KEEP** a forecast — without being told about promotions, seasons, or any other business context. She reasons from numbers alone.

### Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here
```

### Generate the dataset

```bash
python data/generate_dataset.py
```

Produces `data/demand_data.xlsx` and `data/demand_data.csv` — 1,248 rows covering 8 SKUs, 4 European customers, 13 periods × 3 years (2023–2025). The dataset has hidden patterns baked in (recurring peaks, one-time spikes, trends, forecast bias) with no label columns.

### Run Lily

```bash
# Analyse one SKU
python agents/lily/lily.py --sku SKU001

# Analyse all SKUs
python agents/lily/lily.py --sku all

# Narrow to one customer
python agents/lily/lily.py --sku SKU006 --customer Carrefour

# Use a custom data file
python agents/lily/lily.py --file path/to/your_data.xlsx --sku SKU001
```

### What Lily looks for

| Pattern | SKU | Expected recommendation |
|---|---|---|
| Recurring P5 peak (×1.75, 3 years) | SKU001 | RAISE |
| One-time P8 spike in 2023 only | SKU002 | UNCERTAIN |
| Consistent YoY growth (+18%/yr) | SKU003 | RAISE |
| Business plan 24–28% over actuals | SKU004 | LOWER + flag BP bias |
| Stat model far more accurate than DP | SKU005 | LOWER |
| Carrefour-only P11 peak (×2.10) | SKU006 | RAISE (Carrefour scope) |
| Declining volume (−17%/yr) | SKU007 | LOWER |
| High noise, no pattern | SKU008 | KEEP / UNCERTAIN |

### Data schema

| Column | Description |
|---|---|
| `period` | 4-weekly period, 1–13 |
| `year` | 2023 / 2024 / 2025 |
| `sku_id` | SKU001–SKU008 |
| `sku_name` | Product name |
| `customer` | Carrefour, Lidl, Tesco, Albert Heijn |
| `region` | FR, DE, NL |
| `actuals` | Real sales (0 for 2025 P7–P13 future) |
| `dp_forecast` | Demand planner forecast |
| `stat_forecast` | Statistical model forecast |
| `business_plan` | Annual sales team target |
