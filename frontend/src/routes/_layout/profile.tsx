import { createFileRoute } from "@tanstack/react-router"
import { ProfilePage } from "@/features/profile/ProfilePage"

export const Route = createFileRoute("/_layout/profile")({
  component: ProfilePage,
  head: () => ({ meta: [{ title: "个人档案 - ApplyPilot" }] }),
})
