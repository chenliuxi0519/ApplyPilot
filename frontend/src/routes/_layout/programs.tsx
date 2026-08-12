import { createFileRoute } from "@tanstack/react-router"
import { ProgramsPage } from "@/features/programs/ProgramsPage"

export const Route = createFileRoute("/_layout/programs")({
  component: ProgramsPage,
  head: () => ({ meta: [{ title: "项目对比 - ApplyPilot" }] }),
})
