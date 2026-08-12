import { expect, type Page, test } from "@playwright/test"

const CHAT = "**/api/v1/agent/chat"
const APPROVE = "**/api/v1/agent/runs/*/approve"
const REJECT = "**/api/v1/agent/runs/*/reject"
const CONFIG = "**/api/v1/agent/config"
const RUNS = "**/api/v1/agent/runs/?*"
const PROFILE = "**/api/v1/profile/me"
const APPLICATIONS_LIST = /\/api\/v1\/applications\/(\?.*)?$/
const APPLICATION_DETAIL = /\/api\/v1\/applications\/[0-9a-f-]{36}$/
const PROGRAM_DETAIL = /\/api\/v1\/programs\/[0-9a-f-]{36}$/

const RUN_ID = "11111111-1111-4111-8111-111111111111"
const APPLICATION_ID = "22222222-2222-4222-8222-222222222222"
const PROGRAM_ID = "33333333-3333-4333-8333-333333333333"

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem("access_token", "browser-test-token"),
  )
  await page.route("**/api/v1/users/me", (route) =>
    route.fulfill(
      json({
        id: "55555555-5555-4555-8555-555555555555",
        email: "user@example.com",
        full_name: "测试用户",
        is_active: true,
        is_superuser: false,
      }),
    ),
  )
})

const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
})

async function mockSurroundings(page: Page, applicationStatus: string) {
  await page.route(CONFIG, (route) => route.fulfill(json({ configured: true })))
  await page.route(RUNS, (route) => route.fulfill(json({ data: [], count: 0 })))
  await page.route(PROFILE, (route) =>
    route.fulfill(
      json({
        id: "44444444-4444-4444-8444-444444444444",
        user_id: "55555555-5555-4555-8555-555555555555",
        undergraduate_university: "Zhejiang University",
        undergraduate_major: "Computer Science",
        gpa_value: "3.60",
        gpa_scale: "4.00",
        ielts_overall: "6.5",
        budget_cny: null,
        target_regions: ["singapore"],
        target_fields: ["ai"],
        career_goal: null,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      }),
    ),
  )
  await page.route(APPLICATIONS_LIST, (route) =>
    route.fulfill(
      json({
        data: [
          {
            id: APPLICATION_ID,
            user_id: "55555555-5555-4555-8555-555555555555",
            program_id: PROGRAM_ID,
            application_cycle: "2026/27",
            status: applicationStatus,
            target_deadline: null,
            submitted_at: null,
            version: 1,
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
        ],
        count: 1,
      }),
    ),
  )
  await page.route(APPLICATION_DETAIL, (route) =>
    route.fulfill(
      json({
        id: APPLICATION_ID,
        user_id: "55555555-5555-4555-8555-555555555555",
        program_id: PROGRAM_ID,
        application_cycle: "2026/27",
        status: applicationStatus,
        target_deadline: null,
        submitted_at: null,
        version: 1,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
        readiness: {
          is_ready: true,
          required_total: 4,
          required_done: 4,
          blocking_tasks: [],
        },
        tasks: [],
      }),
    ),
  )
  await page.route(PROGRAM_DETAIL, (route) =>
    route.fulfill(
      json({
        id: PROGRAM_ID,
        university_id: "66666666-6666-4666-8666-666666666666",
        name: "Master of Computing in Artificial Intelligence",
        degree_type: "taught_master",
        field_tags: ["ai"],
        program_url: null,
        duration_months: null,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
        university: {
          id: "66666666-6666-4666-8666-666666666666",
          name: "National University of Singapore",
          short_name: "NUS",
          region: "singapore",
          website_url: null,
        },
      }),
    ),
  )
}

const searchAnswer = {
  run_id: RUN_ID,
  conversation_id: "c-test",
  status: "completed",
  answer: "I found one program in Singapore.",
  confirmation: null,
  tool_trace: [{ label: "Searched the program catalog", status: "ok" }],
  ui_events: [
    {
      type: "programs",
      data: {
        count: 1,
        programs: [
          {
            program_id: PROGRAM_ID,
            name: "Master of Computing in Artificial Intelligence",
            university: "NUS",
            region: "singapore",
            degree_type: "taught_master",
            field_tags: ["ai"],
          },
        ],
      },
    },
  ],
  steps: 2,
  tool_calls: 1,
  error: null,
}

const pausedAnswer = {
  run_id: RUN_ID,
  conversation_id: "c-test",
  status: "waiting_confirmation",
  answer: null,
  confirmation: {
    call_id: "toolu_1",
    tool_name: "update_application_status",
    permission_level: "high_risk_write",
    reason: "update_application_status needs a human decision",
    summary: {
      application_id: APPLICATION_ID,
      program_label: "NUS Master of Computing in Artificial Intelligence",
      application_cycle: "2026/27",
      current_status: "ready_to_submit",
      target_status: "submitted",
    },
  },
  tool_trace: [],
  ui_events: [],
  steps: 1,
  tool_calls: 0,
  error: null,
}

async function ask(page: Page, text: string) {
  await page.getByTestId("composer-input").fill(text)
  await page.getByTestId("composer-send").click()
}

test("a search renders an answer and a program card", async ({ page }) => {
  await mockSurroundings(page, "shortlisted")
  await page.route(CHAT, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 300))
    await route.fulfill(json(searchAnswer))
  })

  await page.goto("/agent")
  await ask(page, "Find AI programs in Singapore")

  await expect(page.getByTestId("thinking")).toBeVisible()
  await expect(
    page.getByText("I found one program in Singapore."),
  ).toBeVisible()
  await expect(
    page.getByText("Master of Computing in Artificial Intelligence").first(),
  ).toBeVisible()
  await expect(page.getByRole("button", { name: "加入申请计划" })).toBeVisible()
  await expect(page.getByText("Searched the program catalog")).toBeVisible()
})

test("confirming a high-risk change calls approve and clears the card", async ({
  page,
}) => {
  let applicationStatus = "ready_to_submit"
  await mockSurroundings(page, applicationStatus)
  await page.route(CHAT, (route) => route.fulfill(json(pausedAnswer)))

  let approveCalls = 0
  await page.route(APPROVE, async (route) => {
    approveCalls += 1
    applicationStatus = "submitted"
    await page.unroute(APPLICATIONS_LIST)
    await page.unroute(APPLICATION_DETAIL)
    await mockSurroundings(page, applicationStatus)
    await route.fulfill(
      json({
        ...pausedAnswer,
        status: "completed",
        answer: "Marked as submitted.",
        confirmation: null,
        tool_trace: [{ label: "Updated an application status", status: "ok" }],
      }),
    )
  })

  await page.goto("/agent")
  await ask(page, "I submitted it")

  const card = page.getByTestId("confirmation-card")
  await expect(card).toBeVisible()
  await expect(card).toContainText("可提交")
  await expect(card).toContainText("已提交")

  await page.getByTestId("confirmation-confirm").click()

  await expect(card).toBeHidden()
  await expect(page.getByText("Marked as submitted.")).toBeVisible()
  expect(approveCalls).toBe(1)
  await expect(page.getByTestId("workspace").getByText("已提交")).toBeVisible()
})

test("cancelling calls reject and leaves the application alone", async ({
  page,
}) => {
  await mockSurroundings(page, "ready_to_submit")
  await page.route(CHAT, (route) => route.fulfill(json(pausedAnswer)))

  let rejectCalls = 0
  let approveCalls = 0
  await page.route(APPROVE, async (route) => {
    approveCalls += 1
    await route.fulfill(json(pausedAnswer))
  })
  await page.route(REJECT, async (route) => {
    rejectCalls += 1
    await route.fulfill(
      json({
        ...pausedAnswer,
        status: "completed",
        answer: "No problem, I left it as it was.",
        confirmation: null,
      }),
    )
  })

  await page.goto("/agent")
  await ask(page, "I submitted it")

  const card = page.getByTestId("confirmation-card")
  await expect(card).toBeVisible()
  await page.getByTestId("confirmation-cancel").click()

  await expect(card).toBeHidden()
  await expect(page.getByText("No problem, I left it as it was.")).toBeVisible()
  expect(rejectCalls).toBe(1)
  expect(approveCalls).toBe(0)
  await expect(page.getByTestId("workspace").getByText("可提交")).toBeVisible()
})

test("刷新后会自动恢复最近一次完整对话", async ({ page }) => {
  await mockSurroundings(page, "shortlisted")
  await page.unroute(RUNS)
  await page.route(RUNS, (route) =>
    route.fulfill(
      json({
        data: [
          {
            id: RUN_ID,
            status: "completed",
            started_at: "2026-01-01T00:00:00Z",
            finished_at: "2026-01-01T00:00:01Z",
            step_count: 2,
            tool_call_count: 1,
            final_answer: searchAnswer.answer,
            conversation_id: searchAnswer.conversation_id,
            user_message: "帮我找新加坡的人工智能项目",
            response_payload: searchAnswer,
            last_error_code: null,
          },
        ],
        count: 1,
      }),
    ),
  )

  await page.goto("/agent")

  await expect(
    page.getByText("帮我找新加坡的人工智能项目").last(),
  ).toBeVisible()
  await expect(page.getByText(searchAnswer.answer)).toBeVisible()
  await expect(page.getByRole("button", { name: /帮我找新加坡/ })).toBeVisible()
})
