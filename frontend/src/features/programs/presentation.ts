import type {
  ApplicationStatus,
  EvidencePublic,
  EvidenceStatus,
  ProgramWithUniversityPublic,
  RequirementFieldName,
  RequirementPublic,
  TaskStatus,
  UserProfilePublic,
} from "@/client"

export const regionLabels: Record<string, string> = {
  hong_kong: "中国香港",
  singapore: "新加坡",
  united_kingdom: "英国",
}

export const requirementLabels: Record<RequirementFieldName, string> = {
  ielts_overall: "雅思总分",
  ielts_min_band: "雅思单项",
  toefl_overall: "托福总分",
  gpa_min: "最低 GPA",
  gpa_scale: "GPA 满分",
  work_experience_years: "工作经验",
  application_deadline: "申请截止日期",
  tuition: "学费",
  degree_background: "学术背景",
  prerequisite_courses: "先修课程",
}

export const applicationStatusLabels: Record<ApplicationStatus, string> = {
  shortlisted: "已加入计划",
  preparing: "材料准备中",
  ready_to_submit: "待提交",
  submitted: "已提交",
  result_pending: "等待结果",
  offered: "已录取",
  rejected: "未录取",
  withdrawn: "已撤回",
}

export const taskStatusLabels: Record<TaskStatus, string> = {
  todo: "待办",
  in_progress: "进行中",
  blocked: "受阻",
  done: "已完成",
}

export const evidenceStatusLabels: Record<EvidenceStatus, string> = {
  unverified: "待验证",
  verified: "已验证",
  conflicted: "存在冲突",
  superseded: "已被更新",
  rejected: "已驳回",
}

type ValueSource = Pick<
  RequirementPublic | EvidencePublic,
  | "numeric_value"
  | "date_value"
  | "money_amount"
  | "money_currency"
  | "text_value"
  | "text_list_value"
>

export function formatRequirementValue(value: ValueSource) {
  if (value.money_amount) {
    return `${Number(value.money_amount).toLocaleString("zh-CN")} ${value.money_currency ?? ""}`.trim()
  }
  if (value.date_value) return value.date_value
  // 数据库里是定点小数，直接展示会得到 6.500 / 79.000 这种冗余写法。
  if (value.numeric_value) return String(Number(value.numeric_value))
  if (value.text_list_value?.length) return value.text_list_value.join("、")
  return value.text_value || "暂未公布"
}

/** 招生要求常写成一长段并列条件，按分句拆行后并排对比才读得下去。 */
export function formatComparisonValue(value: ValueSource) {
  if (value.text_list_value?.length) return value.text_list_value.join("\n\n")

  const formatted = formatRequirementValue(value)
  if (value.text_value === null || value.text_value === undefined) {
    return formatted
  }
  return formatted
    .split(/(?<=[.;])\s+(?=[A-Z(（]|\(\d\)|or\b)/)
    .map((part) => part.trim())
    .filter(Boolean)
    .join("\n")
}

export function programTitle(program: ProgramWithUniversityPublic) {
  return `${program.university.short_name} · ${program.name}`
}

export type MatchAssessment = {
  group: "reach" | "target" | "safer" | "incomplete"
  reasons: string[]
  gaps: string[]
}

export const matchGroupLabels: Record<MatchAssessment["group"], string> = {
  reach: "冲刺",
  target: "匹配",
  safer: "稳妥",
  incomplete: "待完善档案",
}

export function assessProgram(
  profile: UserProfilePublic | null | undefined,
  requirements: RequirementPublic[],
): MatchAssessment {
  if (!profile)
    return { group: "incomplete", reasons: [], gaps: ["请先建立个人档案"] }
  const reasons: string[] = []
  const gaps: string[] = []
  let strongMargins = 0
  let evaluated = 0
  const requirement = (field: RequirementFieldName) =>
    requirements.find(
      (item) => item.field_name === field && item.status === "published",
    )

  const ielts = requirement("ielts_overall")
  if (ielts?.numeric_value) {
    if (!profile.ielts_overall)
      gaps.push(`缺少雅思成绩，项目要求 ${ielts.numeric_value}`)
    else {
      evaluated += 1
      const margin = Number(profile.ielts_overall) - Number(ielts.numeric_value)
      if (margin < 0) gaps.push(`雅思还差 ${Math.abs(margin).toFixed(1)} 分`)
      else {
        reasons.push(
          `雅思达到要求（${profile.ielts_overall} / ${ielts.numeric_value}）`,
        )
        if (margin >= 0.5) strongMargins += 1
      }
    }
  }

  const gpaMin = requirement("gpa_min")
  const gpaScale = requirement("gpa_scale")
  if (gpaMin?.numeric_value) {
    if (!profile.gpa_value || !profile.gpa_scale) gaps.push("缺少完整 GPA 信息")
    else {
      evaluated += 1
      const requiredScale = Number(gpaScale?.numeric_value || profile.gpa_scale)
      const normalized =
        (Number(profile.gpa_value) / Number(profile.gpa_scale)) * requiredScale
      const margin = normalized - Number(gpaMin.numeric_value)
      if (margin < 0) gaps.push(`换算 GPA 还差 ${Math.abs(margin).toFixed(2)}`)
      else {
        reasons.push("GPA 达到公开最低要求")
        if (margin >= requiredScale * 0.05) strongMargins += 1
      }
    }
  }

  const work = requirement("work_experience_years")
  if (work?.numeric_value) {
    if (profile.work_experience_years == null)
      gaps.push(`缺少工作经历年限，项目要求 ${work.numeric_value} 年`)
    else {
      evaluated += 1
      const margin =
        Number(profile.work_experience_years) - Number(work.numeric_value)
      if (margin < 0)
        gaps.push(`工作经历还差 ${Math.abs(margin).toFixed(1)} 年`)
      else {
        reasons.push("工作经历达到要求")
        if (margin >= 1) strongMargins += 1
      }
    }
  }

  const tuition = requirement("tuition")
  if (tuition?.money_amount && profile.budget_cny) {
    if (tuition.money_currency === "CNY") {
      evaluated += 1
      if (profile.budget_cny < Number(tuition.money_amount))
        gaps.push(
          `预算还差 ${(Number(tuition.money_amount) - profile.budget_cny).toLocaleString("zh-CN")} 元`,
        )
      else reasons.push("预算覆盖已公布学费")
    } else
      reasons.push(
        `学费以 ${tuition.money_currency} 发布，未使用无来源汇率换算`,
      )
  }

  if (evaluated === 0)
    return {
      group: "incomplete",
      reasons,
      gaps: gaps.length ? gaps : ["当前缺少可用于匹配的公开要求"],
    }
  if (gaps.length > 0) return { group: "reach", reasons, gaps }
  return { group: strongMargins >= 2 ? "safer" : "target", reasons, gaps }
}
