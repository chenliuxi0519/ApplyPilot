import { ArrowUp } from "lucide-react"
import { type KeyboardEvent, useEffect, useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"

interface ComposerProps {
  onSend: (text: string) => void
  busy: boolean
  disabled?: boolean
  placeholder?: string
  draft?: { text: string; key: number }
}

export function Composer({
  onSend,
  busy,
  disabled,
  placeholder,
  draft,
}: ComposerProps) {
  const [value, setValue] = useState("")
  const ref = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (!draft) return
    setValue(draft.text)
    ref.current?.focus()
  }, [draft])

  const submit = () => {
    const text = value.trim()
    if (!text || busy || disabled) return
    setValue("")
    onSend(text)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <div className="border-t bg-background px-4 py-3">
      <div className="mx-auto flex w-full max-w-3xl items-end gap-2 rounded-[11px] border bg-[var(--surface)] p-2 shadow-sm focus-within:border-primary focus-within:ring-2 focus-within:ring-[var(--primary-muted)]">
        <Textarea
          ref={ref}
          rows={1}
          value={value}
          disabled={disabled}
          data-testid="composer-input"
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder={placeholder ?? "向 ApplyPilot 提问…"}
          className="max-h-40 min-h-9 resize-none border-0 bg-transparent px-2 py-1.5 shadow-none focus-visible:ring-0"
        />
        <Button
          size="icon"
          className="size-[34px] shrink-0 rounded-[7px]"
          disabled={busy || disabled || value.trim().length === 0}
          data-testid="composer-send"
          onClick={submit}
          aria-label="发送"
        >
          <ArrowUp className="size-4" />
        </Button>
      </div>
      <p className="mx-auto mt-2 max-w-3xl text-center text-[11px] text-[var(--text-disabled)]">
        涉及重要信息变更时，ApplyPilot 会先征求你的确认。
      </p>
    </div>
  )
}
