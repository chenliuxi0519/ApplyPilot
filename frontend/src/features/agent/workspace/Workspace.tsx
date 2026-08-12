import { useQuery } from "@tanstack/react-query"

import { ApplicationsService } from "@/client"
import { Skeleton } from "@/components/ui/skeleton"
import { useProfile } from "@/hooks/useProfile"
import { ApplicationList } from "./ApplicationList"
import { ProfileSummary } from "./ProfileSummary"

export function Workspace() {
  const profile = useProfile()

  const applications = useQuery({
    queryKey: ["applications"],
    queryFn: () => ApplicationsService.listApplications({}),
  })

  return (
    <aside
      data-testid="workspace"
      className="flex h-full w-full flex-col overflow-y-auto border-l bg-[#F8FAFF] dark:bg-[#0A1220]"
    >
      <div className="border-b px-4 py-3">
        <h2 className="text-sm font-semibold">我的工作区</h2>
        <p className="text-xs text-muted-foreground">
          随智能助手的操作实时更新
        </p>
      </div>

      <div className="space-y-6 p-4">
        <Section title="个人档案">
          {profile.isLoading ? (
            <Skeleton className="h-24 w-full" />
          ) : (
            <ProfileSummary profile={profile.data ?? null} />
          )}
        </Section>

        <Section title="申请项目">
          {applications.isLoading ? (
            <Skeleton className="h-24 w-full" />
          ) : (
            <ApplicationList applications={applications.data?.data ?? []} />
          )}
        </Section>
      </div>
    </aside>
  )
}

function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <section className="space-y-2">
      <h3 className="border-l-2 border-[var(--accent-brand)] pl-2 text-xs font-semibold text-[var(--text-secondary)]">
        {title}
      </h3>
      {children}
    </section>
  )
}
