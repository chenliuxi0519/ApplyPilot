import type {
  AgentChatPublic,
  AgentRunPublic,
  ConfirmationPublic,
  ToolTracePublic,
} from "@/client"

export type ProgramSummary = {
  program_id: string
  name: string
  university: string
  region: string
  degree_type: string
  field_tags: string[]
}

export type RequirementSummary = {
  field_name: string
  application_cycle: string
  value: string
  status: string
  source_url: string | null
  captured_at: string | null
}

export type FitFactor = {
  field: string
  required: string
  have: string
  delta: string
}

export type ProgramFit = {
  program_id: string
  name: string
  university: string
  application_cycle: string | null
  band: "reach" | "target" | "safer" | "unknown"
  disputed: boolean
  gaps: FitFactor[]
  strengths: FitFactor[]
  context: { field: string; value: string }[]
}

export type ProgramsEvent = {
  kind: "programs"
  count: number
  programs: ProgramSummary[]
}

export type RequirementsEvent = {
  kind: "requirements"
  programId: string
  requirements: RequirementSummary[]
}

export type ComparisonEvent = {
  kind: "comparison"
  count: number
  profileMissing: string[]
  fits: ProgramFit[]
}

export type AgentCard = ProgramsEvent | RequirementsEvent | ComparisonEvent

export type ChatMessage =
  | { id: string; role: "user"; text: string }
  | {
      id: string
      role: "assistant"
      text: string | null
      cards: AgentCard[]
      trace: ToolTracePublic[]
      confirmation: ConfirmationPublic | null
      runId: string
      status: AgentChatPublic["status"]
      error: string | null
    }
  | { id: string; role: "error"; text: string }

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : ""
}

function toProgram(value: unknown): ProgramSummary | null {
  if (!isRecord(value) || typeof value.program_id !== "string") return null
  return {
    program_id: value.program_id,
    name: asString(value.name),
    university: asString(value.university),
    region: asString(value.region),
    degree_type: asString(value.degree_type),
    field_tags: Array.isArray(value.field_tags)
      ? value.field_tags.filter((tag): tag is string => typeof tag === "string")
      : [],
  }
}

function toRequirement(value: unknown): RequirementSummary | null {
  if (!isRecord(value) || typeof value.field_name !== "string") return null
  return {
    field_name: value.field_name,
    application_cycle: asString(value.application_cycle),
    value: asString(value.value),
    status: asString(value.status),
    source_url: typeof value.source_url === "string" ? value.source_url : null,
    captured_at:
      typeof value.captured_at === "string" ? value.captured_at : null,
  }
}

function toFactor(value: unknown): FitFactor | null {
  if (!isRecord(value) || typeof value.field !== "string") return null
  return {
    field: value.field,
    required: asString(value.required),
    have: asString(value.have),
    delta: asString(value.delta),
  }
}

function toFit(value: unknown): ProgramFit | null {
  if (!isRecord(value) || typeof value.program_id !== "string") return null
  const band = value.band
  if (
    band !== "reach" &&
    band !== "target" &&
    band !== "safer" &&
    band !== "unknown"
  ) {
    return null
  }
  return {
    program_id: value.program_id,
    name: asString(value.name),
    university: asString(value.university),
    application_cycle:
      typeof value.application_cycle === "string"
        ? value.application_cycle
        : null,
    band,
    disputed: value.disputed === true,
    gaps: (Array.isArray(value.gaps) ? value.gaps : [])
      .map(toFactor)
      .filter((factor): factor is FitFactor => factor !== null),
    strengths: (Array.isArray(value.strengths) ? value.strengths : [])
      .map(toFactor)
      .filter((factor): factor is FitFactor => factor !== null),
    context: (Array.isArray(value.context) ? value.context : [])
      .map((entry) =>
        isRecord(entry) && typeof entry.field === "string"
          ? { field: entry.field, value: asString(entry.value) }
          : null,
      )
      .filter(
        (entry): entry is { field: string; value: string } => entry !== null,
      ),
  }
}

export function toCards(response: AgentChatPublic): AgentCard[] {
  const cards: AgentCard[] = []
  for (const event of response.ui_events ?? []) {
    if (event.type === "programs") {
      const programs = (
        Array.isArray(event.data.programs) ? event.data.programs : []
      )
        .map(toProgram)
        .filter((program): program is ProgramSummary => program !== null)
      if (programs.length > 0) {
        cards.push({
          kind: "programs",
          count:
            typeof event.data.count === "number"
              ? event.data.count
              : programs.length,
          programs,
        })
      }
      continue
    }
    if (event.type === "requirements") {
      const requirements = (
        Array.isArray(event.data.requirements) ? event.data.requirements : []
      )
        .map(toRequirement)
        .filter(
          (requirement): requirement is RequirementSummary =>
            requirement !== null,
        )
      if (requirements.length > 0) {
        cards.push({
          kind: "requirements",
          programId: asString(event.data.program_id),
          requirements,
        })
      }
      continue
    }
    if (event.type === "comparison") {
      const fits = (Array.isArray(event.data.fits) ? event.data.fits : [])
        .map(toFit)
        .filter((fit): fit is ProgramFit => fit !== null)
      if (fits.length > 0) {
        cards.push({
          kind: "comparison",
          count:
            typeof event.data.count === "number"
              ? event.data.count
              : fits.length,
          profileMissing: Array.isArray(event.data.profile_missing)
            ? event.data.profile_missing.filter(
                (name): name is string => typeof name === "string",
              )
            : [],
          fits,
        })
      }
    }
  }
  return cards
}

export function toAssistantMessage(
  response: AgentChatPublic,
  id: string,
): ChatMessage {
  return {
    id,
    role: "assistant",
    text: response.answer ?? null,
    cards: toCards(response),
    trace: response.tool_trace ?? [],
    confirmation: response.confirmation ?? null,
    runId: response.run_id,
    status: response.status,
    error: response.error ?? null,
  }
}

function toPersistedResponse(value: unknown): AgentChatPublic | null {
  if (
    !isRecord(value) ||
    typeof value.run_id !== "string" ||
    typeof value.conversation_id !== "string" ||
    typeof value.status !== "string"
  ) {
    return null
  }
  return value as AgentChatPublic
}

export function runsToMessages(runs: AgentRunPublic[]): ChatMessage[] {
  const messages: ChatMessage[] = []
  const ordered = [...runs].sort(
    (left, right) =>
      new Date(left.started_at).getTime() -
      new Date(right.started_at).getTime(),
  )
  for (const run of ordered) {
    if (run.user_message) {
      messages.push({
        id: `history-user-${run.id}`,
        role: "user",
        text: run.user_message,
      })
    }
    const response = toPersistedResponse(run.response_payload)
    if (response) {
      messages.push(toAssistantMessage(response, `history-assistant-${run.id}`))
    } else if (run.final_answer) {
      messages.push({
        id: `history-assistant-${run.id}`,
        role: "assistant",
        text: run.final_answer,
        cards: [],
        trace: [],
        confirmation: null,
        runId: run.id,
        status: run.status,
        error: run.last_error_code,
      })
    }
  }
  return messages
}
