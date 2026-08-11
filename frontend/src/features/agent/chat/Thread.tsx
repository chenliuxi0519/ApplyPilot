import { AlertCircle, Check, Sparkles, X } from "lucide-react"
import { useEffect, useRef } from "react"

import { ComparisonCard } from "../cards/ComparisonCard"
import { ConfirmationCard } from "../cards/ConfirmationCard"
import { ProgramCard } from "../cards/ProgramCard"
import { RequirementCard } from "../cards/RequirementCard"
import type { ChatMessage, ProgramSummary } from "../types"

interface ThreadProps {
  messages: ChatMessage[]
  busy: boolean
  deciding: boolean
  onDecide: (runId: string, approved: boolean) => void
  onSuggest: (text: string) => void
}

const SUGGESTIONS = [
  "帮我找新加坡的人工智能硕士项目",
  "香港科技大学人工智能硕士有哪些申请要求？",
  "查看我目前的个人档案",
]

export function Thread({
  messages,
  busy,
  deciding,
  onDecide,
  onSuggest,
}: ThreadProps) {
  const endRef = useRef<HTMLDivElement>(null)
  const lastId = messages[messages.length - 1]?.id ?? null

  useEffect(() => {
    if (lastId === null && !busy) return
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" })
  }, [lastId, busy])

  if (messages.length === 0) {
    return <EmptyState onSuggest={onSuggest} />
  }

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-6">
      {messages.map((message) => (
        <Message
          key={message.id}
          message={message}
          deciding={deciding}
          onDecide={onDecide}
          onSuggest={onSuggest}
        />
      ))}
      {busy ? <Thinking /> : null}
      <div ref={endRef} />
    </div>
  )
}

function Message({
  message,
  deciding,
  onDecide,
  onSuggest,
}: {
  message: ChatMessage
  deciding: boolean
  onDecide: (runId: string, approved: boolean) => void
  onSuggest: (text: string) => void
}) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[380px] rounded-[12px_12px_2px_12px] bg-primary px-4 py-2.5 text-primary-foreground">
          <p className="whitespace-pre-wrap text-sm">{message.text}</p>
        </div>
      </div>
    )
  }

  if (message.role === "error") {
    return (
      <div className="flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm">
        <AlertCircle className="mt-0.5 size-4 shrink-0 text-destructive" />
        <p>{message.text}</p>
      </div>
    )
  }

  const askRequirements = (program: ProgramSummary) =>
    onSuggest(`${program.university} ${program.name} 有哪些申请要求？`)
  const addToPlan = (program: ProgramSummary) =>
    onSuggest(
      `把 ${program.university} ${program.name} 加入我的 2026/27 申请计划。`,
    )

  return (
    <div className="space-y-3 rounded-[2px_12px_12px_12px] border border-l-[3px] border-l-primary bg-[var(--surface)] p-4 shadow-sm">
      {message.trace.length > 0 ? (
        <ul className="flex flex-wrap gap-[7px]">
          {message.trace.map((entry, index) => (
            <li
              key={`${entry.label}-${index}`}
              className="flex items-center gap-1.5 rounded-md border bg-[var(--surface)] px-2 py-1 font-mono text-[10px] text-[var(--text-muted)]"
            >
              {entry.status === "ok" ? (
                <Check className="size-3" />
              ) : (
                <X className="size-3" />
              )}
              {entry.label}
            </li>
          ))}
        </ul>
      ) : null}

      {message.text ? (
        <p className="whitespace-pre-wrap text-sm leading-relaxed">
          {message.text}
        </p>
      ) : null}

      {message.cards.map((card, index) => {
        if (card.kind === "programs") {
          return (
            <div key={`programs-${index}`} className="space-y-2">
              <p className="text-xs text-muted-foreground">
                找到 {card.count} 个项目
              </p>
              {card.programs.map((program) => (
                <ProgramCard
                  key={program.program_id}
                  program={program}
                  disabled={deciding}
                  onViewRequirements={askRequirements}
                  onAddToPlan={addToPlan}
                />
              ))}
            </div>
          )
        }
        if (card.kind === "requirements") {
          return (
            <RequirementCard
              key={`requirements-${index}`}
              requirements={card.requirements}
            />
          )
        }
        return <ComparisonCard key={`comparison-${index}`} card={card} />
      })}

      {message.confirmation ? (
        <ConfirmationCard
          confirmation={message.confirmation}
          runId={message.runId}
          onDecide={onDecide}
          busy={deciding}
        />
      ) : null}

      {message.status === "budget_exceeded" ? (
        <p className="text-xs text-muted-foreground">
          本次任务已达到最大执行步数，智能助手已停止。
        </p>
      ) : null}
      {message.status === "failed" ? (
        <p className="text-xs text-destructive">
          本次执行失败{message.error ? `（${message.error}）` : ""}。
        </p>
      ) : null}
    </div>
  )
}

function Thinking() {
  return (
    <div
      data-testid="thinking"
      className="flex items-center gap-2 text-sm text-muted-foreground"
    >
      <Sparkles className="size-4 animate-pulse" />
      正在处理…
    </div>
  )
}

function EmptyState({ onSuggest }: { onSuggest: (text: string) => void }) {
  return (
    <div className="mx-auto flex h-full w-full max-w-3xl flex-col items-center justify-center gap-6 px-4 text-center">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">
          规划你的留学申请
        </h1>
        <p className="max-w-md text-sm text-muted-foreground">
          你可以咨询项目和申请要求、建立选校清单，并在一个地方跟踪所有申请。
          申请要求均来自学校官方来源。
        </p>
      </div>
      <div className="flex flex-wrap justify-center gap-2">
        {SUGGESTIONS.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            onClick={() => onSuggest(suggestion)}
            className="rounded-full border bg-card px-3.5 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
          >
            {suggestion}
          </button>
        ))}
      </div>
    </div>
  )
}
