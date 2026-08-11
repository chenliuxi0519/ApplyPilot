import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { ExternalLink, FileSearch, Plus, Scale, Search, X } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import {
  ApplicationsService,
  type EvidencePublic,
  ProfileService,
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  assessProgram,
  evidenceStatusLabels,
  formatRequirementValue,
  matchGroupLabels,
  programTitle,
  regionLabels,
  requirementLabels,
} from "./presentation"

export function ProgramsPage() {
  const queryClient = useQueryClient()
  const [query, setQuery] = useState("")
  const [submittedQuery, setSubmittedQuery] = useState("")
  const [region, setRegion] = useState("all")
  const [cycle, setCycle] = useState("2026/27")
  const [selected, setSelected] = useState<ProgramWithUniversityPublic[]>([])
  const [evidenceProgram, setEvidenceProgram] =
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
  const profile = useQuery({
    queryKey: ["profile"],
    queryFn: () => ProfileService.readProfileMe(),
    retry: false,
  })
  const allRequirements = useQueries({
    queries: (programs.data?.data ?? []).map((program) => ({
      queryKey: ["requirements", program.id, cycle],
      queryFn: () =>
        ProgramsService.readProgramRequirements({
          programId: program.id,
          applicationCycle: cycle,
        }),
    })),
  })
  const requirementsFor = (programId: string) =>
    allRequirements[
      (programs.data?.data ?? []).findIndex((item) => item.id === programId)
    ]?.data?.data ?? []
  const evidence = useQuery({
    queryKey: ["evidence", evidenceProgram?.id, cycle],
    queryFn: () =>
      ProgramsService.readProgramEvidence({
        programId: evidenceProgram!.id,
        applicationCycle: cycle,
      }),
    enabled: Boolean(evidenceProgram),
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
          requirements={selected.map((program) => requirementsFor(program.id))}
          onRemove={toggleCompare}
        />
      )}

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-xs text-[var(--text-muted)]">项目列表</h2>
          <span className="font-mono text-[11px] text-[var(--text-muted)]">
            找到 {programs.data?.count ?? 0} 个项目 · 最多对比 3 个
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
              const assessment = assessProgram(
                profile.data,
                requirementsFor(program.id),
              )
              return (
                <Card
                  key={program.id}
                  className={`lift-card overflow-hidden rounded-[11px] transition-all duration-150 hover:-translate-y-0.5 hover:border-primary hover:shadow-md ${checked ? "border-primary shadow-[0_0_0_1px_var(--primary)]" : ""}`}
                >
                  <CardHeader>
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <CardTitle>{program.name}</CardTitle>
                        <CardDescription className="mt-1">
                          {program.university.name}（
                          {program.university.short_name}）
                        </CardDescription>
                      </div>
                      <div className="flex flex-col items-end gap-2">
                        <Badge variant="secondary">
                          {regionLabels[program.university.region]}
                        </Badge>
                        <Badge className={`fit-badge ${assessment.group === "reach" ? "fit-reach" : assessment.group === "target" ? "fit-match" : assessment.group === "safer" ? "fit-safe" : ""}`}>
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
                    </div>
                    <MatchSummary assessment={assessment} />
                    <div className="flex flex-wrap gap-2">
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

      <EvidenceDrawer
        program={evidenceProgram}
        evidence={evidence.data?.data ?? []}
        loading={evidence.isLoading}
        onOpenChange={(open) => !open && setEvidenceProgram(null)}
      />
    </div>
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

function Comparison({
  programs,
  requirements,
  onRemove,
}: {
  programs: ProgramWithUniversityPublic[]
  requirements: RequirementPublic[][]
  onRemove: (program: ProgramWithUniversityPublic) => void
}) {
  const fields = Array.from(
    new Set(requirements.flat().map((item) => item.field_name)),
  )
  return (
    <Card className="border-primary bg-[var(--primary-muted)]">
      <CardHeader>
        <CardTitle>项目对比</CardTitle>
        <CardDescription>
          所有数值均来自当前申请季的已发布要求。
        </CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>对比项</TableHead>
              {programs.map((program) => (
                <TableHead key={program.id} className="min-w-56">
                  <div className="flex items-center justify-between gap-2">
                    <span>{programTitle(program)}</span>
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label={`移除 ${program.name}`}
                      onClick={() => onRemove(program)}
                    >
                      <X />
                    </Button>
                  </div>
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow>
              <TableCell>地区</TableCell>
              {programs.map((program) => (
                <TableCell key={program.id}>
                  {regionLabels[program.university.region]}
                </TableCell>
              ))}
            </TableRow>
            {fields.map((field) => (
              <TableRow key={field}>
                <TableCell className="font-medium">
                  {requirementLabels[field]}
                </TableCell>
                {requirements.map((items, index) => {
                  const item = items.find(
                    (candidate) => candidate.field_name === field,
                  )
                  return (
                    <TableCell key={programs[index].id}>
                      {item ? formatRequirementValue(item) : "暂无数据"}
                    </TableCell>
                  )
                })}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
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
