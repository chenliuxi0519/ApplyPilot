import { ArrowRight, ShieldAlert } from "lucide-react"

import type { ConfirmationPublic } from "@/client"
import { Button } from "@/components/ui/button"

const STATUS_LABELS: Record<string, string> = {
  shortlisted: "已加入选校",
  preparing: "材料准备中",
  ready_to_submit: "可提交",
  submitted: "已提交",
  result_pending: "等待结果",
  offered: "已录取",
  rejected: "未录取",
  withdrawn: "已撤回",
}

const FIELD_LABELS: Record<string, string> = {
  undergraduate_university: "本科院校",
  undergraduate_major: "本科专业",
  gpa_value: "GPA",
  gpa_scale: "GPA 满分",
  ielts_overall: "雅思总分",
  work_experience_years: "工作年限",
  experience_summary: "经历摘要",
  budget_cny: "预算（人民币）",
  target_regions: "目标地区",
  target_fields: "目标方向",
  career_goal: "职业目标",
}

const ACTIONS: Record<string, { title: string; effect: string }> = {
  update_user_profile: {
    title: "更新个人档案",
    effect: "确认后，以下信息将保存到你的个人档案，并作为后续选校匹配的依据。",
  },
  update_application_status: {
    title: "变更申请状态",
    effect: "确认后，该申请的状态将被更新。",
  },
}

const statusLabel = (status: string | null | undefined) =>
  status ? (STATUS_LABELS[status] ?? status) : "—"

const fieldLabel = (field: string) => FIELD_LABELS[field] ?? field

interface ConfirmationCardProps {
  confirmation: ConfirmationPublic
  runId: string
  onDecide: (runId: string, approved: boolean) => void
  busy: boolean
}

export function ConfirmationCard({
  confirmation,
  runId,
  onDecide,
  busy,
}: ConfirmationCardProps) {
  const { summary, tool_name, reason } = confirmation
  const action = ACTIONS[tool_name]
  const changes = summary.changes ?? []

  return (
    <div
      data-testid="confirmation-card"
      className="rounded-lg border border-amber-300 bg-amber-50/60 p-4 dark:border-amber-900/60 dark:bg-amber-950/20"
    >
      <div className="flex items-center gap-2">
        <ShieldAlert className="size-4 text-amber-600 dark:text-amber-500" />
        <p className="text-sm font-medium">
          请核对以下信息
          {action ? `，确认后将${action.title}` : "，确认后才会执行"}
        </p>
      </div>

      {summary.program_label ? (
        <div className="mt-3 space-y-1">
          <p className="font-medium leading-snug">{summary.program_label}</p>
          {summary.application_cycle ? (
            <p className="text-sm text-muted-foreground">
              {summary.application_cycle}
            </p>
          ) : null}
        </div>
      ) : null}

      {summary.target_status ? (
        <div className="mt-3 flex items-center gap-2 text-sm">
          <span className="rounded-md border bg-background px-2 py-1">
            {statusLabel(summary.current_status)}
          </span>
          <ArrowRight className="size-4 text-muted-foreground" />
          <span className="rounded-md border bg-background px-2 py-1 font-medium">
            {statusLabel(summary.target_status)}
          </span>
        </div>
      ) : null}

      {changes.length > 0 ? (
        <ul className="mt-3 divide-y rounded-md border bg-background text-sm">
          {changes.map((change) => (
            <li
              key={change.field}
              className="flex items-center justify-between gap-3 px-3 py-2"
            >
              <span className="text-muted-foreground">
                {fieldLabel(change.field)}
              </span>
              <span className="flex items-center gap-2 text-right">
                {change.current && change.current !== change.next ? (
                  <>
                    <span className="text-muted-foreground line-through">
                      {change.current}
                    </span>
                    <ArrowRight className="size-3 shrink-0 text-muted-foreground" />
                  </>
                ) : null}
                <span className="font-medium">{change.next}</span>
              </span>
            </li>
          ))}
        </ul>
      ) : null}

      <p className="mt-3 text-xs text-muted-foreground">
        {action?.effect ?? reason}
        {" 如有错误，请点击取消后重新告诉我正确的信息。"}
      </p>

      <div className="mt-3 flex gap-2">
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          data-testid="confirmation-cancel"
          onClick={() => onDecide(runId, false)}
        >
          信息有误，取消
        </Button>
        <Button
          size="sm"
          disabled={busy}
          data-testid="confirmation-confirm"
          onClick={() => onDecide(runId, true)}
        >
          信息无误，确认保存
        </Button>
      </div>
    </div>
  )
}
