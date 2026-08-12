import { Link as RouterLink, useRouterState } from "@tanstack/react-router"
import type { LucideIcon } from "lucide-react"

import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"

export type NavItem = {
  icon: LucideIcon
  title: string
  path: string
}

interface MainProps {
  items: NavItem[]
}

export function Main({ items }: MainProps) {
  const { isMobile, setOpenMobile } = useSidebar()
  const router = useRouterState()
  const currentPath = router.location.pathname

  const handleMenuClick = () => {
    if (isMobile) {
      setOpenMobile(false)
    }
  }

  return (
    <SidebarGroup className="px-2 py-3">
      <SidebarGroupContent>
        <SidebarMenu>
          {items.map((item) => {
            const isActive = currentPath === item.path

            return (
              <SidebarMenuItem key={item.title}>
                <SidebarMenuButton
                  className="h-[38px] rounded-[7px] border-l-2 border-transparent px-2.5 text-[13.5px] font-normal text-[var(--text-muted)] hover:bg-sidebar-accent/60 hover:text-[var(--text-secondary)] data-[active=true]:border-l-primary data-[active=true]:bg-sidebar-accent data-[active=true]:font-medium data-[active=true]:text-[var(--text-primary)] data-[active=true]:[&_svg]:text-primary"
                  tooltip={item.title}
                  isActive={isActive}
                  asChild
                >
                  <RouterLink to={item.path} onClick={handleMenuClick}>
                    <item.icon />
                    <span>{item.title}</span>
                  </RouterLink>
                </SidebarMenuButton>
              </SidebarMenuItem>
            )
          })}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  )
}
