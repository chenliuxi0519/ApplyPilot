import { AlertTriangle, ExternalLink, FileCheck } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import type { RequirementSummary } from "../types"

function formatHost(url: string): string {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

function formatCaptured(iso: string | null): string | null {
  if (!iso) return null
  try {
    return new Date(iso).toLocaleDateString("zh-CN")
  } catch {
    return null
  }
}

const FIELD_LABELS: Record<string, string> = {
  ielts_overall: "雅思总分",
  ielts_min_band: "雅思单项最低分",
  toefl_overall: "托福总分",
  gpa_min: "最低 GPA",
  gpa_scale: "GPA 满分制",
  work_experience_years: "工作经验",
  application_deadline: "申请截止日期",
  tuition: "学费",
  degree_background: "学术背景",
  prerequisite_courses: "先修课程",
}

interface RequirementCardProps {
  requirements: RequirementSummary[]
}

export function RequirementCard({ requirements }: RequirementCardProps) {
  const cycle = requirements[0]?.application_cycle

  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="flex items-center gap-2">
        <FileCheck className="size-4 text-muted-foreground" />
        <p className="text-sm font-medium">申请要求</p>
        {cycle ? (
          <Badge variant="secondary" className="font-normal">
            {cycle}
          </Badge>
        ) : null}
      </div>

      <ul className="mt-3 space-y-2">
        {requirements.map((requirement) => {
          const captured = formatCaptured(requirement.captured_at)
          return (
            <li
              key={`${requirement.field_name}-${requirement.application_cycle}`}
              className="text-sm"
            >
              <div className="flex items-start justify-between gap-4">
                <span className="shrink-0 text-muted-foreground">
                  {FIELD_LABELS[requirement.field_name] ??
                    requirement.field_name}
                </span>
                <span className="text-right font-medium">
                  {requirement.value}
                  {requirement.status === "conflict_pending" ? (
                    <span className="ml-2 inline-flex items-center gap-1 align-middle text-xs font-normal text-amber-600 dark:text-amber-500">
                      <AlertTriangle className="size-3" />
                      待核实
                    </span>
                  ) : null}
                </span>
              </div>
              {requirement.source_url ? (
                <div className="mt-0.5 flex flex-wrap items-center justify-end gap-2 text-[11px] text-muted-foreground">
                  <a
                    href={requirement.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 hover:text-foreground"
                    data-testid="requirement-source"
                  >
                    <ExternalLink className="size-3" />
                    {formatHost(requirement.source_url)}
                  </a>
                  {captured ? <span>· 抓取于 {captured}</span> : null}
                </div>
              ) : null}
            </li>
          )
        })}
      </ul>

      <p className="mt-3 border-t pt-2 text-xs text-muted-foreground">
        信息发布自学校官方来源。标记为
        <span className="font-medium">"待核实"</span>
        的数据存在来源冲突，正在审核中。
      </p>
    </div>
  )
}
