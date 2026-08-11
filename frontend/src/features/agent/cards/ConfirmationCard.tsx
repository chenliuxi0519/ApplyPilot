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

const label = (status: string | null | undefined) =>
  status ? (STATUS_LABELS[status] ?? status) : "—"

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
  const { summary } = confirmation

  return (
    <div
      data-testid="confirmation-card"
      className="rounded-lg border border-amber-300 bg-amber-50/60 p-4 dark:border-amber-900/60 dark:bg-amber-950/20"
    >
      <div className="flex items-center gap-2">
        <ShieldAlert className="size-4 text-amber-600 dark:text-amber-500" />
        <p className="text-sm font-medium">此操作需要你的确认</p>
      </div>

      <div className="mt-3 space-y-1">
        {summary.program_label ? (
          <p className="font-medium leading-snug">{summary.program_label}</p>
        ) : null}
        {summary.application_cycle ? (
          <p className="text-sm text-muted-foreground">
            {summary.application_cycle}
          </p>
        ) : null}
      </div>

      {summary.target_status ? (
        <div className="mt-3 flex items-center gap-2 text-sm">
          <span className="rounded-md border bg-background px-2 py-1">
            {label(summary.current_status)}
          </span>
          <ArrowRight className="size-4 text-muted-foreground" />
          <span className="rounded-md border bg-background px-2 py-1 font-medium">
            {label(summary.target_status)}
          </span>
        </div>
      ) : null}

      <p className="mt-3 text-xs text-muted-foreground">
        当前尚未保存任何更改。请确认是否继续此操作。
      </p>

      <div className="mt-3 flex gap-2">
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          data-testid="confirmation-cancel"
          onClick={() => onDecide(runId, false)}
        >
          取消
        </Button>
        <Button
          size="sm"
          disabled={busy}
          data-testid="confirmation-confirm"
          onClick={() => onDecide(runId, true)}
        >
          确认
        </Button>
      </div>
    </div>
  )
}
