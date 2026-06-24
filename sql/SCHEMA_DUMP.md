# Warehouse schema dump

> Generated 2026-06-24 14:08 against `billy-ai-postgresql` / `ai-agent-db` / `warehouse`

**13 tables in `warehouse`:** `dim_customer_group`, `dim_fiscal_period`, `dim_fiscal_week`, `dim_material`, `dim_material_group`, `dim_material_sales_organization`, `dim_plant`, `dim_product_hierarchy`, `dim_sales_organization`, `fact_actuals`, `fact_budget`, `fact_forecast`, `fact_inventory`


---

## `warehouse.dim_customer_group`

**Rows:** 196


| # | column | type | null | detail |
|---|---|---|---|---|
| 1 | `customer_group_key` | text | NO |  |
| 2 | `customer_group_name` | text | YES |  |
| 3 | `created_at` | timestamp with time zone | NO |  |
| 4 | `updated_at` | timestamp with time zone | NO |  |

**PK:** (customer_group_key)

**Sample rows:**

| customer_group_key | customer_group_name | created_at | updated_at |
|---|---|---|---|
| A2 | MIGROS | 2026-06-23 11:40:38.388687+00:00 | 2026-06-24 06:58:29.097253+00:00 |
| AI | GÜNEDLER | 2026-06-23 11:42:17.951075+00:00 | 2026-06-24 06:58:29.097253+00:00 |
| BE | OTHER DIRECT | 2026-06-23 10:42:31.045695+00:00 | 2026-06-24 06:58:29.097253+00:00 |

---

## `warehouse.dim_fiscal_period`

**Rows:** 44


| # | column | type | null | detail |
|---|---|---|---|---|
| 1 | `fiscal_period_key` | text | NO |  |
| 2 | `fiscal_year` | integer | YES | (32,0) |
| 3 | `fiscal_period_number` | integer | YES | (32,0) |
| 4 | `created_at` | timestamp with time zone | NO |  |
| 5 | `updated_at` | timestamp with time zone | NO |  |

**PK:** (fiscal_period_key)

**Sample rows:**

| fiscal_period_key | fiscal_year | fiscal_period_number | created_at | updated_at |
|---|---|---|---|---|
| 001.2025 | 2025 | 1 | 2026-06-23 10:40:37.506816+00:00 | 2026-06-24 06:58:29.097253+00:00 |
| 001.2026 | 2026 | 1 | 2026-06-23 10:41:01.544980+00:00 | 2026-06-24 06:58:29.097253+00:00 |
| 001.2027 | 2027 | 1 | 2026-06-23 10:41:01.544980+00:00 | 2026-06-24 06:58:29.097253+00:00 |

---

## `warehouse.dim_fiscal_week`

**Rows:** 11


| # | column | type | null | detail |
|---|---|---|---|---|
| 1 | `fiscal_week_key` | text | NO |  |
| 2 | `fiscal_period_key` | text | NO |  |
| 3 | `fiscal_year` | integer | YES | (32,0) |
| 4 | `week_start_date` | date | YES |  |
| 5 | `week_end_date` | date | YES |  |
| 6 | `created_at` | timestamp with time zone | NO |  |
| 7 | `updated_at` | timestamp with time zone | NO |  |

**PK:** (fiscal_week_key)

**FKs:**
- `fiscal_period_key` → `warehouse.dim_fiscal_period.fiscal_period_key`

**Sample rows:**

| fiscal_week_key | fiscal_period_key | fiscal_year | week_start_date | week_end_date | created_at | updated_at |
|---|---|---|---|---|---|---|
| 05.2026 | 002.2026 | 2026 | 2025-10-26 | 2025-11-01 | 2026-06-23 11:21:11.636985+00:00 | 2026-06-24 06:58:29.097253+00:00 |
| 09.2026 | 003.2026 | 2026 | 2025-11-23 | 2025-11-29 | 2026-06-23 11:20:48.091167+00:00 | 2026-06-24 06:58:29.097253+00:00 |
| 14.2026 | 004.2026 | 2026 | 2025-12-28 | 2026-01-03 | 2026-06-23 11:20:49.533366+00:00 | 2026-06-24 06:58:29.097253+00:00 |

---

## `warehouse.dim_material`

**Rows:** 13530


| # | column | type | null | detail |
|---|---|---|---|---|
| 1 | `material_key` | text | NO |  |
| 2 | `material_description` | text | YES |  |
| 3 | `base_unit_of_measure` | text | YES |  |
| 4 | `material_type_code` | text | YES |  |
| 5 | `material_type_description` | text | YES |  |
| 6 | `cross_plant_material_status` | text | YES |  |
| 7 | `cross_distribution_chain_material_status` | text | YES |  |
| 8 | `product_hierarchy_key` | text | YES |  |
| 9 | `created_at` | timestamp with time zone | NO |  |
| 10 | `updated_at` | timestamp with time zone | NO |  |

**PK:** (material_key)

**FKs:**
- `product_hierarchy_key` → `warehouse.dim_product_hierarchy.product_hierarchy_key`

**Sample rows:**

| material_key | material_description | base_unit_of_measure | material_type_code | material_type_description | cross_plant_material_status | cross_distribution_chain_material_status | product_hierarchy_key | created_at | updated_at |
|---|---|---|---|---|---|---|---|---|---|
| PLVAUT2 |  |  |  |  |  |  |  | 2026-06-23 10:40:37.506816+00:00 | 2026-06-24 06:58:29.097253+00:00 |
| 730195 |  |  |  |  |  |  |  | 2026-06-23 10:42:40.592724+00:00 | 2026-06-24 06:58:29.097253+00:00 |
| LB18269 |  |  |  |  |  |  |  | 2026-06-23 10:42:40.592724+00:00 | 2026-06-24 06:58:29.097253+00:00 |

---

## `warehouse.dim_material_group`

**Rows:** 1763


| # | column | type | null | detail |
|---|---|---|---|---|
| 1 | `material_group_key` | text | NO |  |
| 2 | `material_group_description` | text | YES |  |
| 3 | `material_group_1_code` | text | YES |  |
| 4 | `material_group_1_description` | text | YES |  |
| 5 | `material_group_2_code` | text | YES |  |
| 6 | `material_group_2_description` | text | YES |  |
| 7 | `material_group_3_code` | text | YES |  |
| 8 | `material_group_3_description` | text | YES |  |
| 9 | `material_group_4_code` | text | YES |  |
| 10 | `material_group_4_description` | text | YES |  |
| 11 | `material_group_5_code` | text | YES |  |
| 12 | `material_group_5_description` | text | YES |  |
| 13 | `created_at` | timestamp with time zone | NO |  |
| 14 | `updated_at` | timestamp with time zone | NO |  |

**PK:** (material_group_key)

**Sample rows:**

| material_group_key | material_group_description | material_group_1_code | material_group_1_description | material_group_2_code | material_group_2_description | material_group_3_code | material_group_3_description | material_group_4_code | material_group_4_description | material_group_5_code | material_group_5_description | created_at | updated_at |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MG-FGAE001-C40-000-B03-R01-852 | AEROSOL | C40 | CLEAR | 000 | LIQUID | B03 | PEST & DISEASE | R01 | NATURAL | 852 | PYRETHRUM | 2026-06-24 06:58:29.097253+00:00 | 2026-06-24 06:58:29.097253+00:00 |
| MG-FGAE001-C40-000-B03-R01-868 | AEROSOL | C40 | CLEAR | 000 | LIQUID | B03 | PEST & DISEASE | R01 | NATURAL | 868 | PYRETHRUM + PBO | 2026-06-24 06:58:29.097253+00:00 | 2026-06-24 06:58:29.097253+00:00 |
| MG-FGAE001-F21-000-C11-R02-364 | AEROSOL | F21 | FERTILIGENE | 000 | LIQUID | C11 | INSECTICIDES MENAGER SPE | R02 | SYNTHETIC | 364 | CYPERMETHRIN + TETRAMETHRIN | 2026-06-24 06:58:29.097253+00:00 | 2026-06-24 06:58:29.097253+00:00 |

---

## `warehouse.dim_material_sales_organization`

**Rows:** 6904


| # | column | type | null | detail |
|---|---|---|---|---|
| 1 | `material_key` | text | NO |  |
| 2 | `sales_organization_key` | text | NO |  |
| 3 | `material_group_key` | text | YES |  |
| 4 | `created_at` | timestamp with time zone | NO |  |
| 5 | `updated_at` | timestamp with time zone | NO |  |

**PK:** (material_key, sales_organization_key)

**FKs:**
- `material_group_key` → `warehouse.dim_material_group.material_group_key`
- `material_key` → `warehouse.dim_material.material_key`
- `sales_organization_key` → `warehouse.dim_sales_organization.sales_organization_key`

**Sample rows:**

| material_key | sales_organization_key | material_group_key | created_at | updated_at |
|---|---|---|---|---|
| 010971 | 1110 | MG-FGBB001-S10-006-D06-R02-000 | 2026-06-24 06:58:29.097253+00:00 | 2026-06-24 06:58:29.097253+00:00 |
| 010971 | 1810 | MG-FGBB001-S10-006-D06-R02-000 | 2026-06-24 06:58:29.097253+00:00 | 2026-06-24 06:58:29.097253+00:00 |
| 011004 | 1110 | MG-FGBX001-W10-000-B02-R03-572 | 2026-06-24 06:58:29.097253+00:00 | 2026-06-24 06:58:29.097253+00:00 |

---

## `warehouse.dim_plant`

**Rows:** 69


| # | column | type | null | detail |
|---|---|---|---|---|
| 1 | `plant_key` | text | NO |  |
| 2 | `plant_name` | text | YES |  |
| 3 | `created_at` | timestamp with time zone | NO |  |
| 4 | `updated_at` | timestamp with time zone | NO |  |

**PK:** (plant_key)

**Sample rows:**

| plant_key | plant_name | created_at | updated_at |
|---|---|---|---|
| # | Not assigned | 2026-06-23 11:40:38.388687+00:00 | 2026-06-24 06:58:29.097253+00:00 |
| A300 | SUB CON FERTS & CONT | 2026-06-23 10:40:37.506816+00:00 | 2026-06-24 06:58:29.097253+00:00 |
| A400 | ASB - WERK NEUSTADT | 2026-06-23 10:40:37.506816+00:00 | 2026-06-24 06:58:29.097253+00:00 |

---

## `warehouse.dim_product_hierarchy`

**Rows:** 107


| # | column | type | null | detail |
|---|---|---|---|---|
| 1 | `product_hierarchy_key` | text | NO |  |
| 2 | `level_1_code` | text | YES |  |
| 3 | `level_1_description` | text | YES |  |
| 4 | `level_2_code` | text | YES |  |
| 5 | `level_2_description` | text | YES |  |
| 6 | `level_3_code` | text | YES |  |
| 7 | `level_3_description` | text | YES |  |
| 8 | `level_4_code` | text | YES |  |
| 9 | `level_4_description` | text | YES |  |
| 10 | `created_at` | timestamp with time zone | NO |  |
| 11 | `updated_at` | timestamp with time zone | NO |  |

**PK:** (product_hierarchy_key)

**Sample rows:**

| product_hierarchy_key | level_1_code | level_1_description | level_2_code | level_2_description | level_3_code | level_3_description | level_4_code | level_4_description | created_at | updated_at |
|---|---|---|---|---|---|---|---|---|---|---|
| # | # | Not assigned | # | Not assigned | # | Not assigned | # | Not assigned | 2026-06-24 06:58:29.097253+00:00 | 2026-06-24 06:58:29.097253+00:00 |
| 1010101005 | 10 | LAWNS | 1010 | LAWN FOOD | 1010101 | STRAIGHT LAWN FOOD | 1010101005 | UNIVERSAL LAWN FOOD | 2026-06-24 06:58:29.097253+00:00 | 2026-06-24 06:58:29.097253+00:00 |
| 1010101010 | 10 | LAWNS | 1010 | LAWN FOOD | 1010101 | STRAIGHT LAWN FOOD | 1010101010 | AUTUMN LAWN FOOD | 2026-06-24 06:58:29.097253+00:00 | 2026-06-24 06:58:29.097253+00:00 |

---

## `warehouse.dim_sales_organization`

**Rows:** 8


| # | column | type | null | detail |
|---|---|---|---|---|
| 1 | `sales_organization_key` | text | NO |  |
| 2 | `sales_organization_name` | text | YES |  |
| 3 | `created_at` | timestamp with time zone | NO |  |
| 4 | `updated_at` | timestamp with time zone | NO |  |

**PK:** (sales_organization_key)

**Sample rows:**

| sales_organization_key | sales_organization_name | created_at | updated_at |
|---|---|---|---|
| 1010 | Evergreen Germany | 2026-06-23 10:40:37.506816+00:00 | 2026-06-24 06:58:29.097253+00:00 |
| 1110 | Evergreen UK | 2026-06-23 10:40:37.506816+00:00 | 2026-06-24 06:58:29.097253+00:00 |
| 1210 | Evergreen France | 2026-06-23 10:40:37.506816+00:00 | 2026-06-24 06:58:29.097253+00:00 |

---

## `warehouse.fact_actuals`

**Rows:** 269507


| # | column | type | null | detail |
|---|---|---|---|---|
| 1 | `fact_actuals_id` | bigint | NO | (64,0) |
| 2 | `sales_organization_key` | text | NO |  |
| 3 | `material_key` | text | NO |  |
| 4 | `customer_group_key` | text | NO |  |
| 5 | `fiscal_period_key` | text | NO |  |
| 6 | `plant_key` | text | NO |  |
| 7 | `quantity` | numeric | YES |  |
| 8 | `revenue` | numeric | YES |  |
| 9 | `load_id` | uuid | NO |  |

**PK:** (fact_actuals_id)

**FKs:**
- `customer_group_key` → `warehouse.dim_customer_group.customer_group_key`
- `fiscal_period_key` → `warehouse.dim_fiscal_period.fiscal_period_key`
- `load_id` → `ingestion.etl_load.load_id`
- `material_key` → `warehouse.dim_material.material_key`
- `plant_key` → `warehouse.dim_plant.plant_key`
- `sales_organization_key` → `warehouse.dim_sales_organization.sales_organization_key`

**Sample rows:**

| fact_actuals_id | sales_organization_key | material_key | customer_group_key | fiscal_period_key | plant_key | quantity | revenue | load_id |
|---|---|---|---|---|---|---|---|---|
| 1 | 1010 | 100603 | AV | 006.2025 | C100 | 9000 | 20700 | 2a1dbcf3-0649-48e7-8194-3c3d2229475e |
| 2 | 1010 | 100604 | AV | 006.2025 | C100 | 16170 | 64033.2 | 2a1dbcf3-0649-48e7-8194-3c3d2229475e |
| 3 | 1010 | 11658 | AD | 001.2025 | A500 | 3 | 24.3 | 2a1dbcf3-0649-48e7-8194-3c3d2229475e |

---

## `warehouse.fact_budget`

**Rows:** 38249


| # | column | type | null | detail |
|---|---|---|---|---|
| 1 | `fact_budget_id` | bigint | NO | (64,0) |
| 2 | `fiscal_period_key` | text | NO |  |
| 3 | `sales_organization_key` | text | NO |  |
| 4 | `material_key` | text | NO |  |
| 5 | `customer_group_key` | text | NO |  |
| 6 | `quantity` | numeric | YES |  |
| 7 | `value` | numeric | YES |  |
| 8 | `load_id` | uuid | NO |  |

**PK:** (fact_budget_id)

**FKs:**
- `customer_group_key` → `warehouse.dim_customer_group.customer_group_key`
- `fiscal_period_key` → `warehouse.dim_fiscal_period.fiscal_period_key`
- `load_id` → `ingestion.etl_load.load_id`
- `material_key` → `warehouse.dim_material.material_key`
- `sales_organization_key` → `warehouse.dim_sales_organization.sales_organization_key`

**Sample rows:**

| fact_budget_id | fiscal_period_key | sales_organization_key | material_key | customer_group_key | quantity | value | load_id |
|---|---|---|---|---|---|---|---|
| 1 | 001.2026 | 3710 | 1010444 | JB | 167 | 441 | eabd7b8e-854c-45a5-86df-4cef513734ce |
| 2 | 001.2026 | 3710 | 1010444 | JN | 355 | 896 | eabd7b8e-854c-45a5-86df-4cef513734ce |
| 3 | 001.2026 | 3710 | 1010444 | JO | 13 | 34 | eabd7b8e-854c-45a5-86df-4cef513734ce |

---

## `warehouse.fact_forecast`

**Rows:** 3231663


| # | column | type | null | detail |
|---|---|---|---|---|
| 1 | `fact_forecast_id` | bigint | NO | (64,0) |
| 2 | `sales_organization_key` | text | NO |  |
| 3 | `material_key` | text | NO |  |
| 4 | `customer_group_key` | text | NO |  |
| 5 | `forecast_version_key` | text | NO |  |
| 6 | `fiscal_period_key` | text | NO |  |
| 7 | `quantity` | numeric | YES |  |
| 8 | `revenue` | numeric | YES |  |
| 9 | `cogs` | numeric | YES |  |
| 10 | `load_id` | uuid | NO |  |

**PK:** (fact_forecast_id)

**FKs:**
- `customer_group_key` → `warehouse.dim_customer_group.customer_group_key`
- `fiscal_period_key` → `warehouse.dim_fiscal_period.fiscal_period_key`
- `forecast_version_key` → `warehouse.dim_fiscal_week.fiscal_week_key`
- `load_id` → `ingestion.etl_load.load_id`
- `material_key` → `warehouse.dim_material.material_key`
- `sales_organization_key` → `warehouse.dim_sales_organization.sales_organization_key`

**Sample rows:**

| fact_forecast_id | sales_organization_key | material_key | customer_group_key | forecast_version_key | fiscal_period_key | quantity | revenue | cogs | load_id |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1910 | 12130 | EA | 44.2025 | 011.2025 | 85 | 282.62 | -116.77 | e0134535-aa52-440f-94c4-c03fc099d895 |
| 2 | 1910 | 12130 | ED | 44.2025 | 011.2025 | 423 | 1413.08 | -583.85 | e0134535-aa52-440f-94c4-c03fc099d895 |
| 3 | 1910 | 12130 | EJ | 44.2025 | 011.2025 | 423 | 1413.08 | -583.85 | e0134535-aa52-440f-94c4-c03fc099d895 |

---

## `warehouse.fact_inventory`

**Rows:** 225986


| # | column | type | null | detail |
|---|---|---|---|---|
| 1 | `fact_inventory_id` | bigint | NO | (64,0) |
| 2 | `sales_organization_key` | text | NO |  |
| 3 | `material_key` | text | NO |  |
| 4 | `plant_key` | text | NO |  |
| 5 | `fiscal_period_key` | text | NO |  |
| 6 | `unit_of_measure` | text | NO |  |
| 7 | `quantity` | numeric | YES |  |
| 8 | `value` | numeric | YES |  |
| 9 | `load_id` | uuid | NO |  |

**PK:** (fact_inventory_id)

**FKs:**
- `fiscal_period_key` → `warehouse.dim_fiscal_period.fiscal_period_key`
- `load_id` → `ingestion.etl_load.load_id`
- `material_key` → `warehouse.dim_material.material_key`
- `plant_key` → `warehouse.dim_plant.plant_key`
- `sales_organization_key` → `warehouse.dim_sales_organization.sales_organization_key`

**Sample rows:**

| fact_inventory_id | sales_organization_key | material_key | plant_key | fiscal_period_key | unit_of_measure | quantity | value | load_id |
|---|---|---|---|---|---|---|---|---|
| 1 | 1010 | 1246 | A500 | 001.2025 | EA | 51 | 98.21 | 01199680-043f-45a4-8b1e-1dee12685645 |
| 2 | 1010 | 12560 | A400 | 001.2025 | EA | 3528 | 12418.56 | 01199680-043f-45a4-8b1e-1dee12685645 |
| 3 | 1010 | 1300 | A500 | 001.2025 | EA | 5496 | 15948.02 | 01199680-043f-45a4-8b1e-1dee12685645 |
