import { GraduationCap } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import type { ProgramSummary } from "../types"

const REGION_LABELS: Record<string, string> = {
  singapore: "新加坡",
  hong_kong: "中国香港",
  united_kingdom: "英国",
}

const DEGREE_LABELS: Record<string, string> = {
  taught_master: "授课型硕士",
  taught_masters: "授课型硕士",
  research_master: "研究型硕士",
  phd: "博士",
}

interface ProgramCardProps {
  program: ProgramSummary
  onViewRequirements: (program: ProgramSummary) => void
  onAddToPlan: (program: ProgramSummary) => void
  disabled?: boolean
}

export function ProgramCard({
  program,
  onViewRequirements,
  onAddToPlan,
  disabled,
}: ProgramCardProps) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md bg-muted">
          <GraduationCap className="size-4 text-muted-foreground" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-muted-foreground">
            {program.university}
          </p>
          <p className="font-medium leading-snug">{program.name}</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Badge variant="secondary" className="font-normal">
              {REGION_LABELS[program.region] ?? program.region}
            </Badge>
            <Badge variant="secondary" className="font-normal">
              {DEGREE_LABELS[program.degree_type] ?? program.degree_type}
            </Badge>
            {program.field_tags.map((tag) => (
              <Badge key={tag} variant="outline" className="font-normal">
                {tag}
              </Badge>
            ))}
          </div>
        </div>
      </div>
      <div className="mt-3 flex gap-2">
        <Button
          size="sm"
          variant="outline"
          disabled={disabled}
          onClick={() => onViewRequirements(program)}
        >
          查看申请要求
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={disabled}
          onClick={() => onAddToPlan(program)}
        >
          加入申请计划
        </Button>
      </div>
    </div>
  )
}
