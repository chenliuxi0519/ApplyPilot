import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Save } from "lucide-react"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { ProfileService, type UserProfileUpdate } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { useProfile } from "@/hooks/useProfile"

type FormState = Record<keyof UserProfileUpdate, string>

const emptyForm: FormState = {
  undergraduate_university: "",
  undergraduate_major: "",
  gpa_value: "",
  gpa_scale: "",
  ielts_overall: "",
  work_experience_years: "",
  experience_summary: "",
  budget_cny: "",
  target_regions: "",
  target_fields: "",
  career_goal: "",
}

export function ProfilePage() {
  const queryClient = useQueryClient()
  const [form, setForm] = useState(emptyForm)
  const [saved, setSaved] = useState(false)
  const profile = useProfile()

  useEffect(() => {
    if (!profile.data) return
    setForm({
      undergraduate_university: profile.data.undergraduate_university ?? "",
      undergraduate_major: profile.data.undergraduate_major ?? "",
      gpa_value: profile.data.gpa_value ?? "",
      gpa_scale: profile.data.gpa_scale ?? "",
      ielts_overall: profile.data.ielts_overall ?? "",
      work_experience_years: profile.data.work_experience_years ?? "",
      experience_summary: profile.data.experience_summary ?? "",
      budget_cny: profile.data.budget_cny?.toString() ?? "",
      target_regions: profile.data.target_regions.join("、"),
      target_fields: profile.data.target_fields.join("、"),
      career_goal: profile.data.career_goal ?? "",
    })
  }, [profile.data])

  const save = useMutation({
    mutationFn: () =>
      ProfileService.updateProfileMe({
        requestBody: {
          undergraduate_university: form.undergraduate_university || null,
          undergraduate_major: form.undergraduate_major || null,
          gpa_value: form.gpa_value || null,
          gpa_scale: form.gpa_scale || null,
          ielts_overall: form.ielts_overall || null,
          work_experience_years: form.work_experience_years || null,
          experience_summary: form.experience_summary || null,
          budget_cny: form.budget_cny ? Number(form.budget_cny) : null,
          target_regions: splitList(form.target_regions),
          target_fields: splitList(form.target_fields),
          career_goal: form.career_goal || null,
        },
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["profile"], data)
      toast.success("个人档案已保存")
      setSaved(true)
      window.setTimeout(() => setSaved(false), 1500)
    },
    onError: () => toast.error("保存失败，请检查 GPA 和语言成绩格式"),
  })

  const set =
    (key: keyof FormState) =>
    (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setForm((current) => ({ ...current, [key]: event.target.value }))

  if (profile.isLoading) return <Skeleton className="h-96 w-full" />
  const profileMissing =
    profile.isError && (profile.error as { status?: number })?.status === 404
  if (profile.isError && !profileMissing)
    return (
      <div className="rounded-xl border border-destructive/40 p-6">
        <p className="text-destructive">档案加载失败，请检查网络后重试。</p>
        <Button
          className="mt-4"
          variant="outline"
          onClick={() => profile.refetch()}
        >
          重新加载
        </Button>
      </div>
    )

  const completeness = Math.round(
    (Object.values(form).filter((value) => value.trim()).length /
      Object.keys(form).length) *
      100,
  )

  return (
    <div className="space-y-[14px]">
      <div className="mb-6 flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="page-title">个人档案</h1>
          <p className="page-subtitle">
            {profileMissing
              ? "填写以下信息建立档案；保存后会用于项目匹配。"
              : "这些信息会用于项目匹配和风险评估，随时可以修改。"}
          </p>
        </div>
        <div className="lift-card flex items-center gap-3 rounded-[11px] border bg-[var(--surface)] px-[18px] py-3">
          <div className="relative size-[52px]">
            <svg
              className="size-[52px] -rotate-90"
              viewBox="0 0 52 52"
              aria-hidden="true"
            >
              <circle
                cx="26"
                cy="26"
                r="21"
                fill="none"
                stroke="var(--border)"
                strokeWidth="4"
              />
              <circle
                cx="26"
                cy="26"
                r="21"
                fill="none"
                stroke="var(--primary)"
                strokeWidth="4"
                strokeLinecap="round"
                strokeDasharray={`${completeness * 1.319} 132`}
              />
            </svg>
            <span className="absolute inset-0 flex items-center justify-center font-mono text-[13px]">
              {completeness}%
            </span>
          </div>
          <div>
            <p className="text-xs text-[var(--text-secondary)]">档案完整度</p>
            <p className="text-[11px] text-[var(--text-muted)]">
              继续填写以提升匹配精度
            </p>
          </div>
        </div>
      </div>
      <Card className="section-card">
        <CardHeader>
          <CardTitle>经历与能力</CardTitle>
          <CardDescription>
            记录实习、工作、科研和项目经历，帮助判断背景匹配度。
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-5 md:grid-cols-2">
          <Field label="工作或实习年限">
            <Input
              inputMode="decimal"
              value={form.work_experience_years}
              onChange={set("work_experience_years")}
              placeholder="例如：1.5"
            />
          </Field>
          <div className="space-y-2 md:col-span-2">
            <Label htmlFor="experience-summary">经历摘要</Label>
            <Textarea
              id="experience-summary"
              value={form.experience_summary}
              onChange={set("experience_summary")}
              placeholder="概述实习、科研、竞赛、论文或重要项目"
              rows={5}
            />
          </div>
        </CardContent>
      </Card>
      <Card className="section-card">
        <CardHeader>
          <CardTitle>教育与成绩</CardTitle>
          <CardDescription>
            填写真实信息，系统不会依赖聊天记录猜测。
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-5 md:grid-cols-2">
          <Field label="本科院校">
            <Input
              value={form.undergraduate_university}
              onChange={set("undergraduate_university")}
              placeholder="例如：北京邮电大学"
            />
          </Field>
          <Field label="本科专业">
            <Input
              value={form.undergraduate_major}
              onChange={set("undergraduate_major")}
              placeholder="例如：计算机科学"
            />
          </Field>
          <Field label="GPA">
            <Input
              inputMode="decimal"
              value={form.gpa_value}
              onChange={set("gpa_value")}
              placeholder="例如：3.6"
            />
          </Field>
          <Field label="GPA 满分">
            <Input
              inputMode="decimal"
              value={form.gpa_scale}
              onChange={set("gpa_scale")}
              placeholder="例如：4.0"
            />
          </Field>
          <Field label="雅思总分">
            <Input
              inputMode="decimal"
              value={form.ielts_overall}
              onChange={set("ielts_overall")}
              placeholder="例如：7.0"
            />
          </Field>
          <Field label="预算（人民币）">
            <Input
              inputMode="numeric"
              value={form.budget_cny}
              onChange={set("budget_cny")}
              placeholder="例如：400000"
            />
          </Field>
        </CardContent>
      </Card>
      <Card className="section-card">
        <CardHeader>
          <CardTitle>目标与方向</CardTitle>
          <CardDescription>多个地区或方向可用逗号、顿号分隔。</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-5 md:grid-cols-2">
          <Field label="目标地区">
            <Input
              value={form.target_regions}
              onChange={set("target_regions")}
              placeholder="中国香港、新加坡、英国"
            />
          </Field>
          <Field label="目标专业">
            <Input
              value={form.target_fields}
              onChange={set("target_fields")}
              placeholder="人工智能、计算机科学"
            />
          </Field>
          <div className="space-y-2 md:col-span-2">
            <Label>职业目标</Label>
            <Textarea
              value={form.career_goal}
              onChange={set("career_goal")}
              placeholder="描述你希望从事的方向"
              rows={5}
            />
          </div>
        </CardContent>
      </Card>
      <div className="flex justify-end">
        <Button
          className="rounded-lg px-[26px]"
          onClick={() => save.mutate()}
          disabled={save.isPending}
        >
          <Save />
          {save.isPending ? "保存中…" : saved ? "已保存 ✓" : "保存档案"}
        </Button>
      </div>
    </div>
  )
}

function Field({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <Label className="flex flex-col items-stretch gap-[5px]">
      <span className="text-[10px] font-bold uppercase tracking-[.07em] text-[var(--text-muted)]">
        {label}
      </span>
      {children}
    </Label>
  )
}

function splitList(value: string) {
  return value
    .split(/[，,、]/)
    .map((item) => item.trim())
    .filter(Boolean)
}
