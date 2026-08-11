# Gold Evidence 数据结构与导入前校验方案

配套文件：

- `docs/program-catalog-export.json` — 24 个 Program 的精确名称清单
- `docs/evidence-collection-worksheet.md` — 采集规范

本文档描述**现有** gold seed 的数据结构（未做任何模型改动），以及数据回来后的导入前校验方案。

---

## 一、现有 gold seed 数据结构

### 1.1 `GoldRequirement`（`app/evaluation/gold_programs.py`）

```python
@dataclass(frozen=True)
class GoldRequirement:
    university_short_name: str          # 精确匹配 University.short_name
    program_name: str                   # 精确匹配 Program.name
    application_cycle: str              # ^\d{4}/\d{2}$，例 "2026/27"
    field_name: RequirementFieldName    # 10 选 1
    source_url: str                     # 官方 URL
    source_type: EvidenceSourceType     # 7 选 1
    basis: str                          # 采集依据说明

    # 以下 6 个值槽，按 field_name 决定填哪些，其余必须为 None
    numeric_value: Decimal | None = None
    date_value: date | None = None
    money_amount: Decimal | None = None
    money_currency: str | None = None
    text_value: str | None = None
    text_list_value: tuple[str, ...] | None = None
```

**注意两点现状**：

1. `basis` **不会入库** —— `to_evidence()` 没有把它传给 `EvidenceCreate`，它只存在于源码里。
2. `captured_at` 是**全局常量** `CAPTURED_AT = datetime(2026, 8, 9, tzinfo=UTC)`，18 条共用，
   无法逐条设置。如果新数据的采集日期不同，需要把 `captured_at` 改成 per-record 字段
   （小改动，不涉及 migration，因为 DB 列本来就存在）。

### 1.2 `field_name` → 值类型 → 必填槽位

| `field_name` | 值类型 | 必填槽位 | 其余槽位 |
|---|---|---|---|
| `ielts_overall` | numeric | `numeric_value` | 必须为 None |
| `ielts_min_band` | numeric | `numeric_value` | 必须为 None |
| `toefl_overall` | numeric | `numeric_value` | 必须为 None |
| `gpa_min` | numeric | `numeric_value` | 必须为 None |
| `gpa_scale` | numeric | `numeric_value` | 必须为 None |
| `work_experience_years` | numeric | `numeric_value` | 必须为 None |
| `application_deadline` | date | `date_value` | 必须为 None |
| `tuition` | money | `money_amount` **+** `money_currency` | 必须为 None |
| `degree_background` | text | `text_value` | 必须为 None |
| `prerequisite_courses` | text_list | `text_list_value` | 必须为 None |

> 槽位规则由 `EvidenceCreate.validate_value()` 和数据库 CHECK 约束**双重强制**。
> 多填一个槽位会直接抛错，不是警告。

### 1.3 `source_type` 枚举

`program_page` / `admission_page` / `fees_page` / `university_english_requirement` /
`official_pdf` / `official_faq` / `handbook`

### 1.4 数据库层硬约束

| 项 | 约束 |
|---|---|
| `application_cycle` | `String(7)`，正则 `^\d{4}/\d{2}$` |
| `numeric_value` | `Numeric(12, 3)` — 最多 9 位整数 + 3 位小数 |
| `money_amount` | `Numeric(14, 2)`，且 **≥ 0** |
| `money_currency` | `String(3)`，∈ `SGD / HKD / GBP / CNY / USD / EUR` |
| `text_value` | `String(1000)` |
| `text_list_value` | `ARRAY(String(200))` — **每一项**不超过 200 字符 |
| `source_url` | 长度 1–1000 |
| `content_hash` | ≤ 128，可选 |
| 唯一约束 | `program_requirement(program_id, application_cycle, field_name)` |

### 1.5 导入行为（`ingest_evidence`，本次不改）

对每一条证据，按 `(program, cycle, field)` 查找已有 requirement：

| 前置状态 | requirement 结果 | evidence 结果 | outcome |
|---|---|---|---|
| 无 requirement | 新建，`published` | `verified` | `PUBLISHED_INITIAL` |
| 已有且**值相同** | 保持 `published` | `verified` | `CORROBORATED` |
| 已有且**值不同** | 转 `conflict_pending` | `conflicted` | `CONFLICT_RECORDED` |

> **这条对交付数据的含义**：如果研究 Agent 对同一个
> `(大学, 项目, 周期, 字段)` 给出**两条值不同**的记录，第二条会把该
> requirement 打成 `conflict_pending`，需要人工复核才能恢复。
> 校验必须在导入前拦下这种自相矛盾。

---

## 二、建议的交付 JSON 格式

研究 Agent 请按此结构输出，可直接喂给校验器：

```json
{
  "captured_at": "2026-08-12",
  "records": [
    {
      "university_short_name": "NTU",
      "program_name": "Master of Computing in Applied Artificial Intelligence",
      "application_cycle": "2026/27",
      "field_name": "ielts_overall",
      "value": { "numeric_value": "6.5" },
      "source_url": "https://www.ntu.edu.sg/...",
      "source_type": "admission_page",
      "source_quote": "IELTS (Academic): Overall band of 6.5",
      "basis": "页面标题标注 Academic Year 2026-2027 Admission"
    },
    {
      "university_short_name": "UCL",
      "program_name": "MSc Machine Learning",
      "application_cycle": "2026/27",
      "field_name": "tuition",
      "value": { "money_amount": "38000", "money_currency": "GBP" },
      "source_url": "https://www.ucl.ac.uk/...",
      "source_type": "fees_page",
      "source_quote": "Tuition fees (2026/27): UK £extract, Overseas £38,000",
      "basis": "取 Overseas 全程学费"
    }
  ],
  "not_found": [
    {
      "university_short_name": "KCL",
      "program_name": "MSc Advanced Computing",
      "field_name": "gpa_min",
      "reason": "官网未公布数字 GPA 线，仅写 2:1 honours（已记入 degree_background）"
    }
  ],
  "program_urls": [
    {
      "university_short_name": "NTU",
      "program_name": "Master of Computing in Applied Artificial Intelligence",
      "program_url": "https://www.ntu.edu.sg/..."
    }
  ],
  "university_urls": [
    { "short_name": "NTU", "website_url": "https://www.ntu.edu.sg/" }
  ]
}
```

**`not_found` 数组同样重要** —— 它把"官网确认没有"和"没去查"区分开，
避免后续反复重查同一个字段。

---

## 三、导入前校验方案

设计原则：**全程只读，不写任何表**。校验与 seed 是两个独立步骤，
校验不通过则 seed 根本不启动。

### L1 结构校验（离线，不连数据库）

- JSON 可解析，必填键齐全
- `field_name` ∈ 10 个枚举值
- `source_type` ∈ 7 个枚举值
- `application_cycle` 匹配 `^\d{4}/\d{2}$`
- `captured_at` 可解析，且 **不晚于今天**（防未来日期）

### L2 值类型与槽位校验（离线）

- `field_name` → 值类型映射正确
- **只填了该值类型要求的槽位，其余全为 null**（对齐 §1.2）
- `tuition` 的 `money_amount` 与 `money_currency` 必须成对出现
- 精度与长度：`Numeric(12,3)` / `Numeric(14,2)` / text ≤1000 / list 每项 ≤200
- `money_currency` ∈ 支持币种，`money_amount` ≥ 0
- **常识区间**（超出即报错，用于拦截数量级错误）：
  - `ielts_overall` / `ielts_min_band` ∈ [0, 9]
  - `toefl_overall` ∈ [0, 120]
  - `gpa_min` ≤ `gpa_scale`
  - `work_experience_years` ∈ [0, 20]
  - `application_deadline` 落在申请周期前后的合理区间内
  - `tuition` 按币种设上下限（如 GBP 5,000–100,000），拦截"漏写千位"或"填了每年而非全程"

### L3 来源校验（离线）

- `source_url` 必须是 `https://`
- **域名必须以该大学的 `official_domain` 结尾** —— 用 `program-catalog-export.json`
  里的映射逐条比对。这一步同时拦截三类错误：第三方站、中介站、以及**串校**
  （把 UCL 的页面挂到 Imperial 名下）
- `source_quote` 非空且不少于 10 个字符
- `source_url` 长度 ≤ 1000

### L4 目录匹配校验（**只读**数据库）

- `(university_short_name, program_name)` 必须在库中**精确匹配到唯一一个** Program
- 这是**最容易出错的一环**：研究 Agent 极可能写成 `MSc AI`、
  `NTU MSc Artificial Intelligence`、或多一个空格
- 匹配失败时，用编辑距离给出最接近的候选，输出成可直接修正的清单

### L5 内部一致性与冲突预演（**只读**数据库）

- **交付数据内部去重**：同一 `(uni, program, cycle, field)` 若出现多条**值不同**的记录 →
  报错阻断（否则 seed 时会自己和自己冲突，见 §1.5）
- **与库中现状比对，预演每条记录会走哪个分支**：
  `PUBLISHED_INITIAL` / `CORROBORATED` / `CONFLICT_RECORDED`
- 输出预演汇总，让人在导入前就看清：新增多少、印证多少、**会触发多少条冲突复核**

### L6 GPA 红线专项检查

- 凡 `gpa_min` 有值，强制检查其 `source_quote`：
  - 若引用中含 `2:1` / `second class` / `honours` / `upper second` 而不含数字分数线
    → **高危，标记待人工裁决**（典型的把等级折算成 GPA 的错误）
  - 若引用中确含数字分数线（如 `CGPA 3.0 out of 4.0`）→ 通过
- 同理检查 `gpa_min` 与 `gpa_scale` 是否成对采集

### 输出格式

校验器输出一份分级报告：

| 级别 | 含义 | 后果 |
|---|---|---|
| `ERROR` | 结构/约束/来源违规 | **阻断导入** |
| `WARNING` | 需人工裁决（如 GPA 红线、区间可疑） | 逐条确认后方可导入 |
| `INFO` | 冲突预演、统计汇总 | 供决策参考 |

### 导入阶段的保护（校验通过后）

1. 先跑 `--dry-run`，只打印将执行的操作，不提交事务
2. 正式导入放在**单一事务**里，任一条失败**整体回滚**
3. 当前生产库 `requirement_evidence` 与 `program_requirement` 均为 **0 行**，
   首次导入天然无覆盖风险；后续增量导入前需先备份

---

## 四、当前状态与后续分工

**已完成**：审计、清单导出、结构说明、校验方案（本文档）。

**未改动任何生产数据与代码。** 已暂停：自动抓取、MCP、定时刷新、Evidence 模型改造。

**待你方交付**：24 个项目的官方数据（按 §2 格式）。

**数据到位后由我执行**：
`数据校验 → 转成 GoldRequirement → seed → Agent 查询测试`
