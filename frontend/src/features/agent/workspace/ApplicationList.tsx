import { useQueries } from "@tanstack/react-query"

import {
  type ApplicationPublic,
  ApplicationsService,
  ProgramsService,
} from "@/client"
import { ApplicationCard } from "./ApplicationCard"

interface ApplicationListProps {
  applications: ApplicationPublic[]
}

export function ApplicationList({ applications }: ApplicationListProps) {
  const details = useQueries({
    queries: applications.map((application) => ({
      queryKey: ["applications", application.id],
      queryFn: () =>
        ApplicationsService.readApplication({ applicationId: application.id }),
    })),
  })

  const programs = useQueries({
    queries: applications.map((application) => ({
      queryKey: ["programs", application.program_id],
      queryFn: () =>
        ProgramsService.readProgram({ programId: application.program_id }),
      staleTime: Number.POSITIVE_INFINITY,
    })),
  })

  if (applications.length === 0) {
    return (
      <p className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
        还没有申请项目。你可以让 ApplyPilot 把心仪项目加入申请计划。
      </p>
    )
  }

  return (
    <div className="space-y-3" data-testid="application-list">
      {applications.map((application, index) => {
        const program = programs[index]?.data
        return (
          <ApplicationCard
            key={application.id}
            application={application}
            detail={details[index]?.data ?? null}
            programLabel={
              program
                ? `${program.university.short_name} ${program.name}`
                : null
            }
          />
        )
      })}
    </div>
  )
}
