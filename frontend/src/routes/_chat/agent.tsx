import { createFileRoute } from "@tanstack/react-router"

import { AgentPage } from "@/features/agent/AgentPage"

export const Route = createFileRoute("/_chat/agent")({
  component: AgentPage,
  head: () => ({
    meta: [{ title: "ApplyPilot" }],
  }),
})
