import { createFileRoute } from "@tanstack/react-router"
import { ApplicationsPage } from "@/features/applications/ApplicationsPage"

export const Route = createFileRoute("/_layout/applications")({
  component: ApplicationsPage,
  head: () => ({ meta: [{ title: "申请看板 - ApplyPilot" }] }),
})
