import type { UserProfilePublic } from "@/client"
import { Badge } from "@/components/ui/badge"

const REGION_LABELS: Record<string, string> = {
  singapore: "新加坡",
  hong_kong: "中国香港",
  united_kingdom: "英国",
}

interface ProfileSummaryProps {
  profile: UserProfilePublic | null
}

export function ProfileSummary({ profile }: ProfileSummaryProps) {
  if (!profile) {
    return (
      <p className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
        还没有个人档案。告诉 ApplyPilot 你的背景信息，它会帮助你建立档案。
      </p>
    )
  }

  const gpa =
    profile.gpa_value && profile.gpa_scale
      ? `${profile.gpa_value} / ${profile.gpa_scale}`
      : null
  const targets = [...profile.target_regions, ...profile.target_fields]

  return (
    <div
      className="space-y-2 rounded-lg border bg-card p-3"
      data-testid="profile-summary"
    >
      {profile.undergraduate_university ? (
        <p className="text-sm font-medium leading-snug">
          {profile.undergraduate_university}
        </p>
      ) : null}
      {profile.undergraduate_major ? (
        <p className="text-xs text-muted-foreground">
          {profile.undergraduate_major}
        </p>
      ) : null}

      <dl className="space-y-1 text-xs">
        {gpa ? <Row label="GPA" value={gpa} /> : null}
        {profile.ielts_overall ? (
          <Row label="雅思" value={profile.ielts_overall} />
        ) : null}
        {profile.budget_cny !== null && profile.budget_cny !== undefined ? (
          <Row
            label="预算"
            value={`¥${profile.budget_cny.toLocaleString("zh-CN")}`}
          />
        ) : null}
        {profile.career_goal ? (
          <Row label="职业目标" value={profile.career_goal} />
        ) : null}
      </dl>

      {targets.length > 0 ? (
        <div className="flex flex-wrap gap-1 pt-1">
          {targets.map((target) => (
            <Badge key={target} variant="secondary" className="font-normal">
              {REGION_LABELS[target] ?? target}
            </Badge>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd className="text-right font-medium">{value}</dd>
    </div>
  )
}
