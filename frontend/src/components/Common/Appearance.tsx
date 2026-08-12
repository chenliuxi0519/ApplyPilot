import { Monitor, Moon, Sun } from "lucide-react"

import { useTheme } from "@/components/theme-provider"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

export const SidebarAppearance = () => {
  const { resolvedTheme, setTheme } = useTheme()
  const dark = resolvedTheme === "dark"

  return (
    // 不能用 <li>：外面没有 <ul>，浏览器会给它加上项目符号。
    <div className="relative">
      <button
        type="button"
        data-testid="theme-button"
        onClick={() => setTheme(dark ? "light" : "dark")}
        className="flex h-9 w-full items-center justify-between px-1 text-xs text-[var(--text-muted)] group-data-[collapsible=icon]:justify-center"
      >
        <span className="group-data-[collapsible=icon]:hidden">
          {dark ? "深色模式" : "浅色模式"}
        </span>
        <span
          className={`relative h-5 w-9 rounded-full ${dark ? "bg-[#1A2540]" : "bg-[#E2E8F6]"}`}
        >
          <span
            className={`absolute top-0.5 flex size-4 items-center justify-center rounded-full bg-primary text-[9px] text-white transition-transform ${dark ? "translate-x-[18px]" : "translate-x-0.5"}`}
          >
            {dark ? "☾" : "☀"}
          </span>
        </span>
        <span
          data-testid={dark ? "light-mode" : "dark-mode"}
          className="sr-only"
        >
          切换主题
        </span>
      </button>
    </div>
  )
}

export const Appearance = () => {
  const { setTheme } = useTheme()

  return (
    <div className="flex items-center justify-center">
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <Button data-testid="theme-button" variant="outline" size="icon">
            <Sun className="h-[1.2rem] w-[1.2rem] rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
            <Moon className="absolute h-[1.2rem] w-[1.2rem] rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
            <span className="sr-only">切换主题</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem
            data-testid="light-mode"
            onClick={() => setTheme("light")}
          >
            <Sun className="mr-2 h-4 w-4" />
            Light
          </DropdownMenuItem>
          <DropdownMenuItem
            data-testid="dark-mode"
            onClick={() => setTheme("dark")}
          >
            <Moon className="mr-2 h-4 w-4" />
            Dark
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => setTheme("system")}>
            <Monitor className="mr-2 h-4 w-4" />
            System
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}
