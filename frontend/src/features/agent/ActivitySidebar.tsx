import {
  CheckCircle2,
  CircleDashed,
  PauseCircle,
  Trash2,
  XCircle,
} from "lucide-react"
import type { MouseEvent } from "react"

import type { AgentRunPublic } from "@/client"
import { Skeleton } from "@/components/ui/skeleton"

interface ActivitySidebarProps {
  runs: AgentRunPublic[]
  loading: boolean
  activeConversationId: string | null
  onOpen: (conversationId: string) => void
  onDelete: (conversationId: string) => void
}

export function ActivitySidebar({
  runs,
  loading,
  activeConversationId,
  onOpen,
  onDelete,
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
        <h2 className="text-[10px] font-semibold uppercase tracking-[.08em] text-[var(--text-muted)]">
          最近对话
        </h2>
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
              onDelete={onDelete}
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
  onDelete,
}: {
  run: AgentRunPublic
  active: boolean
  onOpen: (conversationId: string) => void
  onDelete: (conversationId: string) => void
}) {
  const meta = STATUS_META[run.status] ?? STATUS_META.running
  const Icon = meta.icon

  const handleDelete = (event: MouseEvent) => {
    event.stopPropagation()
    if (!run.conversation_id) return
    if (window.confirm("删除这段对话？删除后无法恢复。")) {
      onDelete(run.conversation_id)
    }
  }

  return (
    <div
      className={`group relative mb-[3px] rounded-[7px] border ${active ? "border-[var(--border)] bg-[var(--surface-raised)]" : "border-transparent"}`}
    >
      <button
        type="button"
        disabled={!run.conversation_id}
        onClick={() => run.conversation_id && onOpen(run.conversation_id)}
        className="w-full rounded-[7px] py-[9px] pr-8 pl-2.5 text-left text-xs hover:bg-[var(--surface-raised)] disabled:cursor-default"
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
      {run.conversation_id ? (
        <button
          type="button"
          onClick={handleDelete}
          aria-label="删除对话"
          className="absolute top-2 right-1.5 rounded p-1 text-[var(--text-muted)] opacity-0 hover:bg-[var(--surface)] hover:text-destructive focus-visible:opacity-100 group-hover:opacity-100"
        >
          <Trash2 className="size-3.5" />
        </button>
      ) : null}
    </div>
  )
}
