import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback, useEffect, useState } from "react"

import { type AgentChatPublic, AgentRunsService, AgentService } from "@/client"
import { type ChatMessage, runsToMessages, toAssistantMessage } from "./types"

const WORKSPACE_QUERIES = [
  ["profile"],
  ["applications"],
  ["agent-runs"],
] as const

let counter = 0

function nextId() {
  counter += 1
  return `m-${counter}`
}

export function useAgentChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [conversationId, setConversationId] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const history = useQuery({
    queryKey: ["agent-runs"],
    queryFn: () => AgentRunsService.listRuns({ limit: 200 }),
  })

  const openConversation = useCallback(
    (id: string) => {
      const runs = (history.data?.data ?? []).filter(
        (run) => run.conversation_id === id,
      )
      setConversationId(id)
      setMessages(runsToMessages(runs))
    },
    [history.data],
  )

  useEffect(() => {
    if (conversationId !== null || messages.length > 0) return
    const latest = history.data?.data.find((run) => run.conversation_id)
    if (latest?.conversation_id) openConversation(latest.conversation_id)
  }, [conversationId, history.data, messages.length, openConversation])

  const refreshWorkspace = useCallback(() => {
    for (const key of WORKSPACE_QUERIES) {
      queryClient.invalidateQueries({ queryKey: [...key] })
    }
  }, [queryClient])

  const accept = useCallback(
    (response: AgentChatPublic) => {
      setConversationId(response.conversation_id)
      setMessages((current) => [
        ...current,
        toAssistantMessage(response, nextId()),
      ])
      refreshWorkspace()
    },
    [refreshWorkspace],
  )

  const fail = useCallback((error: unknown) => {
    const text =
      error instanceof Error ? error.message : "出现了问题，请稍后重试。"
    setMessages((current) => [
      ...current,
      { id: nextId(), role: "error", text },
    ])
  }, [])

  const send = useMutation({
    mutationFn: (message: string) =>
      AgentService.chat({
        requestBody: { message, conversation_id: conversationId },
      }),
    onSuccess: accept,
    onError: fail,
  })

  const decide = useMutation({
    mutationFn: ({ runId, approved }: { runId: string; approved: boolean }) =>
      approved
        ? AgentService.approve({ runId })
        : AgentService.reject({ runId }),
    onSuccess: (response, variables) => {
      setMessages((current) =>
        current.map((message) =>
          message.role === "assistant" && message.runId === variables.runId
            ? { ...message, confirmation: null }
            : message,
        ),
      )
      accept(response)
    },
    onError: fail,
  })

  const ask = useCallback(
    (text: string) => {
      const message = text.trim()
      if (!message || send.isPending || decide.isPending) return
      setMessages((current) => [
        ...current,
        { id: nextId(), role: "user", text: message },
      ])
      send.mutate(message)
    },
    [send, decide.isPending],
  )

  const answer = useCallback(
    (runId: string, approved: boolean) => {
      if (decide.isPending) return
      decide.mutate({ runId, approved })
    },
    [decide],
  )

  return {
    messages,
    ask,
    answer,
    isBusy: send.isPending || decide.isPending,
    isDeciding: decide.isPending,
    runs: history.data?.data ?? [],
    historyLoading: history.isLoading,
    conversationId,
    openConversation,
  }
}
