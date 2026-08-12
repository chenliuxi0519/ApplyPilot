import {
  Columns3,
  FileCheck2,
  GraduationCap,
  Home,
  MessagesSquare,
  UserRound,
  Users,
} from "lucide-react"

import { SidebarAppearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import useAuth from "@/hooks/useAuth"
import { Main, type NavItem } from "./Main"
import { User } from "./User"

const baseItems: NavItem[] = [
  { icon: Home, title: "首页", path: "/" },
  { icon: MessagesSquare, title: "智能助手", path: "/agent" },
  { icon: UserRound, title: "个人档案", path: "/profile" },
  { icon: GraduationCap, title: "项目对比", path: "/programs" },
  { icon: FileCheck2, title: "证据库", path: "/evidence" },
  { icon: Columns3, title: "申请看板", path: "/applications" },
]

export function AppSidebar() {
  const { user: currentUser } = useAuth()

  const items = currentUser?.is_superuser
    ? [...baseItems, { icon: Users, title: "用户管理", path: "/admin" }]
    : baseItems

  return (
    <Sidebar collapsible="icon" className="border-r border-[var(--border)]">
      <SidebarHeader className="h-16 justify-center border-b border-[var(--border-subtle)] px-4 group-data-[collapsible=icon]:px-0 group-data-[collapsible=icon]:items-center">
        <div className="flex items-center justify-between gap-2">
          <Logo variant="responsive" />
          <SidebarTrigger className="shrink-0 text-muted-foreground group-data-[collapsible=icon]:hidden" />
        </div>
      </SidebarHeader>
      <SidebarContent>
        <Main items={items} />
      </SidebarContent>
      <SidebarFooter className="gap-2 border-t border-[var(--border-subtle)] p-3">
        {/* 折叠后头部的收起按钮会隐藏，这里补一个展开入口。 */}
        <SidebarTrigger className="hidden text-muted-foreground group-data-[collapsible=icon]:flex group-data-[collapsible=icon]:self-center" />
        <SidebarAppearance />
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
