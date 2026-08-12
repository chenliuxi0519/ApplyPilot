import { useQueries, useQuery } from "@tanstack/react-query"
import { ExternalLink, FileCheck2, Search } from "lucide-react"
import { useMemo, useState } from "react"

import {
  type EvidencePublic,
  ProgramsService,
  type ProgramWithUniversityPublic,
} from "@/client"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
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
  evidenceStatusLabels,
  formatRequirementValue,
  programTitle,
  requirementLabels,
} from "./presentation"

type EvidenceRow = {
  evidence: EvidencePublic
  program: ProgramWithUniversityPublic
}

export function EvidencePage() {
  const [query, setQuery] = useState("")
  const [status, setStatus] = useState("all")
  const [cycle, setCycle] = useState("2026/27")
  const [detail, setDetail] = useState<EvidenceRow | null>(null)
  const programs = useQuery({
    queryKey: ["programs", "evidence-index"],
    queryFn: () => ProgramsService.searchPrograms({ limit: 200 }),
  })
  const evidenceQueries = useQueries({
    queries: (programs.data?.data ?? []).map((program) => ({
      queryKey: ["evidence", program.id, cycle],
      queryFn: () =>
        ProgramsService.readProgramEvidence({
          programId: program.id,
          applicationCycle: cycle,
        }),
    })),
  })
  const rows = useMemo(
    () =>
      (programs.data?.data ?? [])
        .flatMap((program, index) =>
          (evidenceQueries[index]?.data?.data ?? []).map((evidence) => ({
            evidence,
            program,
          })),
        )
        .filter(({ evidence, program }) => {
          const needle = query.trim().toLocaleLowerCase()
          // 学校简称（HKU、NTU）也要能搜到。
          const haystack = [
            program.name,
            program.university.name,
            program.university.short_name,
            requirementLabels[evidence.field_name],
            formatRequirementValue(evidence),
            evidence.source_url,
            ...program.field_tags,
          ]
            .join(" ")
            .toLocaleLowerCase()
          const matchesQuery = !needle || haystack.includes(needle)
          return (
            matchesQuery && (status === "all" || evidence.status === status)
          )
        }),
    [programs.data, evidenceQueries, query, status],
  )

  const loading =
    programs.isLoading || evidenceQueries.some((item) => item.isLoading)
  const failed =
    programs.isError || evidenceQueries.some((item) => item.isError)
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">证据库</h1>
        <p className="text-muted-foreground">
          集中查看关键要求的官网链接、抓取时间与验证状态。
        </p>
      </div>
      <Card>
        <CardContent className="grid gap-3 pt-0 md:grid-cols-[1fr_180px_140px]">
          <div className="relative">
            <Search className="absolute left-3 top-2.5 size-4 text-muted-foreground" />
            <Input
              className="pl-9"
              aria-label="搜索证据"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索学校、项目或要求字段"
            />
          </div>
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger aria-label="证据状态">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部状态</SelectItem>
              {Object.entries(evidenceStatusLabels).map(([value, label]) => (
                <SelectItem key={value} value={value}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input
            aria-label="申请季"
            value={cycle}
            onChange={(event) => setCycle(event.target.value)}
          />
        </CardContent>
      </Card>
      {loading ? (
        <Skeleton className="h-72 w-full" />
      ) : failed ? (
        <div className="rounded-xl border border-destructive/40 p-8 text-center">
          <p className="font-medium text-destructive">部分官网证据加载失败</p>
          <p className="mt-1 text-sm text-muted-foreground">
            请检查网络后刷新页面重试。
          </p>
        </div>
      ) : rows.length === 0 ? (
        <div className="rounded-xl border border-dashed p-12 text-center">
          <FileCheck2 className="mx-auto size-8 text-muted-foreground" />
          <p className="mt-3 font-medium">没有符合条件的证据</p>
          <p className="mt-1 text-sm text-muted-foreground">
            可以调整搜索条件、状态或申请季。
          </p>
        </div>
      ) : (
        <div className="grid gap-3">
          <p className="font-mono text-[11px] text-[var(--text-muted)]">
            共 {rows.length} 条证据 · 点击任意一条查看完整信息
          </p>
          {rows.map(({ evidence, program }) => (
            <Card
              key={evidence.id}
              className="cursor-pointer gap-3 py-4 transition-colors hover:border-primary"
              onClick={() => setDetail({ evidence, program })}
            >
              <CardContent className="grid gap-3 px-4 md:grid-cols-[1.2fr_1fr_auto] md:items-center">
                <div>
                  <p className="font-medium">{programTitle(program)}</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {requirementLabels[evidence.field_name]} ·{" "}
                    {formatRequirementValue(evidence)}
                  </p>
                </div>
                <div className="text-sm text-muted-foreground">
                  <p>
                    抓取：
                    {new Date(evidence.captured_at).toLocaleString("zh-CN")}
                  </p>
                  <p>来源类型：{sourceTypeLabel(evidence.source_type)}</p>
                </div>
                <div className="flex items-center gap-3">
                  <Badge
                    variant={
                      evidence.status === "conflicted"
                        ? "destructive"
                        : "secondary"
                    }
                  >
                    {evidenceStatusLabels[evidence.status]}
                  </Badge>
                  <a
                    className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
                    href={evidence.source_url}
                    target="_blank"
                    rel="noreferrer"
                    onClick={(event) => event.stopPropagation()}
                  >
                    官网
                    <ExternalLink className="size-3" />
                  </a>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Sheet
        open={detail !== null}
        onOpenChange={(open) => !open && setDetail(null)}
      >
        <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
          <SheetHeader>
            <SheetTitle>
              {detail ? requirementLabels[detail.evidence.field_name] : ""}
            </SheetTitle>
            <SheetDescription>
              {detail ? programTitle(detail.program) : ""}
            </SheetDescription>
          </SheetHeader>
          {detail ? (
            <div className="space-y-4 px-4 pb-6">
              <div className="rounded-lg border p-4">
                <p className="text-xs text-[var(--text-muted)]">采集到的数值</p>
                <p className="mt-1 text-lg font-medium">
                  {formatRequirementValue(detail.evidence)}
                </p>
              </div>

              <dl className="divide-y rounded-lg border text-sm">
                {[
                  ["验证状态", evidenceStatusLabels[detail.evidence.status]],
                  ["申请季", detail.evidence.application_cycle],
                  ["来源类型", sourceTypeLabel(detail.evidence.source_type)],
                  [
                    "采集时间",
                    new Date(detail.evidence.captured_at).toLocaleString(
                      "zh-CN",
                    ),
                  ],
                  ["所属学校", detail.program.university.name],
                  ["项目", detail.program.name],
                ].map(([label, value]) => (
                  <div
                    key={label}
                    className="flex items-start justify-between gap-4 px-3 py-2"
                  >
                    <dt className="shrink-0 text-muted-foreground">{label}</dt>
                    <dd className="text-right">{value}</dd>
                  </div>
                ))}
              </dl>

              <div className="space-y-1.5">
                <p className="text-xs text-[var(--text-muted)]">官网来源地址</p>
                <a
                  className="inline-flex items-start gap-1 break-all text-sm text-primary hover:underline"
                  href={detail.evidence.source_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  {detail.evidence.source_url}
                  <ExternalLink className="mt-0.5 size-3 shrink-0" />
                </a>
              </div>

              {detail.evidence.status === "conflicted" ? (
                <p className="rounded-lg border border-amber-300 bg-amber-50/60 p-3 text-xs dark:border-amber-900/60 dark:bg-amber-950/20">
                  这条和当前已发布的值对不上，正在等人工复核，先别当准信。
                </p>
              ) : null}
            </div>
          ) : null}
        </SheetContent>
      </Sheet>
    </div>
  )
}

function sourceTypeLabel(value: string) {
  return (
    (
      {
        program_page: "项目主页",
        admission_page: "招生页面",
        fees_page: "费用页面",
        university_english_requirement: "校级语言要求",
        official_pdf: "官方文件",
        official_faq: "官方问答",
        handbook: "课程手册",
      } as Record<string, string>
    )[value] ?? "官方来源"
  )
}
