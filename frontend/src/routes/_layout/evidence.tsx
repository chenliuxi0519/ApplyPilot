import { createFileRoute } from "@tanstack/react-router"
import { EvidencePage } from "@/features/programs/EvidencePage"

export const Route = createFileRoute("/_layout/evidence")({
  component: EvidencePage,
  head: () => ({ meta: [{ title: "证据库 - ApplyPilot" }] }),
})
