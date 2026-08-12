import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import {
  ExternalLink,
  FileSearch,
  ListChecks,
  Plus,
  Scale,
  Search,
  X,
} from "lucide-react"
import { useMemo, useState } from "react"
import { toast } from "sonner"

import {
  ApplicationsService,
  type EvidencePublic,
  ProgramsService,
  type ProgramWithUniversityPublic,
  type RequirementPublic,
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
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { useProfile } from "@/hooks/useProfile"
import {
  assessProgram,
  evidenceStatusLabels,
  formatComparisonValue,
  formatRequirementValue,
  matchGroupLabels,
  programTitle,
  regionLabels,
  requirementLabels,
} from "./presentation"

/** 稳定的空数组引用，避免每次渲染都产生新对象而让下游 memo 失效。 */
const EMPTY_REQUIREMENTS: RequirementPublic[] = []

export function ProgramsPage() {
  const queryClient = useQueryClient()
  const [query, setQuery] = useState("")
  const [submittedQuery, setSubmittedQuery] = useState("")
  const [region, setRegion] = useState("all")
  const [cycle, setCycle] = useState("2026/27")
  const [selected, setSelected] = useState<ProgramWithUniversityPublic[]>([])
  const [evidenceProgram, setEvidenceProgram] =
    useState<ProgramWithUniversityPublic | null>(null)
  const [detailProgram, setDetailProgram] =
    useState<ProgramWithUniversityPublic | null>(null)

  const programs = useQuery({
    queryKey: ["programs", submittedQuery, region],
    queryFn: () =>
      ProgramsService.searchPrograms({
        query: submittedQuery || undefined,
        region:
          region === "all"
            ? undefined
            : (region as "hong_kong" | "singapore" | "united_kingdom"),
        limit: 100,
      }),
  })
  const profile = useProfile()
  const allRequirements = useQueries({
    queries: (programs.data?.data ?? []).map((program) => ({
      queryKey: ["requirements", program.id, cycle],
      queryFn: () =>
        ProgramsService.readProgramRequirements({
          programId: program.id,
          applicationCycle: cycle,
        }),
      // 不设过期时间的话，每次重渲染都会重新请求，勾选对比时明显卡顿。
      staleTime: 5 * 60_000,
    })),
  })
  const requirementsById = useMemo(() => {
    const map = new Map<string, RequirementPublic[]>()
    ;(programs.data?.data ?? []).forEach((program, index) => {
      map.set(program.id, allRequirements[index]?.data?.data ?? [])
    })
    return map
  }, [programs.data, allRequirements])
  const requirementsFor = (programId: string) =>
    requirementsById.get(programId) ?? EMPTY_REQUIREMENTS
  const evidence = useQuery({
    queryKey: ["evidence", evidenceProgram?.id, cycle],
    queryFn: () =>
      ProgramsService.readProgramEvidence({
        programId: evidenceProgram!.id,
        applicationCycle: cycle,
      }),
    enabled: Boolean(evidenceProgram),
  })
  const detailEvidence = useQuery({
    queryKey: ["evidence", detailProgram?.id, cycle],
    queryFn: () =>
      ProgramsService.readProgramEvidence({
        programId: detailProgram!.id,
        applicationCycle: cycle,
      }),
    enabled: Boolean(detailProgram),
  })
  const addApplication = useMutation({
    mutationFn: (programId: string) =>
      ApplicationsService.createApplication({
        requestBody: { program_id: programId, application_cycle: cycle },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["applications"] })
      toast.success("已加入申请计划")
    },
    onError: () => toast.error("添加失败；该项目可能已在申请计划中"),
  })

  const toggleCompare = (program: ProgramWithUniversityPublic) => {
    setSelected((current) =>
      current.some((item) => item.id === program.id)
        ? current.filter((item) => item.id !== program.id)
        : current.length >= 3
          ? current
          : [...current, program],
    )
  }

  const selectedRequirements = useMemo(
    () =>
      selected.map(
        (program) => requirementsById.get(program.id) ?? EMPTY_REQUIREMENTS,
      ),
    [selected, requirementsById],
  )

  return (
    <div className="space-y-6">
      <div>
        <h1 className="page-title">项目检索与对比</h1>
        <p className="page-subtitle">
          检索官方项目库，对比要求，并追溯每个关键字段的来源。
        </p>
      </div>
      <Card className="border-0 bg-transparent py-0 shadow-none">
        <CardContent className="flex flex-col gap-3 px-0 pt-0 md:flex-row">
          <form
            className="flex flex-1 gap-2"
            onSubmit={(event) => {
              event.preventDefault()
              setSubmittedQuery(query.trim())
            }}
          >
            <Input
              aria-label="搜索项目"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索学校、项目或专业方向"
              className="h-12 rounded-[9px] bg-[var(--surface)] px-4 shadow-sm"
            />
            <Button type="submit" className="h-12 rounded-[9px] px-5">
              <Search />
              搜索
            </Button>
          </form>
          <Select value={region} onValueChange={setRegion}>
            <SelectTrigger className="h-12 rounded-[9px] bg-[var(--surface)] md:w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部地区</SelectItem>
              <SelectItem value="hong_kong">中国香港</SelectItem>
              <SelectItem value="singapore">新加坡</SelectItem>
              <SelectItem value="united_kingdom">英国</SelectItem>
            </SelectContent>
          </Select>
          <Input
            className="h-12 rounded-[9px] bg-[var(--surface)] md:w-32"
            aria-label="申请季"
            value={cycle}
            onChange={(event) => setCycle(event.target.value)}
            placeholder="2026/27"
          />
        </CardContent>
      </Card>

      {selected.length > 0 && (
        <Comparison
          programs={selected}
          requirements={selectedRequirements}
          onRemove={toggleCompare}
        />
      )}

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-xs text-[var(--text-muted)]">项目列表</h2>
          <span className="font-mono text-[11px] text-[var(--text-muted)]">
            找到 {programs.data?.count ?? 0} 个项目 ·{" "}
            {selected.length > 0
              ? `已选 ${selected.length}/3 个待对比`
              : "最多对比 3 个"}
          </span>
        </div>
        {programs.isLoading ? (
          <Skeleton className="h-64 w-full" />
        ) : programs.isError ? (
          <p className="text-destructive">项目加载失败，请稍后重试。</p>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            {programs.data?.data.map((program) => {
              const checked = selected.some((item) => item.id === program.id)
              const programRequirements = requirementsFor(program.id)
              const assessment = assessProgram(
                profile.data,
                programRequirements,
              )
              return (
                <Card
                  key={program.id}
                  className={`lift-card overflow-hidden rounded-[11px] transition-colors duration-150 hover:border-primary hover:shadow-md ${
                    checked
                      ? "border-primary bg-[var(--primary-muted)]"
                      : "bg-[var(--surface)]"
                  }`}
                >
                  <CardHeader>
                    <div className="flex items-start justify-between gap-3">
                      <button
                        type="button"
                        className="cursor-pointer text-left"
                        onClick={() => setDetailProgram(program)}
                      >
                        <CardTitle className="hover:text-primary hover:underline">
                          {program.name}
                        </CardTitle>
                        <CardDescription className="mt-1">
                          {program.university.name}（
                          {program.university.short_name}）
                        </CardDescription>
                      </button>
                      <div className="flex flex-col items-end gap-2">
                        <Badge variant="secondary">
                          {regionLabels[program.university.region]}
                        </Badge>
                        <Badge
                          className={`fit-badge ${assessment.group === "reach" ? "fit-reach" : assessment.group === "target" ? "fit-match" : assessment.group === "safer" ? "fit-safe" : ""}`}
                        >
                          {matchGroupLabels[assessment.group]}
                        </Badge>
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="flex flex-wrap gap-2">
                      {program.field_tags.map((tag) => (
                        <Badge key={tag} variant="outline">
                          {tag}
                        </Badge>
                      ))}
                      {program.duration_months && (
                        <Badge variant="outline">
                          {program.duration_months} 个月
                        </Badge>
                      )}
                      {programRequirements.length > 0 ? (
                        <Badge
                          variant="outline"
                          className="border-primary/50 text-primary"
                        >
                          {programRequirements.length} 项官方要求
                        </Badge>
                      ) : (
                        <Badge
                          variant="outline"
                          className="text-[var(--text-muted)]"
                        >
                          暂无要求数据
                        </Badge>
                      )}
                    </div>
                    <MatchSummary assessment={assessment} />
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="outline"
                        onClick={() => setDetailProgram(program)}
                      >
                        <ListChecks />
                        申请要求
                      </Button>
                      <Button
                        variant={checked ? "secondary" : "outline"}
                        onClick={() => toggleCompare(program)}
                        disabled={!checked && selected.length >= 3}
                      >
                        <Scale />
                        {checked ? "移出对比" : "加入对比"}
                      </Button>
                      <Button
                        variant="outline"
                        onClick={() => setEvidenceProgram(program)}
                      >
                        <FileSearch />
                        查看证据
                      </Button>
                      <Button
                        onClick={() => addApplication.mutate(program.id)}
                        disabled={addApplication.isPending}
                      >
                        <Plus />
                        加入申请计划
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              )
            })}
          </div>
        )}
      </section>

      <RequirementsDrawer
        program={detailProgram}
        cycle={cycle}
        requirements={detailProgram ? requirementsFor(detailProgram.id) : []}
        evidence={detailEvidence.data?.data ?? []}
        assessment={assessProgram(
          profile.data,
          detailProgram ? requirementsFor(detailProgram.id) : [],
        )}
        onOpenChange={(open) => !open && setDetailProgram(null)}
      />

      <EvidenceDrawer
        program={evidenceProgram}
        evidence={evidence.data?.data ?? []}
        loading={evidence.isLoading}
        onOpenChange={(open) => !open && setEvidenceProgram(null)}
      />
    </div>
  )
}

function RequirementsDrawer({
  program,
  cycle,
  requirements,
  evidence,
  assessment,
  onOpenChange,
}: {
  program: ProgramWithUniversityPublic | null
  cycle: string
  requirements: RequirementPublic[]
  evidence: EvidencePublic[]
  assessment: ReturnType<typeof assessProgram>
  onOpenChange: (open: boolean) => void
}) {
  const sourceOf = (requirement: RequirementPublic) =>
    evidence.find((item) => item.id === requirement.published_evidence_id)

  return (
    <Sheet open={Boolean(program)} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle>{program?.name}</SheetTitle>
          <SheetDescription>
            {program?.university.name} · {cycle} 申请季
          </SheetDescription>
        </SheetHeader>
        <div className="space-y-4 px-4 pb-6">
          <div className="flex flex-wrap gap-2">
            {program?.field_tags.map((tag) => (
              <Badge key={tag} variant="outline">
                {tag}
              </Badge>
            ))}
            {program?.duration_months ? (
              <Badge variant="outline">{program.duration_months} 个月</Badge>
            ) : null}
            <Badge
              className={`fit-badge ${assessment.group === "reach" ? "fit-reach" : assessment.group === "target" ? "fit-match" : assessment.group === "safer" ? "fit-safe" : ""}`}
            >
              {matchGroupLabels[assessment.group]}
            </Badge>
          </div>

          <MatchSummary assessment={assessment} />

          <div className="space-y-2">
            <p className="text-xs text-[var(--text-muted)]">
              申请要求（每项均可追溯到官网原始来源）
            </p>
            {requirements.length === 0 ? (
              <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
                该项目在 {cycle}{" "}
                申请季暂无已发布的要求。你可以在智能助手中询问，
                它会尝试实时读取学校官网。
              </p>
            ) : (
              <ul className="divide-y rounded-lg border">
                {requirements.map((item) => {
                  const source = sourceOf(item)
                  return (
                    <li key={item.id} className="space-y-1.5 p-3">
                      <div className="flex items-start justify-between gap-3">
                        <span className="text-sm text-muted-foreground">
                          {requirementLabels[item.field_name]}
                        </span>
                        {item.status === "conflict_pending" ? (
                          <Badge variant="destructive">待核实</Badge>
                        ) : (
                          <Badge variant="secondary">已发布</Badge>
                        )}
                      </div>
                      <p className="text-sm font-medium">
                        {formatRequirementValue(item)}
                      </p>
                      {source ? (
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                          <span>
                            采集于{" "}
                            {new Date(source.captured_at).toLocaleDateString(
                              "zh-CN",
                            )}
                          </span>
                          <a
                            className="inline-flex items-center gap-1 text-primary hover:underline"
                            href={source.source_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            官网来源
                            <ExternalLink className="size-3" />
                          </a>
                        </div>
                      ) : null}
                    </li>
                  )
                })}
              </ul>
            )}
          </div>

          {requirements.some((item) => item.status === "conflict_pending") ? (
            <p className="rounded-lg border border-amber-300 bg-amber-50/60 p-3 text-xs dark:border-amber-900/60 dark:bg-amber-950/20">
              标「待核实」的项，是学校自己不同页面写的不一样，还没确认，先别当准信。
            </p>
          ) : null}
        </div>
      </SheetContent>
    </Sheet>
  )
}

function MatchSummary({
  assessment,
}: {
  assessment: ReturnType<typeof assessProgram>
}) {
  return (
    <div className="rounded-lg bg-muted/50 p-3 text-sm">
      <p className="font-medium">匹配依据</p>
      {assessment.reasons.length === 0 && assessment.gaps.length === 0 ? (
        <p className="mt-1 text-muted-foreground">暂无可比较数据</p>
      ) : (
        <>
          <ul className="mt-1 space-y-1 text-muted-foreground">
            {assessment.reasons.slice(0, 2).map((reason) => (
              <li key={reason}>✓ {reason}</li>
            ))}
          </ul>
          {assessment.gaps.length > 0 && (
            <div className="mt-2">
              <p className="font-medium text-destructive">需要补足</p>
              <ul className="mt-1 space-y-1 text-muted-foreground">
                {assessment.gaps.slice(0, 2).map((gap) => (
                  <li key={gap}>· {gap}</li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  )
}

const LABEL_COLUMN_DEFAULT = 108
const LABEL_COLUMN_MIN = 72
const PROGRAM_COLUMN_MIN = 96

function Comparison({
  programs,
  requirements,
  onRemove,
}: {
  programs: ProgramWithUniversityPublic[]
  requirements: RequirementPublic[][]
  onRemove: (program: ProgramWithUniversityPublic) => void
}) {
  const fields = useMemo<RequirementPublic["field_name"][]>(
    () => Array.from(new Set(requirements.flat().map((i) => i.field_name))),
    [requirements],
  )
  // 一条要求都没有的项目，对比表看起来会像什么都没比。
  const withoutData = programs.filter((_, i) => requirements[i].length === 0)

  const { gridTemplate, startResize } = useResizableColumns(programs.length)

  const row = (key: string, label: string, values: (string | null)[]) => (
    <div
      key={key}
      className="grid items-start border-t border-[var(--border-subtle)]"
      style={{ gridTemplateColumns: gridTemplate }}
    >
      <div className="px-3 py-3 text-xs leading-relaxed text-[var(--text-muted)]">
        {label}
      </div>
      {values.map((value, index) => (
        <div
          key={programs[index].id}
          className={`min-w-0 px-3 py-3 text-sm leading-relaxed ${
            value === null
              ? "text-[var(--text-muted)]"
              : "whitespace-pre-line break-words"
          }`}
        >
          {value ?? "—"}
        </div>
      ))}
    </div>
  )

  return (
    <Card className="border-primary bg-[var(--primary-muted)]">
      <CardHeader className="pb-3">
        <div className="flex items-baseline justify-between gap-3">
          <CardTitle>项目对比</CardTitle>
          <CardDescription className="text-[11px]">
            拖动表头之间的分隔线可调整列宽
          </CardDescription>
        </div>
        {withoutData.length > 0 ? (
          <p className="mt-2 rounded-md border border-amber-300/70 bg-amber-50/60 p-2.5 text-xs leading-relaxed dark:border-amber-900/60 dark:bg-amber-950/20">
            {withoutData.map((program) => programTitle(program)).join("、")}
            {withoutData.length === programs.length
              ? " 尚未收录官方要求，因此下表只能比较地区。"
              : " 尚未收录官方要求，其对应列为空。"}
            可以在智能助手中直接询问这些项目，它会尝试实时读取学校官网。
          </p>
        ) : null}
      </CardHeader>

      <CardContent className="pt-0">
        <div className="overflow-hidden rounded-lg border border-[var(--border-subtle)]">
          <div
            className="grid items-stretch"
            style={{ gridTemplateColumns: gridTemplate }}
          >
            <div className="px-3 py-3 text-[11px] text-[var(--text-muted)]">
              对比项
            </div>
            {programs.map((program, index) => (
              <div key={program.id} className="relative min-w-0">
                <div className="px-3 py-3 pr-8">
                  <p
                    className="text-sm font-medium leading-snug"
                    title={program.name}
                  >
                    {program.name}
                  </p>
                  <p className="mt-0.5 text-[11px] text-[var(--text-muted)]">
                    {program.university.short_name}
                  </p>
                </div>
                <button
                  type="button"
                  aria-label={`移除 ${program.name}`}
                  onClick={() => onRemove(program)}
                  className="absolute right-1.5 top-2 rounded p-0.5 text-[var(--text-muted)] transition-colors hover:bg-[var(--primary-muted)] hover:text-foreground"
                >
                  <X className="size-3.5" />
                </button>
                {index < programs.length - 1 ? (
                  <button
                    type="button"
                    aria-label="调整列宽"
                    onPointerDown={(event) => startResize(index, event)}
                    className="absolute -right-1 top-0 h-full w-2 cursor-col-resize border-0 bg-transparent p-0 transition-colors hover:bg-primary/25"
                  />
                ) : null}
                {index === 0 ? (
                  <button
                    type="button"
                    aria-label="调整对比项列宽"
                    onPointerDown={(event) => startResize(-1, event)}
                    className="absolute -left-1 top-0 h-full w-2 cursor-col-resize border-0 bg-transparent p-0 transition-colors hover:bg-primary/25"
                  />
                ) : null}
              </div>
            ))}
          </div>

          {row(
            "region",
            "地区",
            programs.map((program) => regionLabels[program.university.region]),
          )}
          {fields.map((field) =>
            row(
              field,
              requirementLabels[field],
              requirements.map((items) => {
                const item = items.find((c) => c.field_name === field)
                return item ? formatComparisonValue(item) : null
              }),
            ),
          )}
        </div>
        <p className="mt-2 text-[11px] text-[var(--text-muted)]">
          数据来自当前申请季的已发布要求，「—」表示官网没写或还没收录
        </p>
      </CardContent>
    </Card>
  )
}

/** 列宽以像素保存，第一列是标签列，其余对应各个项目。 */
function useResizableColumns(programCount: number) {
  const [labelWidth, setLabelWidth] = useState(LABEL_COLUMN_DEFAULT)
  const [pixelWidths, setPixelWidths] = useState<number[] | null>(null)

  // 增减项目时回到等分。
  const [lastCount, setLastCount] = useState(programCount)
  if (lastCount !== programCount) {
    setLastCount(programCount)
    setPixelWidths(null)
  }

  const gridTemplate =
    pixelWidths === null
      ? `${labelWidth}px repeat(${programCount}, minmax(0, 1fr))`
      : `${labelWidth}px ${pixelWidths.map((width) => `${width}px`).join(" ")}`

  const startResize = (
    boundaryIndex: number,
    event: React.PointerEvent<HTMLElement>,
  ) => {
    event.preventDefault()
    const header = event.currentTarget.parentElement?.parentElement
    if (!header) return

    // 先把当前宽度固化成像素，才能精确增减。
    const columns = Array.from(header.children).slice(1) as HTMLElement[]
    const measured = columns.map(
      (column) => column.getBoundingClientRect().width,
    )
    const startX = event.clientX
    const startWidths = pixelWidths ?? measured
    const startLabel = labelWidth

    const move = (moveEvent: PointerEvent) => {
      const delta = moveEvent.clientX - startX
      if (boundaryIndex < 0) {
        setLabelWidth(Math.max(LABEL_COLUMN_MIN, startLabel + delta))
        return
      }
      const next = [...startWidths]
      const left = startWidths[boundaryIndex]
      const right = startWidths[boundaryIndex + 1]
      if (right === undefined) return
      const clamped = Math.max(
        PROGRAM_COLUMN_MIN - left,
        Math.min(right - PROGRAM_COLUMN_MIN, delta),
      )
      next[boundaryIndex] = left + clamped
      next[boundaryIndex + 1] = right - clamped
      setPixelWidths(next)
    }

    const stop = () => {
      window.removeEventListener("pointermove", move)
      window.removeEventListener("pointerup", stop)
    }
    window.addEventListener("pointermove", move)
    window.addEventListener("pointerup", stop)
  }

  return { gridTemplate, startResize }
}

function EvidenceDrawer({
  program,
  evidence,
  loading,
  onOpenChange,
}: {
  program: ProgramWithUniversityPublic | null
  evidence: EvidencePublic[]
  loading: boolean
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Sheet open={Boolean(program)} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle>官网证据</SheetTitle>
          <SheetDescription>
            {program ? programTitle(program) : ""} · 可追溯的字段来源
          </SheetDescription>
        </SheetHeader>
        <div className="space-y-3 px-4 pb-6">
          {loading ? (
            <Skeleton className="h-40 w-full" />
          ) : evidence.length === 0 ? (
            <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
              当前申请季暂无证据记录。
            </p>
          ) : (
            evidence.map((item) => (
              <Card key={item.id} className="gap-3 py-4">
                <CardContent className="space-y-2 px-4">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">
                      {requirementLabels[item.field_name]}
                    </span>
                    <Badge
                      variant={
                        item.status === "conflicted"
                          ? "destructive"
                          : "secondary"
                      }
                    >
                      {evidenceStatusLabels[item.status]}
                    </Badge>
                  </div>
                  <p className="text-sm">{formatRequirementValue(item)}</p>
                  <p className="text-xs text-muted-foreground">
                    抓取时间：
                    {new Date(item.captured_at).toLocaleString("zh-CN")}
                  </p>
                  <a
                    className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
                    href={item.source_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    打开官网来源
                    <ExternalLink className="size-3" />
                  </a>
                </CardContent>
              </Card>
            ))
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
