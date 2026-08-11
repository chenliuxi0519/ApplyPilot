import { CheckCircle2, CircleDashed, PauseCircle, XCircle } from "lucide-react"

import type { AgentRunPublic } from "@/client"
import { Skeleton } from "@/components/ui/skeleton"

interface ActivitySidebarProps {
  runs: AgentRunPublic[]
  loading: boolean
  activeConversationId: string | null
  onOpen: (conversationId: string) => void
}

export function ActivitySidebar({
  runs,
  loading,
  activeConversationId,
  onOpen,
}: ActivitySidebarProps) {
  const conversations = runs
    .filter(
      (run, index, all) =>
        run.conversation_id &&
        all.findIndex(
          (candidate) => candidate.conversation_id === run.conversation_id,
        ) === index,
    )
    .slice(0, 12)

  return (
    <div className="flex h-full w-full flex-col overflow-y-auto border-r bg-[var(--bg)]">
      <div className="border-b px-4 py-3">
        <h2 className="text-[10px] font-semibold uppercase tracking-[.08em] text-[var(--text-muted)]">最近对话</h2>
        <p className="text-xs text-muted-foreground">点击可查看完整记录</p>
      </div>

      <div className="space-y-1 p-2">
        {loading ? (
          <Skeleton className="h-16 w-full" />
        ) : conversations.length === 0 ? (
          <p className="p-2 text-xs text-muted-foreground">
            还没有对话，先问一个问题吧。
          </p>
        ) : (
          conversations.map((run) => (
            <RunRow
              key={run.id}
              run={run}
              active={run.conversation_id === activeConversationId}
              onOpen={onOpen}
            />
          ))
        )}
      </div>
    </div>
  )
}

const STATUS_META: Record<
  string,
  { label: string; icon: typeof CheckCircle2; className: string }
> = {
  completed: {
    label: "已完成",
    icon: CheckCircle2,
    className: "text-emerald-600 dark:text-emerald-500",
  },
  waiting_confirmation: {
    label: "等待确认",
    icon: PauseCircle,
    className: "text-amber-600 dark:text-amber-500",
  },
  failed: { label: "失败", icon: XCircle, className: "text-destructive" },
  budget_exceeded: {
    label: "已达执行上限",
    icon: CircleDashed,
    className: "text-muted-foreground",
  },
  running: {
    label: "处理中",
    icon: CircleDashed,
    className: "text-muted-foreground",
  },
}

function RunRow({
  run,
  active,
  onOpen,
}: {
  run: AgentRunPublic
  active: boolean
  onOpen: (conversationId: string) => void
}) {
  const meta = STATUS_META[run.status] ?? STATUS_META.running
  const Icon = meta.icon

  return (
    <button
      type="button"
      disabled={!run.conversation_id}
      onClick={() => run.conversation_id && onOpen(run.conversation_id)}
      className={`mb-[3px] w-full rounded-[7px] border px-2.5 py-[9px] text-left text-xs hover:bg-[var(--surface-raised)] disabled:cursor-default ${active ? "border-[var(--border)] bg-[var(--surface-raised)]" : "border-transparent"}`}
    >
      <div className="flex items-center gap-1.5">
        <Icon className={`size-3.5 shrink-0 ${meta.className}`} />
        <span className="font-medium">{meta.label}</span>
      </div>
      <p className="mt-1 truncate text-muted-foreground">
        {run.user_message ??
          run.final_answer ??
          `调用了 ${run.tool_call_count} 个工具`}
      </p>
      <p className="mt-0.5 font-mono text-[10px] text-[var(--text-muted)]">
        {new Date(run.started_at).toLocaleString("zh-CN")}
      </p>
    </button>
  )
}
