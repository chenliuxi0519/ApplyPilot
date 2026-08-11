import { useQueries, useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  CircleUserRound,
  GraduationCap,
  ListChecks,
  MessageSquareText,
} from "lucide-react"

import { ApplicationsService, ProfileService, ProgramsService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import {
  applicationStatusLabels,
  programTitle,
} from "@/features/programs/presentation"
import useAuth from "@/hooks/useAuth"

const dashboardTaskLabels: Record<string, string> = {
  // 兼容中文化前已经写入数据库的系统任务标题。
  "Prepare CV": "准备个人简历",
  "Write personal statement": "撰写个人陈述",
  "Obtain transcript": "准备成绩单",
  "Complete application form": "填写申请表",
  "Request recommendation letters": "邀请推荐人并准备推荐信",
  "Provide language test score": "提供语言考试成绩",
  "Provide language test score (requirement not verified yet)":
    "提供语言考试成绩（要求尚待验证）",
}

export const Route = createFileRoute("/_layout/")({
  component: Dashboard,
  head: () => ({ meta: [{ title: "首页 - ApplyPilot" }] }),
})

function Dashboard() {
  const { user } = useAuth()
  const profile = useQuery({
    queryKey: ["profile"],
    queryFn: () => ProfileService.readProfileMe(),
    retry: false,
  })
  const applications = useQuery({
    queryKey: ["applications"],
    queryFn: () => ApplicationsService.listApplications({ limit: 200 }),
  })
  const details = useQueries({
    queries: (applications.data?.data ?? []).map((item) => ({
      queryKey: ["application", item.id],
      queryFn: () =>
        ApplicationsService.readApplication({ applicationId: item.id }),
    })),
  })
  const programs = useQueries({
    queries: (applications.data?.data ?? []).map((item) => ({
      queryKey: ["program", item.program_id],
      queryFn: () =>
        ProgramsService.readProgram({ programId: item.program_id }),
    })),
  })

  if (profile.isLoading || applications.isLoading)
    return <Skeleton className="h-[520px] w-full" />
  const profileValues = profile.data
    ? [
        profile.data.undergraduate_university,
        profile.data.undergraduate_major,
        profile.data.gpa_value,
        profile.data.ielts_overall,
        profile.data.budget_cny,
        profile.data.target_regions.length,
        profile.data.target_fields.length,
        profile.data.career_goal,
      ]
    : []
  const completeness =
    Math.round((profileValues.filter(Boolean).length / 8) * 100) || 0
  const allTasks = details.flatMap((result, index) =>
    (result.data?.tasks ?? []).map((task) => ({
      ...task,
      program: programs[index]?.data,
    })),
  )
  const pendingTasks = allTasks
    .filter((task) => task.status !== "done")
    .sort((a, b) => (a.due_date ?? "9999").localeCompare(b.due_date ?? "9999"))
    .slice(0, 5)
    .map((task) => ({
      ...task,
      title: dashboardTaskLabels[task.title] ?? task.title,
    }))
  const deadlines = (applications.data?.data ?? [])
    .filter(
      (item) =>
        item.target_deadline &&
        !["rejected", "withdrawn"].includes(item.status),
    )
    .sort((a, b) =>
      (a.target_deadline ?? "").localeCompare(b.target_deadline ?? ""),
    )
    .slice(0, 4)

  return (
    <div className="space-y-7">
      <div>
        <h1 className="text-2xl font-semibold">
          欢迎回来，{user?.full_name || user?.email}
        </h1>
        <p className="text-muted-foreground">
          从目标到提交，所有进度集中在这里。
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          icon={CircleUserRound}
          label="档案完整度"
          value={`${completeness}%`}
          hint={completeness === 100 ? "档案已完善" : "继续补充可提升匹配质量"}
        />
        <Stat
          icon={GraduationCap}
          label="申请项目"
          value={`${applications.data?.count ?? 0}`}
          hint="全部申请季"
        />
        <Stat
          icon={ListChecks}
          label="待办材料"
          value={`${allTasks.filter((task) => task.status !== "done").length}`}
          hint={`${allTasks.filter((task) => task.status === "done").length} 项已完成`}
        />
        <Stat
          icon={CalendarClock}
          label="近期截止"
          value={`${deadlines.length}`}
          hint="按截止日期排序"
        />
      </div>
      <div className="grid gap-5 lg:grid-cols-[1.25fr_.75fr]">
        <Card>
          <CardHeader>
            <CardTitle>下一步行动</CardTitle>
            <CardDescription>
              优先处理临近截止且尚未完成的材料。
            </CardDescription>
          </CardHeader>
          <CardContent>
            {pendingTasks.length === 0 ? (
              <Empty text="当前没有待办任务。" />
            ) : (
              <ul className="divide-y">
                {pendingTasks.map((task) => (
                  <li
                    key={task.id}
                    className="flex items-start justify-between gap-3 py-3 first:pt-0"
                  >
                    <div>
                      <p className="text-sm font-medium">{task.title}</p>
                      <p className="text-xs text-muted-foreground">
                        {task.program ? programTitle(task.program) : "申请项目"}
                      </p>
                    </div>
                    <Badge variant="outline">
                      {task.due_date ?? "未设置日期"}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
            <Button asChild variant="link" className="mt-3 px-0">
              <Link to="/applications">
                打开申请看板
                <ArrowRight />
              </Link>
            </Button>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>申请日程</CardTitle>
            <CardDescription>最近的项目截止日期。</CardDescription>
          </CardHeader>
          <CardContent>
            {deadlines.length === 0 ? (
              <Empty text="暂无已确认的截止日期。" />
            ) : (
              <ul className="space-y-3">
                {deadlines.map((item) => {
                  const index = (applications.data?.data ?? []).findIndex(
                    (candidate) => candidate.id === item.id,
                  )
                  const program = programs[index]?.data
                  return (
                    <li key={item.id} className="rounded-lg border p-3">
                      <div className="flex justify-between gap-2">
                        <p className="text-sm font-medium">
                          {program ? programTitle(program) : "项目加载中…"}
                        </p>
                        <Badge>{applicationStatusLabels[item.status]}</Badge>
                      </div>
                      <p className="mt-2 text-sm text-muted-foreground">
                        截止：{item.target_deadline}
                      </p>
                    </li>
                  )
                })}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <QuickLink
          to="/agent"
          icon={MessageSquareText}
          title="咨询智能助手"
          description="用自然语言制定目标或继续申请。"
        />
        <QuickLink
          to="/programs"
          icon={GraduationCap}
          title="发现匹配项目"
          description="查看分组、差距和官网证据。"
        />
        <QuickLink
          to="/profile"
          icon={CheckCircle2}
          title="完善个人档案"
          description="更新成绩、经历、预算与目标。"
        />
      </div>
    </div>
  )
}

function Stat({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: typeof CircleUserRound
  label: string
  value: string
  hint: string
}) {
  return (
    <Card className="gap-3 py-5">
      <CardContent className="px-5">
        <div className="flex items-center justify-between">
          <span className="text-sm text-muted-foreground">{label}</span>
          <Icon className="size-4 text-primary" />
        </div>
        <p className="mt-2 text-3xl font-semibold">{value}</p>
        <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
      </CardContent>
    </Card>
  )
}
function Empty({ text }: { text: string }) {
  return (
    <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
      {text}
    </p>
  )
}
function QuickLink({
  to,
  icon: Icon,
  title,
  description,
}: {
  to: "/agent" | "/programs" | "/profile"
  icon: typeof CircleUserRound
  title: string
  description: string
}) {
  return (
    <Link
      to={to}
      className="rounded-xl border bg-card p-5 transition hover:border-primary hover:shadow-sm"
    >
      <Icon className="size-5 text-primary" />
      <p className="mt-4 font-medium">{title}</p>
      <p className="mt-1 text-sm text-muted-foreground">{description}</p>
    </Link>
  )
}
