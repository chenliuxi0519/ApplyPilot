import { Link } from "@tanstack/react-router"
import { Compass } from "lucide-react"

import { cn } from "@/lib/utils"

interface LogoProps {
  variant?: "full" | "icon" | "responsive"
  className?: string
  asLink?: boolean
}

export function Logo({
  variant = "full",
  className,
  asLink = true,
}: LogoProps) {
  const showName = variant !== "icon"
  const content = (
    <span
      className={cn(
        "inline-flex items-center gap-2.5 tracking-tight",
        className,
      )}
    >
      <span className="flex size-[30px] shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-violet-500 text-white shadow-sm">
        <Compass className="size-[18px]" aria-hidden="true" />
      </span>
      {showName && (
        <span
          className={cn(
            "display-font text-[17px] text-[var(--text-primary)]",
            variant === "responsive" && "group-data-[collapsible=icon]:hidden",
          )}
        >
          ApplyPilot
        </span>
      )}
    </span>
  )

  if (!asLink) {
    return content
  }

  return (
    <Link to="/" aria-label="ApplyPilot">
      {content}
    </Link>
  )
}
