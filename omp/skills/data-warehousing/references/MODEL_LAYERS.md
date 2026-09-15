# Model Layers

Organize data warehouse models into distinct layers with clear responsibilities, dependencies, and ownership boundaries.

## Layer Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        MART LAYER                           │
│   Consumer-specific presentations (dashboards, reports)     │
│   Reads from: Domain only                                   │
└─────────────────────────────────────────────────────────────┘
                              ↑
┌─────────────────────────────────────────────────────────────┐
│                       DOMAIN LAYER                          │
│   Public dimensional models (facts, dimensions)             │
│   Reads from: Base, Intermediate                            │
└─────────────────────────────────────────────────────────────┘
                              ↑
┌─────────────────────────────────────────────────────────────┐
│                    INTERMEDIATE LAYER                       │
│   Private staging transformations                           │
│   Reads from: Base only                                     │
└─────────────────────────────────────────────────────────────┘
                              ↑
┌─────────────────────────────────────────────────────────────┐
│                        BASE LAYER                           │
│   Light views on raw source data                            │
│   Reads from: dbt sources only                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Base Layer

Base models are **light wrapper views** on raw data with minimal transformation. Their purpose is to provide a conformed table API for raw data.

### Principles

| Rule | Description |
|------|-------------|
| **Single source** | Read from exactly one `{{ source() }}` |
| **No renaming** | Column names match source (except standard conforming) |
| **No filtering** | Include all records from source |
| **No derivation** | No new calculated columns |
| **Always views** | Materialized as views for freshness |

### Permissible Transformations

- Type casting (e.g., integer IDs to strings for consistency)
- Date/datetime/timestamp type conforming
- JSON field extraction (without renaming extracted fields)
- Standard conforming renames (e.g., Rails implicit `id` → `<entity>_id`)

### Example

```sql
-- GOOD: Minimal base model
{{ config(materialized="view") }}

SELECT
    CAST(id AS STRING) AS customer_id,  -- Standard ID conforming
    email,
    first_name,
    last_name,
    created_at,
    updated_at,
FROM {{ source('crm', 'customers') }}
```

```sql
-- BAD: Violates base model principles
{{ config(materialized="table") }}  -- ❌ Should be view

SELECT
    id AS customer_id,
    UPPER(first_name) AS customer_first_name,  -- ❌ Transformation + rename
    LOWER(last_name) AS customer_last_name,    -- ❌ Transformation + rename
    CONCAT(first_name, ' ', last_name) AS full_name,  -- ❌ New derived column
    DATEDIFF(CURRENT_DATE(), created_at) AS account_age_days,  -- ❌ Calculation
FROM {{ source('crm', 'customers') }}
WHERE status = 'active'  -- ❌ Filtering
```

### File Organization

```
models/base/
├── crm/
│   ├── base__salesforce_accounts.sql
│   ├── base__salesforce_accounts.yml
│   ├── base__salesforce_contacts.sql
│   └── base__salesforce_contacts.yml
├── ecommerce/
│   ├── base__shopify_orders.sql
│   └── base__shopify_orders.yml
└── finance/
    ├── base__netsuite_invoices.sql
    └── base__netsuite_invoices.yml
```

---

## Intermediate Layer

Intermediate models are **private staging tables** for organizing complex transformations. They are explicitly internal and not intended for direct consumption.

### Principles

| Rule | Description |
|------|-------------|
| **Private by design** | Not for ad-hoc queries or dashboard use |
| **Single consumer** | Built for a specific downstream domain model |
| **Owner discretion** | Can be changed/dropped without downstream coordination |
| **No `fct_`/`dim_` prefix** | Reserved for domain layer |

### Ownership Contract

- Intermediate model owners maintain only the documented downstream dependencies
- New dependencies require explicit approval and documentation updates
- No availability guarantees for undocumented consumers

### File Organization

Organize intermediate models in subdirectories named after their downstream consumer:

```
models/intermediate/
├── sales/
│   └── fct_daily_sales_snapshot/        # Supports fct_daily_sales_snapshot
│       ├── daily_sales_base.sql
│       ├── daily_sales_discounts.sql
│       └── daily_sales_returns.sql
└── customers/
    └── dim_customers/                    # Supports dim_customers
        ├── customer_attributes.sql
        └── customer_segments.sql
```

### Documentation Requirement

Schema YAML must specify sanctioned downstream consumers:

```yaml
models:
  - name: daily_sales_base
    description: |
      Intermediate model for daily sales aggregation.
      
      **Intended Consumer**: `fct_daily_sales_snapshot`
      **Owner**: Sales Analytics team
      
      ⚠️ This is a private intermediate model. Do not reference directly.
```

---

## Domain Layer

Domain models are the **public dimensional model** layer containing facts and dimensions. These are the primary analytical building blocks.

### Principles

| Rule | Description |
|------|-------------|
| **Public API** | Schema changes require downstream coordination |
| **Dimensional modeling** | Strict fact/dimension separation |
| **Normalized** | Attributes on dimensions; resolve at query time |
| **Surrogate keys** | Use `generate_surrogate_key()` for dimensions |

### Naming Convention

| Type | Pattern | Example |
|------|---------|---------|
| Dimension | `dim_<entity>` | `dim_customers`, `dim_products` |
| Fact | `fct_<process>` | `fct_orders`, `fct_page_views` |

### File Organization

```
models/
├── sales/
│   ├── dim_customers.sql
│   ├── dim_customers.yml
│   ├── dim_products.sql
│   ├── dim_products.yml
│   ├── fct_orders.sql
│   ├── fct_orders.yml
│   ├── fct_order_line_items.sql
│   └── fct_order_line_items.yml
└── marketing/
    ├── dim_campaigns.sql
    ├── fct_campaign_events.sql
    └── fct_email_sends.sql
```

### Dependency Rules

Domain models may read from:
- ✅ Base models
- ✅ Intermediate models
- ❌ Raw `{{ source() }}` references
- ❌ Hardcoded table paths
- ❌ Other domain models (prefer intermediate layer for composition)

---

## Mart Layer

Mart models are **consumer-specific presentations** optimized for particular use cases like dashboards, reports, or applications.

### Principles

| Rule | Description |
|------|-------------|
| **Consumer-focused** | Built for specific dashboards/applications |
| **Domain-sourced** | Read only from domain models |
| **Denormalized OK** | Optimize for query patterns, not normalization |
| **Metrics layer** | Aggregate, bin, filter domain data |

### What Marts Are For

- Reusable metric aggregations (e.g., monthly revenue, churn rates)
- Dashboard-specific query patterns
- Tracking downstream dependencies for domain maintainers

### What Marts Are NOT For

- Shadow modeling of attributes that belong in domain tables
- New fact derivation at the grain of existing domain models
- Direct consumption of base or intermediate models

### File Organization

```
models/marts/
├── mart_sales/
│   ├── executive_dashboard/
│   │   ├── exec_revenue_summary.sql
│   │   ├── exec_revenue_summary.yml
│   │   └── exec_dashboard_access.sql
│   └── ops_dashboard/
│       ├── ops_daily_orders.sql
│       └── ops_dashboard_access.sql
└── mart_marketing/
    └── campaign_analytics/
        ├── campaign_performance.sql
        └── campaign_attribution.sql
```

### Dependency Rules

Mart models may read from:
- ✅ Domain models (`fct_*`, `dim_*`)
- ❌ Base models
- ❌ Intermediate models
- ❌ Raw sources or hardcoded paths

⚠️ **Warning**: If a mart reads from base or intermediate models, maintainers of those upstream models are not responsible for fixing breakages.

---

## Layer Summary

| Layer | Visibility | Materialization | Reads From |
|-------|------------|-----------------|------------|
| Base | Internal | View | Sources only |
| Intermediate | Private | Table/Ephemeral | Base only |
| Domain | Public | Table/Incremental | Base, Intermediate |
| Mart | Consumer-specific | Table | Domain only |
