# 官方要求采集工作表

用于人工从大学官方域名采集申请要求，采集结果将以 `provenance = manual_verified` 入库。

---

## 一、硬约束（不满足则无法入库）

1. **只接受官方域名**（见第四节白名单）。中介站、留学论坛、排名站、第三方汇总一律不可用。
2. **每条数据必须同时提供**：`source_url` + `source_quote`（页面逐字原文）+ `captured_at`（采集日期）。
3. **官网没写的字段一律留空**，不要折算、不要推断、不要凭印象填。
4. **`2:1 honours` / `second class honours` 不是 GPA**，请填入 `degree_background`，`gpa_min` 保持空白。
   只有官网明确写出数字分数线（如 "minimum CGPA 3.0 out of 4.0"）时才填 `gpa_min` + `gpa_scale`。
5. **学费只记录本币金额**，不要做汇率换算。币种必须是 `SGD / HKD / GBP / CNY / USD / EUR` 之一。
6. **一个项目的不同字段可以来自不同 URL**（例如语言要求常在校级页面），请逐字段分别记录来源。

---

## 二、可采集字段清单

| 字段名 | 类型 | 填写格式 | 说明 |
|---|---|---|---|
| `ielts_overall` | 数值 | `6.5` | 雅思总分 |
| `ielts_min_band` | 数值 | `6.0` | 雅思单项最低分 |
| `toefl_overall` | 数值 | `100` | 托福总分 |
| `gpa_min` | 数值 | `3.0` | **仅当官网给出数字线** |
| `gpa_scale` | 数值 | `4.0` | 与 `gpa_min` 成对出现 |
| `work_experience_years` | 数值 | `2` | 要求的工作年限 |
| `application_deadline` | 日期 | `2026-01-31` | 多轮次时填**最后一轮**，并把完整轮次写进 source_quote |
| `tuition` | 金额 | `63220` + `SGD` | 金额 + 币种，全程学费 |
| `degree_background` | 文本 | 原文照抄 | 学历背景要求 |
| `prerequisite_courses` | 文本列表 | 每行一项 | 先修课程要求 |

### `application_cycle` 格式

必须是 `YYYY/YY`，例如 `2026/27`。**以页面自身声明的学年为准**，不要按采集时间推断。
页面没有明确学年时，请在备注里写清楚你依据什么判断的。

### `source_type`（该字段来自哪类页面）

`program_page` / `admission_page` / `fees_page` / `university_english_requirement` /
`official_pdf` / `official_faq` / `handbook`

---

## 三、单条记录填写模板

```
项目: NTU / Master of Computing in Applied Artificial Intelligence
字段: ielts_overall
值: 6.5
application_cycle: 2026/27
source_url: https://www.ntu.edu.sg/...
source_type: admission_page
captured_at: 2026-08-11
source_quote: "IELTS (Academic): Overall band of 6.5"
备注: (可选，例如学年依据、轮次说明)
```

---

## 四、官方域名白名单

| 大学 | 官方域名 | 白名单状态 |
|---|---|---|
| NUS | `nus.edu.sg` | 已在白名单 |
| NTU | `ntu.edu.sg` | 已在白名单 |
| HKUST | `hkust.edu.hk` | 已在白名单 |
| CUHK | `cuhk.edu.hk` | 已在白名单 |
| HKU | `hku.hk`（含 `*.hku.hk` 子域） | 已在白名单 |
| Imperial | `imperial.ac.uk` | 已在白名单 |
| UCL | `ucl.ac.uk` | 已在白名单 |
| Edinburgh | `ed.ac.uk`（含 `study.ed.ac.uk`） | 已在白名单 |
| Manchester | `manchester.ac.uk` | **待加入代码** |
| KCL | `kcl.ac.uk` | **待加入代码** |
| Warwick | `warwick.ac.uk` | **待加入代码** |
| Southampton | `southampton.ac.uk` | **待加入代码** |

---

## 五、项目清单（24 个）

标记说明：`[试点]` = 本轮优先采集；`[存量]` = 源码中已有数据但**尚未入库**，需复核。

### 新加坡

**NUS — National University of Singapore** · `nus.edu.sg`

1. `[存量]` **Master of Computing in Artificial Intelligence**
   - 已有：`ielts_overall` 6.0、`degree_background`、`application_deadline` 2026-01-31（cycle 2026/27）
   - 缺：`gpa_min`、`tuition`
   - 现有来源：`comp.nus.edu.sg/programmes/pg/mcomp-ai/admissions/`、`.../application/`
2. **MSc Artificial Intelligence & Innovation** — 全部字段待采集

**NTU — Nanyang Technological University** · `ntu.edu.sg`

3. `[试点]` **Master of Computing in Applied Artificial Intelligence** — 全部字段待采集
4. `[试点]` **MSc Enterprise Artificial Intelligence** — 全部字段待采集
5. `[试点][存量]` **MSc Artificial Intelligence**
   - 已有：`ielts_overall` 6.5、`toefl_overall` 100、`degree_background`、`tuition` SGD 63,220
   - 缺：`gpa_min`、`application_deadline`
   - **⚠ 待确认**：现标 cycle `2025/26`，来源页写的是学费适用于 "Academic Year 2025/26 **and after**"。
     请确认该页当前是否适用于 **2026/27**；若是，四条记录统一改标 `2026/27`。
   - 现有来源：`ntu.edu.sg/education/graduate-programme/master-of-science-in-artificial-intelligence`

### 香港

**HKUST — The Hong Kong University of Science and Technology** · `hkust.edu.hk`

6. `[存量]` **MSc Artificial Intelligence**
   - 已有：`ielts_overall` 6.5、`ielts_min_band` 5.5、`degree_background`、`tuition` HKD 400,000、`application_deadline` 2026-03-01（cycle 2026/27）
   - 缺：`gpa_min`
   - 现有来源：`prog-crs.hkust.edu.hk/pgprog/2026-27/msc-ai`
7. **MSc Information Technology** — 全部字段待采集
8. **MSc Big Data Technology** — 全部字段待采集

**CUHK — The Chinese University of Hong Kong** · `cuhk.edu.hk`

9. **MSc Artificial Intelligence** — 全部字段待采集
10. **MSc Computer Science** — 全部字段待采集

**HKU — The University of Hong Kong** · `hku.hk`

11. `[存量]` **MSc Computer Science**
    - 已有：`degree_background`、`application_deadline` 2026-04-30（cycle 2026/27）
    - 缺：`ielts_overall`、`gpa_min`、`tuition`
    - 备注：语言要求预计在**校级页面**，`source_type` 用 `university_english_requirement`
    - 现有来源：`master.cds.hku.hk/msccs/admission/application-details/`

### 英国

**Imperial — Imperial College London** · `imperial.ac.uk`

12. `[试点]` **MSc Computing (Artificial Intelligence and Machine Learning)** — 全部字段待采集
    - 备注：语言要求通常在校级 English requirement 页

**UCL — University College London** · `ucl.ac.uk`

13. `[试点]` **MSc Machine Learning** — 全部字段待采集
14. `[试点]` **MSc Data Science and Machine Learning** — 全部字段待采集
15. `[试点]` **MSc Computer Science** — 全部字段待采集
    - 备注：UCL 三个项目可能共用校级语言要求页，但**学费和截止日期各不相同**，请分别采集

**Edinburgh — The University of Edinburgh** · `ed.ac.uk`

16. `[存量]` **MSc Artificial Intelligence**
    - 已有：`ielts_overall` 7.0、`ielts_min_band` 6.5、`degree_background`、`application_deadline` 2026-03-31（cycle 2026/27）
    - 缺：`gpa_min`、`tuition`
    - 现有来源：`study.ed.ac.uk/postgraduate/degrees/index.php?r=site/view&id=107`
17. **MSc Computer Science** — 全部字段待采集

**Manchester — The University of Manchester** · `manchester.ac.uk`

18. **MSc Artificial Intelligence** — 全部字段待采集
19. **MSc Machine Learning** — 全部字段待采集

**KCL — King's College London** · `kcl.ac.uk`

20. **MSc Artificial Intelligence** — 全部字段待采集
21. **MSc Advanced Computing** — 全部字段待采集

**Warwick — The University of Warwick** · `warwick.ac.uk`

22. **MSc Applied Artificial Intelligence** — 全部字段待采集

**Southampton — University of Southampton** · `southampton.ac.uk`

23. **MSc Artificial Intelligence** — 全部字段待采集
24. **MSc Machine Learning** — 全部字段待采集

---

## 六、顺带需要补的两项 URL

采集过程中请一并记录，用于填充数据库现有空字段：

- **`University.website_url`** ×12 — 每所大学官网首页
- **`Program.program_url`** ×24 — 每个项目的官方主页面

这两项目前**全部为 NULL**，是 on-demand 抽取功能的必要前提。

---

## 七、试点范围（建议先做这 7 个）

| # | 大学 | Program |
|---|---|---|
| 3 | NTU | Master of Computing in Applied Artificial Intelligence |
| 4 | NTU | MSc Enterprise Artificial Intelligence |
| 5 | NTU | MSc Artificial Intelligence（含 cycle 确认） |
| 12 | Imperial | MSc Computing (Artificial Intelligence and Machine Learning) |
| 13 | UCL | MSc Machine Learning |
| 14 | UCL | MSc Data Science and Machine Learning |
| 15 | UCL | MSc Computer Science |

这 7 个覆盖：两个地区、6 个空项目 + 1 个有存量数据（用于验证 corroborate / conflict 分支）、
校级语言要求页、GBP 学费、以及"2:1 不折算成 GPA"这条红线。三个域名均已在白名单内。
