import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback, useEffect, useRef, useState } from "react"

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

  // 用户主动点过"新建对话"或者打开过某条历史对话之后，就不再自动跳回
  // 最近一条——那会把用户刚清空的会话又拉回去，等于按钮白点了。
  const skipAutoOpenRef = useRef(false)

  const openConversation = useCallback(
    (id: string) => {
      skipAutoOpenRef.current = true
      const runs = (history.data?.data ?? []).filter(
        (run) => run.conversation_id === id,
      )
      setConversationId(id)
      setMessages(runsToMessages(runs))
    },
    [history.data],
  )

  const startNewConversation = useCallback(() => {
    skipAutoOpenRef.current = true
    setConversationId(null)
    setMessages([])
  }, [])

  useEffect(() => {
    if (skipAutoOpenRef.current) return
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
            ? {
                ...message,
                confirmation: null,
                decision: variables.approved ? "approved" : "rejected",
              }
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

  const remove = useMutation({
    mutationFn: (id: string) =>
      AgentRunsService.deleteConversation({ conversationId: id }),
    onSuccess: (_response, deletedId) => {
      // 删的正好是当前打开的这条，得清空面板，不然还显示着一段
      // 已经被删掉的对话。
      if (deletedId === conversationId) startNewConversation()
      queryClient.invalidateQueries({ queryKey: ["agent-runs"] })
    },
    onError: fail,
  })

  const deleteConversation = useCallback(
    (id: string) => {
      if (remove.isPending) return
      remove.mutate(id)
    },
    [remove],
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
    startNewConversation,
    deleteConversation,
    isDeletingConversation: remove.isPending,
  }
}
