import { AlertTriangle, Check, ChevronDown, X } from "lucide-react"
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import type { ComparisonEvent, ProgramFit } from "../types"

const BAND_META = {
  reach: {
    title: "冲刺",
    subtitle: "个人条件距离要求还有缺口",
    className:
      "border-rose-200 bg-rose-50/60 dark:border-rose-900/60 dark:bg-rose-950/20",
    badge: "bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300",
  },
  target: {
    title: "匹配",
    subtitle: "达到要求但富余不多",
    className:
      "border-amber-200 bg-amber-50/40 dark:border-amber-900/60 dark:bg-amber-950/20",
    badge:
      "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
  },
  safer: {
    title: "稳妥",
    subtitle: "个人条件明显高于要求",
    className:
      "border-emerald-200 bg-emerald-50/40 dark:border-emerald-900/60 dark:bg-emerald-950/20",
    badge:
      "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
  },
  unknown: {
    title: "信息不足",
    subtitle: "缺少个人档案或项目公开的可比字段",
    className:
      "border-slate-200 bg-slate-50/40 dark:border-slate-800/60 dark:bg-slate-950/20",
    badge:
      "bg-slate-100 text-slate-700 dark:bg-slate-800/40 dark:text-slate-300",
  },
} as const

const FIELD_LABELS: Record<string, string> = {
  ielts_overall: "雅思",
  ielts_min_band: "雅思单项",
  toefl_overall: "托福",
  gpa_min: "最低 GPA",
  gpa_scale: "GPA 制式",
  work_experience_years: "工作经验",
  application_deadline: "申请截止",
  tuition: "学费",
  degree_background: "学位背景",
  prerequisite_courses: "先修课程",
}

const label = (field: string) => FIELD_LABELS[field] ?? field

interface ComparisonCardProps {
  card: ComparisonEvent
}

export function ComparisonCard({ card }: ComparisonCardProps) {
  const buckets: Record<ProgramFit["band"], ProgramFit[]> = {
    reach: [],
    target: [],
    safer: [],
    unknown: [],
  }
  for (const fit of card.fits) buckets[fit.band].push(fit)

  return (
    <div className="space-y-3" data-testid="comparison-card">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          共对比 {card.count} 个项目
        </p>
        {card.profileMissing.length > 0 ? (
          <p className="text-xs text-muted-foreground">
            缺少档案字段：
            {card.profileMissing.map((name) => label(name)).join("、")}
          </p>
        ) : null}
      </div>

      {(["reach", "target", "safer", "unknown"] as const).map((band) =>
        buckets[band].length === 0 ? null : (
          <Bucket key={band} band={band} fits={buckets[band]} />
        ),
      )}
    </div>
  )
}

function Bucket({
  band,
  fits,
}: {
  band: ProgramFit["band"]
  fits: ProgramFit[]
}) {
  const meta = BAND_META[band]
  return (
    <div className={`rounded-lg border p-3 ${meta.className}`}>
      <div className="flex items-baseline gap-2">
        <span
          className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${meta.badge}`}
        >
          {meta.title} · {fits.length}
        </span>
        <span className="text-xs text-muted-foreground">{meta.subtitle}</span>
      </div>
      <ul className="mt-2 space-y-2">
        {fits.map((fit) => (
          <FitRow key={fit.program_id} fit={fit} />
        ))}
      </ul>
    </div>
  )
}

function FitRow({ fit }: { fit: ProgramFit }) {
  const [open, setOpen] = useState(false)
  const hasDetail =
    fit.gaps.length + fit.strengths.length + fit.context.length > 0

  return (
    <li className="rounded-md border bg-card">
      <button
        type="button"
        onClick={() => hasDetail && setOpen((current) => !current)}
        disabled={!hasDetail}
        className="flex w-full items-start justify-between gap-3 p-2.5 text-left"
      >
        <div className="min-w-0">
          <p className="text-xs font-medium text-muted-foreground">
            {fit.university}
          </p>
          <p className="text-sm font-medium leading-snug">{fit.name}</p>
          <div className="mt-1 flex flex-wrap items-center gap-1">
            {fit.application_cycle ? (
              <Badge variant="secondary" className="font-normal">
                {fit.application_cycle}
              </Badge>
            ) : null}
            {fit.disputed ? (
              <span className="inline-flex items-center gap-1 text-xs text-amber-600 dark:text-amber-500">
                <AlertTriangle className="size-3" />
                含存疑要求
              </span>
            ) : null}
          </div>
        </div>
        {hasDetail ? (
          <ChevronDown
            className={`mt-1 size-4 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`}
          />
        ) : null}
      </button>

      {open ? (
        <div className="space-y-2 border-t px-2.5 py-2 text-xs">
          {fit.gaps.length > 0 ? (
            <FactorList
              title="需要补齐"
              factors={fit.gaps}
              icon={<X className="size-3 text-rose-600 dark:text-rose-400" />}
            />
          ) : null}
          {fit.strengths.length > 0 ? (
            <FactorList
              title="已达要求"
              factors={fit.strengths}
              icon={
                <Check className="size-3 text-emerald-600 dark:text-emerald-400" />
              }
            />
          ) : null}
          {fit.context.length > 0 ? (
            <div>
              <p className="mb-1 font-medium text-muted-foreground">其他信息</p>
              <dl className="space-y-1">
                {fit.context.map((row) => (
                  <div
                    key={row.field}
                    className="flex items-start justify-between gap-3"
                  >
                    <dt className="shrink-0 text-muted-foreground">
                      {label(row.field)}
                    </dt>
                    <dd className="text-right">{row.value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ) : null}
        </div>
      ) : null}
    </li>
  )
}

function FactorList({
  title,
  factors,
  icon,
}: {
  title: string
  factors: { field: string; required: string; have: string; delta: string }[]
  icon: React.ReactNode
}) {
  return (
    <div>
      <p className="mb-1 font-medium text-muted-foreground">{title}</p>
      <ul className="space-y-0.5">
        {factors.map((factor) => (
          <li key={factor.field} className="flex items-center gap-1.5">
            {icon}
            <span>
              {label(factor.field)}：要求 {factor.required}，我方 {factor.have}
            </span>
            <span className="ml-1 text-muted-foreground">({factor.delta})</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
