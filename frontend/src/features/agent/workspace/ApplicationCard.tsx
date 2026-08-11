import { Check, Circle } from "lucide-react"

import type {
  ApplicationDetailPublic,
  ApplicationPublic,
  TaskPublic,
} from "@/client"
import { Badge } from "@/components/ui/badge"

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

const TASK_LABELS: Record<string, string> = {
  cv: "个人简历",
  personal_statement: "个人陈述",
  transcript: "成绩单",
  language_score: "语言成绩",
  recommendation: "推荐信",
  application_form: "申请表",
  other: "其他",
}

interface ApplicationCardProps {
  application: ApplicationPublic
  detail: ApplicationDetailPublic | null
  programLabel: string | null
}

export function ApplicationCard({
  application,
  detail,
  programLabel,
}: ApplicationCardProps) {
  const readiness = detail?.readiness
  const tasks = detail?.tasks ?? []

  return (
    <div className="space-y-2 rounded-lg border bg-card p-3">
      <div>
        <p className="text-sm font-medium leading-snug">
          {programLabel ?? "申请项目"}
        </p>
        <p className="text-xs text-muted-foreground">
          {application.application_cycle}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Badge
          variant="secondary"
          className="font-normal"
          data-testid={`application-status-${application.id}`}
        >
          {STATUS_LABELS[application.status] ?? application.status}
        </Badge>
        {readiness ? (
          <span
            className={
              readiness.is_ready
                ? "text-xs font-medium text-emerald-600 dark:text-emerald-500"
                : "text-xs text-muted-foreground"
            }
          >
            必需材料 {readiness.required_done}/{readiness.required_total}
            {readiness.is_ready ? " · 已就绪" : ""}
          </span>
        ) : null}
      </div>

      {tasks.length > 0 ? (
        <ul className="space-y-1 border-t pt-2">
          {tasks.map((task) => (
            <TaskRow key={task.id} task={task} />
          ))}
        </ul>
      ) : null}
    </div>
  )
}

function TaskRow({ task }: { task: TaskPublic }) {
  const done = task.status === "done"
  return (
    <li className="flex items-center gap-1.5 text-xs">
      {done ? (
        <Check className="size-3 shrink-0 text-emerald-600 dark:text-emerald-500" />
      ) : (
        <Circle className="size-3 shrink-0 text-muted-foreground" />
      )}
      <span className={done ? "text-muted-foreground line-through" : ""}>
        {TASK_LABELS[task.task_type] ?? task.title}
      </span>
      {task.is_required ? null : (
        <span className="text-muted-foreground">（选填）</span>
      )}
    </li>
  )
}
