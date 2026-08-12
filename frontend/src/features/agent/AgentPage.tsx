import { useQuery } from "@tanstack/react-query"
import { PanelRight } from "lucide-react"
import { useState } from "react"

import { AgentService } from "@/client"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { ActivitySidebar } from "./ActivitySidebar"
import { Composer } from "./chat/Composer"
import { Thread } from "./chat/Thread"
import { useAgentChat } from "./useAgentChat"
import { Workspace } from "./workspace/Workspace"

export function AgentPage() {
  const {
    messages,
    ask,
    answer,
    isBusy,
    isDeciding,
    runs,
    historyLoading,
    conversationId,
    openConversation,
  } = useAgentChat()
  const [draft, setDraft] = useState<{ text: string; key: number }>()
  const [workspaceOpen, setWorkspaceOpen] = useState(false)

  const config = useQuery({
    queryKey: ["agent-config"],
    queryFn: () => AgentService.agentConfig(),
    staleTime: Number.POSITIVE_INFINITY,
  })
  const unconfigured = config.data?.configured === false

  const suggest = (text: string) => setDraft({ text, key: Date.now() })

  return (
    <div className="grid h-full min-h-0 grid-cols-1 overflow-hidden lg:grid-cols-[210px_minmax(0,1fr)] xl:grid-cols-[210px_minmax(0,1fr)_230px]">
      <div className="hidden min-h-0 lg:block">
        <ActivitySidebar
          runs={runs}
          loading={historyLoading}
          activeConversationId={conversationId}
          onOpen={openConversation}
        />
      </div>

      <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
        <header className="flex h-12 shrink-0 items-center justify-between gap-2 border-b bg-[var(--surface)]/80 px-4 backdrop-blur-xl">
          <div className="flex items-center gap-2">
            <SidebarTrigger className="-ml-1 text-muted-foreground" />
            <span className="size-[7px] animate-pulse rounded-full bg-[var(--success)] shadow-[0_0_10px_var(--success)]" />
            <span className="text-sm font-medium">ApplyPilot 智能助手</span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="xl:hidden"
            onClick={() => setWorkspaceOpen((open) => !open)}
          >
            <PanelRight className="size-4" />
            工作区
          </Button>
        </header>

        {unconfigured ? (
          <div className="px-4 pt-4">
            <Alert>
              <AlertDescription>
                当前服务器尚未配置智能助手，请配置 AGENT_BASE_URL、
                AGENT_API_KEY 和 AGENT_MODEL 后再开始对话。
              </AlertDescription>
            </Alert>
          </div>
        ) : null}

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
          <Thread
            messages={messages}
            busy={isBusy}
            deciding={isDeciding}
            onDecide={answer}
            onSuggest={suggest}
          />
        </div>

        <Composer
          onSend={ask}
          busy={isBusy}
          disabled={unconfigured}
          draft={draft}
        />
      </div>

      <div className="hidden min-h-0 xl:block">
        <Workspace />
      </div>

      {workspaceOpen ? (
        <div className="fixed inset-y-0 right-0 z-20 w-80 bg-background shadow-xl xl:hidden">
          <div className="flex h-full flex-col">
            <div className="flex items-center justify-end border-b px-2 py-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setWorkspaceOpen(false)}
              >
                关闭
              </Button>
            </div>
            <div className="min-h-0 flex-1">
              <Workspace />
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
