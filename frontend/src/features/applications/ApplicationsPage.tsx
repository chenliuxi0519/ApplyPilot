import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import {
  CalendarDays,
  CheckCircle2,
  Circle,
  LayoutGrid,
  List,
  Loader2,
  Pencil,
  Plus,
  Trash2,
} from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import {
  type ApplicationDetailPublic,
  type ApplicationStatus,
  ApplicationsService,
  ApplicationTasksService,
  ProgramsService,
  type TaskPublic,
  type TaskType,
} from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import {
  applicationStatusLabels,
  programTitle,
  taskStatusLabels,
} from "@/features/programs/presentation"

const statusColumns: ApplicationStatus[] = [
  "shortlisted",
  "preparing",
  "ready_to_submit",
  "submitted",
  "result_pending",
  "offered",
  "rejected",
  "withdrawn",
]
const allowedTransitions: Record<ApplicationStatus, ApplicationStatus[]> = {
  shortlisted: ["preparing", "withdrawn"],
  preparing: ["shortlisted", "ready_to_submit", "withdrawn"],
  ready_to_submit: ["preparing", "submitted", "withdrawn"],
  submitted: ["result_pending", "offered", "rejected", "withdrawn"],
  result_pending: ["offered", "rejected", "withdrawn"],
  offered: ["withdrawn"],
  rejected: [],
  withdrawn: ["shortlisted"],
}
const highRiskStatuses: ApplicationStatus[] = [
  "submitted",
  "withdrawn",
  "offered",
  "rejected",
]
const taskTypeLabels: Record<TaskType, string> = {
  cv: "个人简历",
  personal_statement: "个人陈述",
  transcript: "成绩单",
  language_score: "语言成绩",
  recommendation: "推荐信",
  application_form: "申请表",
  other: "其他",
}
const taskTitleLabels: Record<string, string> = {
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

export function ApplicationsPage() {
  const [view, setView] = useState<"board" | "timeline">("board")
  const applications = useQuery({
    queryKey: ["applications"],
    queryFn: () => ApplicationsService.listApplications({ limit: 200 }),
  })
  const details = useQueries({
    queries: (applications.data?.data ?? []).map((application) => ({
      queryKey: ["application", application.id],
      queryFn: () =>
        ApplicationsService.readApplication({ applicationId: application.id }),
    })),
  })
  const programs = useQueries({
    queries: (applications.data?.data ?? []).map((application) => ({
      queryKey: ["program", application.program_id],
      queryFn: () =>
        ProgramsService.readProgram({ programId: application.program_id }),
    })),
  })

  if (applications.isLoading) return <Skeleton className="h-96 w-full" />
  if (applications.isError)
    return <p className="text-destructive">申请计划加载失败，请稍后重试。</p>
  const rows = (applications.data?.data ?? []).map((application, index) => ({
    application: details[index]?.data ?? {
      ...application,
      tasks: [],
      readiness: {
        is_ready: false,
        required_total: 0,
        required_done: 0,
        blocking_tasks: [],
      },
    },
    program: programs[index]?.data,
  }))

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <h1 className="page-title">申请管理</h1>
          <p className="page-subtitle">
            按阶段、时间和材料任务持续推进申请。
          </p>
        </div>
        <div className="flex rounded-lg border p-1">
          <Button
            size="sm"
            variant={view === "board" ? "secondary" : "ghost"}
            onClick={() => setView("board")}
          >
            <LayoutGrid />
            看板
          </Button>
          <Button
            size="sm"
            variant={view === "timeline" ? "secondary" : "ghost"}
            onClick={() => setView("timeline")}
          >
            <List />
            时间线
          </Button>
        </div>
      </div>
      {rows.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <p className="font-medium">还没有申请项目</p>
            <p className="mt-1 text-sm text-muted-foreground">
              先到“项目对比”页面把目标项目加入计划。
            </p>
          </CardContent>
        </Card>
      ) : view === "timeline" ? (
        <Timeline rows={rows} />
      ) : (
        <div className="overflow-x-auto pb-4">
          <div className="flex min-w-max gap-4">
            {statusColumns.slice(0, 6).map((status) => {
              const cards = rows.filter(
                (row) => row.application.status === status,
              )
              return (
                <section key={status} className="w-[280px] min-h-[400px] overflow-hidden rounded-[9px] bg-[var(--bg)]">
                  <div className="flex items-center justify-between border-l-[3px] border-l-primary bg-[var(--surface-raised)] px-4 py-3">
                    <h2 className="text-[13px] font-semibold">
                      {applicationStatusLabels[status]}
                    </h2>
                    <Badge className="font-mono text-[11px]" variant="secondary">{cards.length}</Badge>
                  </div>
                  {cards.length === 0 ? (
                    <div className="m-2.5 min-h-[300px] rounded-xl border border-dashed p-5 text-center text-xs text-muted-foreground">
                      暂无项目
                    </div>
                  ) : (
                    <div className="p-2.5">{cards.map((row) => (
                      <ApplicationCard
                        key={row.application.id}
                        detail={row.application}
                        title={
                          row.program
                            ? programTitle(row.program)
                            : "项目加载中…"
                        }
                      />
                    ))}</div>
                  )}
                </section>
              )
            })}
          </div>
          <div className="mt-5 grid min-w-[560px] grid-cols-2 gap-4">
            {statusColumns.slice(6).map((status) => {
              const cards = rows.filter(
                (row) => row.application.status === status,
              )
              return (
                <section key={status} className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h2 className="font-semibold text-muted-foreground">
                      {applicationStatusLabels[status]}
                    </h2>
                    <Badge variant="outline">{cards.length}</Badge>
                  </div>
                  {cards.map((row) => (
                    <ApplicationCard
                      key={row.application.id}
                      detail={row.application}
                      title={
                        row.program ? programTitle(row.program) : "项目加载中…"
                      }
                    />
                  ))}
                </section>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

function ApplicationCard({
  detail,
  title,
}: {
  detail: ApplicationDetailPublic
  title: string
}) {
  const [pendingStatus, setPendingStatus] = useState<ApplicationStatus | null>(
    null,
  )
  const [editor, setEditor] = useState<TaskPublic | "new" | null>(null)
  const [deleteTask, setDeleteTask] = useState<TaskPublic | null>(null)
  const queryClient = useQueryClient()
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["applications"] })
    queryClient.invalidateQueries({ queryKey: ["application", detail.id] })
  }
  const changeStatus = useMutation({
    mutationFn: (status: ApplicationStatus) =>
      ApplicationsService.updateApplication({
        applicationId: detail.id,
        requestBody: {
          version: detail.version,
          status,
          confirm: highRiskStatuses.includes(status),
        },
      }),
    onSuccess: () => {
      refresh()
      setPendingStatus(null)
      toast.success("申请阶段已更新")
    },
    onError: () =>
      toast.error("阶段更新失败，请先完成必需材料或按正确顺序推进"),
  })
  const changeTask = useMutation({
    mutationFn: (task: TaskPublic) =>
      ApplicationTasksService.updateApplicationTask({
        taskId: task.id,
        requestBody: {
          version: task.version,
          status: task.status === "done" ? "todo" : "done",
        },
      }),
    onSuccess: () => {
      refresh()
      toast.success("任务状态已更新")
    },
    onError: () => toast.error("任务更新失败，请刷新后重试"),
  })
  return (
    <Card className="lift-card mb-2.5 gap-4 rounded-[9px] py-3.5 transition-all hover:-translate-y-0.5 hover:border-primary">
      <CardHeader className="px-4">
        <CardTitle className="text-sm leading-5">{title}</CardTitle>
        <CardDescription className="metric flex items-center gap-1 text-[11px]">
          <CalendarDays className="size-3" />
          {detail.target_deadline
            ? `截止：${detail.target_deadline}`
            : `申请季：${detail.application_cycle}`}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 px-4">
        <Select
          value={detail.status}
          onValueChange={(value) => {
            const status = value as ApplicationStatus
            if (highRiskStatuses.includes(status)) setPendingStatus(status)
            else changeStatus.mutate(status)
          }}
          disabled={changeStatus.isPending}
        >
          <SelectTrigger aria-label="申请阶段">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={detail.status}>
              {applicationStatusLabels[detail.status]}
            </SelectItem>
            {allowedTransitions[detail.status].map((status) => (
              <SelectItem key={status} value={status}>
                {applicationStatusLabels[status]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div>
          <div className="mb-2 flex items-center justify-between text-xs">
            <span>必需材料进度</span>
            <span>
              {detail.readiness.required_done}/{detail.readiness.required_total}
            </span>
          </div>
          <div className="h-1 overflow-hidden rounded-full bg-[var(--border)]">
            <div
              className="h-full bg-primary transition-all"
              style={{
                width: detail.readiness.required_total
                  ? `${(detail.readiness.required_done / detail.readiness.required_total) * 100}%`
                  : "100%",
              }}
            />
          </div>
        </div>
        <ul className="space-y-1">
          {detail.tasks.map((task) => (
            <li key={task.id} className="group flex items-start gap-1">
              <button
                type="button"
                className="flex min-w-0 flex-1 items-start gap-2 rounded-md p-1.5 text-left text-xs hover:bg-muted disabled:opacity-60"
                onClick={() => changeTask.mutate(task)}
                disabled={changeTask.isPending}
              >
                {changeTask.isPending &&
                changeTask.variables?.id === task.id ? (
                  <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin" />
                ) : task.status === "done" ? (
                  <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" />
                ) : (
                  <Circle className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                )}
                <span
                  className={
                    task.status === "done"
                      ? "text-muted-foreground line-through"
                      : ""
                  }
                >
                  {taskTitleLabels[task.title] ?? task.title}
                  {task.is_required && (
                    <span className="text-destructive"> *</span>
                  )}
                  <span className="ml-1 text-muted-foreground">
                    · {taskStatusLabels[task.status]}
                  </span>
                </span>
              </button>
              {task.source === "user" && (
                <div className="flex opacity-0 transition group-hover:opacity-100 group-focus-within:opacity-100">
                  <Button
                    size="icon"
                    variant="ghost"
                    className="size-7"
                    aria-label={`编辑 ${task.title}`}
                    onClick={() => setEditor(task)}
                  >
                    <Pencil className="size-3" />
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="size-7 text-destructive"
                    aria-label={`删除 ${task.title}`}
                    onClick={() => setDeleteTask(task)}
                  >
                    <Trash2 className="size-3" />
                  </Button>
                </div>
              )}
            </li>
          ))}
        </ul>
        <Button
          variant="outline"
          size="sm"
          className="w-full"
          onClick={() => setEditor("new")}
        >
          <Plus />
          新增任务
        </Button>
      </CardContent>
      <RiskDialog
        status={pendingStatus}
        loading={changeStatus.isPending}
        onCancel={() => setPendingStatus(null)}
        onConfirm={() => pendingStatus && changeStatus.mutate(pendingStatus)}
      />
      <TaskEditor
        applicationId={detail.id}
        task={editor}
        onClose={() => setEditor(null)}
        onSaved={refresh}
      />
      <DeleteTaskDialog
        task={deleteTask}
        onClose={() => setDeleteTask(null)}
        onDeleted={refresh}
      />
    </Card>
  )
}

function RiskDialog({
  status,
  loading,
  onCancel,
  onConfirm,
}: {
  status: ApplicationStatus | null
  loading: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const effects: Partial<Record<ApplicationStatus, string>> = {
    submitted: "系统会把申请记录为已正式提交，提交后必需材料不能重新打开。",
    withdrawn: "申请将离开当前执行流程，但之后仍可重新加入计划。",
    offered: "系统会记录学校已发放录取结果。",
    rejected: "系统会记录未录取；该状态不能撤销。",
  }
  return (
    <Dialog open={Boolean(status)} onOpenChange={(open) => !open && onCancel()}>
      <DialogContent className="max-w-[400px] rounded-xl border bg-[var(--surface)] p-6 backdrop-blur-sm">
        <DialogHeader>
          <DialogTitle>确认更新申请状态</DialogTitle>
          <DialogDescription>
            {status
              ? `即将把申请改为“${applicationStatusLabels[status]}”。${effects[status] ?? ""}`
              : ""}
          </DialogDescription>
        </DialogHeader>
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-100">
          请确认该状态与学校官网或你实际完成的操作一致。
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>
            取消
          </Button>
          <Button onClick={onConfirm} disabled={loading}>
            {loading ? "更新中…" : "确认更新"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function TaskEditor({
  applicationId,
  task,
  onClose,
  onSaved,
}: {
  applicationId: string
  task: TaskPublic | "new" | null
  onClose: () => void
  onSaved: () => void
}) {
  const [title, setTitle] = useState("")
  const [dueDate, setDueDate] = useState("")
  const [type, setType] = useState<TaskType>("other")
  const [required, setRequired] = useState(false)
  const open = task !== null
  const shownTitle = task && task !== "new" ? title || task.title : title
  const shownDate =
    task && task !== "new" ? dueDate || task.due_date || "" : dueDate
  const save = useMutation({
    mutationFn: () =>
      task === "new"
        ? ApplicationsService.createApplicationTask({
            applicationId,
            requestBody: {
              title: shownTitle,
              due_date: shownDate || null,
              task_type: type,
              is_required: required,
            },
          })
        : ApplicationTasksService.updateApplicationTask({
            taskId: (task as TaskPublic).id,
            requestBody: {
              version: (task as TaskPublic).version,
              title: shownTitle,
              due_date: shownDate || null,
            },
          }),
    onSuccess: () => {
      onSaved()
      onClose()
      setTitle("")
      setDueDate("")
      toast.success(task === "new" ? "任务已创建" : "任务已更新")
    },
    onError: () => toast.error("任务保存失败，请检查内容后重试"),
  })
  return (
    <Dialog open={open} onOpenChange={(value) => !value && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{task === "new" ? "新增任务" : "编辑任务"}</DialogTitle>
          <DialogDescription>
            记录材料、沟通或提交节点，并设置计划日期。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="task-title">任务名称</Label>
            <Input
              id="task-title"
              value={shownTitle}
              onChange={(event) => setTitle(event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="task-due">计划日期</Label>
            <Input
              id="task-due"
              type="date"
              value={shownDate}
              onChange={(event) => setDueDate(event.target.value)}
            />
          </div>
          {task === "new" && (
            <>
              <div className="space-y-2">
                <Label>任务类型</Label>
                <Select
                  value={type}
                  onValueChange={(value) => setType(value as TaskType)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(taskTypeLabels).map(([value, label]) => (
                      <SelectItem key={value} value={value}>
                        {label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Label className="flex items-center gap-2">
                <Checkbox
                  checked={required}
                  onCheckedChange={(value) => setRequired(value === true)}
                />
                提交前必须完成
              </Label>
            </>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button
            onClick={() => save.mutate()}
            disabled={!shownTitle.trim() || save.isPending}
          >
            {save.isPending ? "保存中…" : "保存任务"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function DeleteTaskDialog({
  task,
  onClose,
  onDeleted,
}: {
  task: TaskPublic | null
  onClose: () => void
  onDeleted: () => void
}) {
  const remove = useMutation({
    mutationFn: () =>
      ApplicationTasksService.deleteApplicationTask({
        taskId: task!.id,
        version: task!.version,
      }),
    onSuccess: () => {
      onDeleted()
      onClose()
      toast.success("任务已删除")
    },
    onError: () => toast.error("任务删除失败，请刷新后重试"),
  })
  return (
    <Dialog open={Boolean(task)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>删除自建任务</DialogTitle>
          <DialogDescription>
            “{task?.title}”将被永久删除，此操作无法撤销。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button
            variant="destructive"
            onClick={() => remove.mutate()}
            disabled={remove.isPending}
          >
            {remove.isPending ? "删除中…" : "确认删除"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Timeline({
  rows,
}: {
  rows: Array<{
    application: ApplicationDetailPublic
    program: Awaited<ReturnType<typeof ProgramsService.readProgram>> | undefined
  }>
}) {
  const events = rows
    .flatMap(({ application, program }) => [
      {
        key: `deadline-${application.id}`,
        date: application.target_deadline,
        title: `${program ? programTitle(program) : "申请项目"}截止`,
        kind: "申请截止",
      },
      ...application.tasks
        .filter((task) => task.due_date)
        .map((task) => ({
          key: task.id,
          date: task.due_date,
          title: taskTitleLabels[task.title] ?? task.title,
          kind: taskStatusLabels[task.status],
        })),
    ])
    .filter((event) => event.date)
    .sort((a, b) => (a.date ?? "").localeCompare(b.date ?? ""))
  return (
    <Card>
      <CardHeader>
        <CardTitle>申请时间线</CardTitle>
        <CardDescription>按日期汇总所有项目截止和材料任务。</CardDescription>
      </CardHeader>
      <CardContent>
        {events.length === 0 ? (
          <p className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
            尚未设置任何截止日期或任务日期。
          </p>
        ) : (
          <ol className="relative ml-3 border-l">
            {events.map((event) => (
              <li key={event.key} className="relative ml-6 pb-6 last:pb-0">
                <span className="absolute -left-[31px] top-1.5 size-3 rounded-full border-2 border-background bg-primary" />
                <p className="text-sm text-muted-foreground">{event.date}</p>
                <p className="font-medium">{event.title}</p>
                <Badge variant="outline" className="mt-1">
                  {event.kind}
                </Badge>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  )
}
