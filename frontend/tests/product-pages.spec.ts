import { expect, type Page, test } from "@playwright/test"

const PROGRAM_ID = "11111111-1111-4111-8111-111111111111"
const APPLICATION_ID = "22222222-2222-4222-8222-222222222222"
const TASK_ID = "33333333-3333-4333-8333-333333333333"
const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
})

const program = {
  id: PROGRAM_ID,
  university_id: "44444444-4444-4444-8444-444444444444",
  name: "人工智能理学硕士",
  degree_type: "taught_masters",
  field_tags: ["人工智能"],
  program_url: "https://example.edu/ai",
  duration_months: 12,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  university: {
    id: "44444444-4444-4444-8444-444444444444",
    name: "香港科技大学",
    short_name: "港科大",
    region: "hong_kong",
    website_url: "https://example.edu",
  },
}
const profile = {
  id: "55555555-5555-4555-8555-555555555555",
  user_id: "66666666-6666-4666-8666-666666666666",
  undergraduate_university: "测试大学",
  undergraduate_major: "计算机科学",
  gpa_value: "3.50",
  gpa_scale: "4.00",
  ielts_overall: "6.5",
  work_experience_years: "1.5",
  experience_summary: "两段实习",
  budget_cny: 400000,
  target_regions: ["中国香港"],
  target_fields: ["人工智能"],
  career_goal: "算法工程师",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
}
const task = {
  id: TASK_ID,
  application_id: APPLICATION_ID,
  task_type: "cv",
  title: "Prepare CV",
  status: "todo",
  due_date: null,
  is_required: true,
  source: "template",
  source_requirement_id: null,
  completed_at: null,
  version: 1,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
}
const application = {
  id: APPLICATION_ID,
  user_id: profile.user_id,
  program_id: PROGRAM_ID,
  application_cycle: "2026/27",
  status: "preparing",
  target_deadline: "2026-03-01",
  submitted_at: null,
  version: 1,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
}

async function mockUser(page: Page) {
  await page.addInitScript(() =>
    localStorage.setItem("access_token", "browser-test-token"),
  )
  await page.route("**/api/v1/users/me", (route) =>
    route.fulfill(
      json({
        id: profile.user_id,
        email: "user@example.com",
        full_name: "测试用户",
        is_active: true,
        is_superuser: false,
      }),
    ),
  )
}

test("个人档案可加载并保存中文字段", async ({ page }) => {
  await mockUser(page)
  let savedBody: Record<string, unknown> | undefined
  await page.route("**/api/v1/profile/me", async (route) => {
    if (route.request().method() === "PATCH") {
      savedBody = route.request().postDataJSON()
      await route.fulfill(json({ ...profile, ...savedBody }))
    } else await route.fulfill(json(profile))
  })
  await page.goto("/profile")
  await expect(page.getByRole("heading", { name: "个人档案" })).toBeVisible()
  await page.getByLabel("本科院校").fill("复旦大学")
  await page.getByRole("button", { name: "保存档案" }).click()
  await expect.poll(() => savedBody?.undergraduate_university).toBe("复旦大学")
  await expect(page.getByText("个人档案已保存")).toBeVisible()
})

test("新用户在没有档案时可以直接建档", async ({ page }) => {
  await mockUser(page)
  let created = false
  await page.route("**/api/v1/profile/me", async (route) => {
    if (route.request().method() === "PATCH") {
      created = true
      await route.fulfill(json(profile))
    } else
      await route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Profile not found" }),
      })
  })
  await page.goto("/profile")
  await expect(
    page.getByText("填写以下信息建立档案；保存后会用于项目匹配。"),
  ).toBeVisible()
  await page.getByLabel("本科院校").fill("测试大学")
  await page.getByRole("button", { name: "保存档案" }).click()
  await expect.poll(() => created).toBe(true)
})

test("项目可对比、查看证据并加入申请计划", async ({ page }) => {
  await mockUser(page)
  let applicationCreated = false
  await page.route(/\/api\/v1\/programs\/(\?.*)?$/, (route) =>
    route.fulfill(json({ data: [program], count: 1 })),
  )
  await page.route(`**/api/v1/programs/${PROGRAM_ID}/requirements*`, (route) =>
    route.fulfill(
      json({
        data: [
          {
            id: "77777777-7777-4777-8777-777777777777",
            program_id: PROGRAM_ID,
            application_cycle: "2026/27",
            field_name: "ielts_overall",
            value_type: "numeric",
            numeric_value: "6.5",
            status: "published",
            published_evidence_id: "88888888-8888-4888-8888-888888888888",
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
        ],
        count: 1,
      }),
    ),
  )
  await page.route(`**/api/v1/programs/${PROGRAM_ID}/evidence*`, (route) =>
    route.fulfill(
      json({
        data: [
          {
            id: "88888888-8888-4888-8888-888888888888",
            program_id: PROGRAM_ID,
            application_cycle: "2026/27",
            field_name: "ielts_overall",
            value_type: "numeric",
            numeric_value: "6.5",
            source_url: "https://example.edu/requirements",
            source_type: "admission_page",
            captured_at: "2026-01-01T00:00:00Z",
            content_hash: null,
            status: "verified",
            reviewed_by: null,
            reviewed_at: null,
            review_note: null,
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
        ],
        count: 1,
      }),
    ),
  )
  await page.route(/\/api\/v1\/applications\/(\?.*)?$/, async (route) => {
    if (route.request().method() === "POST") applicationCreated = true
    await route.fulfill(
      json({
        ...application,
        tasks: [task],
        readiness: {
          is_ready: false,
          required_total: 1,
          required_done: 0,
          blocking_tasks: [],
        },
      }),
    )
  })
  await page.goto("/programs")
  await expect(page.getByText("人工智能理学硕士")).toBeVisible()
  await page.getByRole("button", { name: "加入对比" }).click()
  await expect(page.getByText("雅思总分")).toBeVisible()
  await page.getByRole("button", { name: "查看证据" }).click()
  await expect(page.getByRole("heading", { name: "官网证据" })).toBeVisible()
  await expect(
    page.getByRole("link", { name: "打开官网来源" }),
  ).toHaveAttribute("href", "https://example.edu/requirements")
  await page.keyboard.press("Escape")
  await page.getByRole("button", { name: "加入申请计划" }).click()
  await expect.poll(() => applicationCreated).toBe(true)
})

test("申请看板可显示并完成任务", async ({ page }) => {
  await mockUser(page)
  let taskUpdated = false
  await page.route(/\/api\/v1\/applications\/(\?.*)?$/, (route) =>
    route.fulfill(json({ data: [application], count: 1 })),
  )
  await page.route(`**/api/v1/applications/${APPLICATION_ID}`, (route) =>
    route.fulfill(
      json({
        ...application,
        tasks: [task],
        readiness: {
          is_ready: false,
          required_total: 1,
          required_done: 0,
          blocking_tasks: [
            {
              id: task.id,
              task_type: task.task_type,
              title: task.title,
              status: task.status,
            },
          ],
        },
      }),
    ),
  )
  await page.route(`**/api/v1/programs/${PROGRAM_ID}`, (route) =>
    route.fulfill(json(program)),
  )
  await page.route(`**/api/v1/application-tasks/${TASK_ID}`, async (route) => {
    taskUpdated = route.request().postDataJSON().status === "done"
    await route.fulfill(json({ ...task, status: "done", version: 2 }))
  })
  await page.goto("/applications")
  await expect(page.getByText("港科大 · 人工智能理学硕士")).toBeVisible()
  await page.getByRole("button", { name: /准备个人简历/ }).click()
  await expect.poll(() => taskUpdated).toBe(true)
  await expect(page.getByText("任务状态已更新")).toBeVisible()
})

test("首页汇总档案、申请和下一步任务", async ({ page }) => {
  await mockUser(page)
  await page.route("**/api/v1/profile/me", (route) =>
    route.fulfill(json(profile)),
  )
  await page.route(/\/api\/v1\/applications\/(\?.*)?$/, (route) =>
    route.fulfill(json({ data: [application], count: 1 })),
  )
  await page.route(`**/api/v1/applications/${APPLICATION_ID}`, (route) =>
    route.fulfill(
      json({
        ...application,
        tasks: [task],
        readiness: {
          is_ready: false,
          required_total: 1,
          required_done: 0,
          blocking_tasks: [],
        },
      }),
    ),
  )
  await page.route(`**/api/v1/programs/${PROGRAM_ID}`, (route) =>
    route.fulfill(json(program)),
  )

  await page.goto("/")

  await expect(
    page.getByRole("heading", { name: "欢迎回来，测试用户" }),
  ).toBeVisible()
  await expect(page.getByText("档案完整度")).toBeVisible()
  await expect(page.getByText("准备个人简历")).toBeVisible()
})

test("独立证据库支持检索和来源追溯", async ({ page }) => {
  await mockUser(page)
  await page.route(/\/api\/v1\/programs\/(\?.*)?$/, (route) =>
    route.fulfill(json({ data: [program], count: 1 })),
  )
  await page.route(`**/api/v1/programs/${PROGRAM_ID}/evidence*`, (route) =>
    route.fulfill(
      json({
        data: [
          {
            id: "88888888-8888-4888-8888-888888888888",
            program_id: PROGRAM_ID,
            application_cycle: "2026/27",
            field_name: "ielts_overall",
            value_type: "numeric",
            numeric_value: "6.5",
            source_url: "https://example.edu/requirements",
            source_type: "admission_page",
            captured_at: "2026-01-01T00:00:00Z",
            content_hash: null,
            status: "verified",
            reviewed_by: null,
            reviewed_at: null,
            review_note: null,
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
        ],
        count: 1,
      }),
    ),
  )

  await page.goto("/evidence")

  await expect(page.getByRole("heading", { name: "证据库" })).toBeVisible()
  await expect(page.getByText("港科大 · 人工智能理学硕士")).toBeVisible()
  await page.getByLabel("搜索证据").fill("不存在的项目")
  await expect(page.getByText("没有符合条件的证据")).toBeVisible()
})

test("高风险申请状态必须经过中文确认弹窗", async ({ page }) => {
  await mockUser(page)
  const ready = { ...application, status: "ready_to_submit", version: 3 }
  let patchCalled = false
  await page.route(/\/api\/v1\/applications\/(\?.*)?$/, (route) =>
    route.fulfill(json({ data: [ready], count: 1 })),
  )
  await page.route(
    `**/api/v1/applications/${APPLICATION_ID}`,
    async (route) => {
      if (route.request().method() === "PATCH") {
        patchCalled = true
        await route.fulfill(
          json({
            ...ready,
            status: "submitted",
            submitted_at: "2026-02-01T00:00:00Z",
            version: 4,
            tasks: [],
            readiness: {
              is_ready: true,
              required_total: 1,
              required_done: 1,
              blocking_tasks: [],
            },
          }),
        )
      } else
        await route.fulfill(
          json({
            ...ready,
            tasks: [],
            readiness: {
              is_ready: true,
              required_total: 1,
              required_done: 1,
              blocking_tasks: [],
            },
          }),
        )
    },
  )
  await page.route(`**/api/v1/programs/${PROGRAM_ID}`, (route) =>
    route.fulfill(json(program)),
  )
  await page.goto("/applications")

  await page.getByLabel("申请阶段").click()
  await page.getByRole("option", { name: "已提交" }).click()
  await expect(
    page.getByRole("heading", { name: "确认更新申请状态" }),
  ).toBeVisible()
  expect(patchCalled).toBe(false)
  await page.getByRole("button", { name: "确认更新" }).click()
  await expect.poll(() => patchCalled).toBe(true)
})

test("移动端核心页面不会把正文挤出视口", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockUser(page)
  await page.route("**/api/v1/profile/me", (route) =>
    route.fulfill(json(profile)),
  )
  await page.route(/\/api\/v1\/programs\/(\?.*)?$/, (route) =>
    route.fulfill(json({ data: [program], count: 1 })),
  )
  await page.route(`**/api/v1/programs/${PROGRAM_ID}/requirements*`, (route) =>
    route.fulfill(json({ data: [], count: 0 })),
  )
  await page.goto("/programs")

  await expect(
    page.getByRole("heading", { name: "项目检索与对比" }),
  ).toBeVisible()
  const dimensions = await page.evaluate(() => ({
    width: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }))
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.width)
  await page.getByRole("button", { name: "打开侧边栏" }).click()
  await expect(page.getByText("申请看板", { exact: true })).toBeVisible()
})

test("用户可以新增、编辑和删除自建任务", async ({ page }) => {
  await mockUser(page)
  const userTask = {
    ...task,
    id: "99999999-9999-4999-8999-999999999999",
    title: "准备面试",
    task_type: "other",
    source: "user",
    is_required: false,
  }
  let created = false
  let updated = false
  let deleted = false
  await page.route(/\/api\/v1\/applications\/(\?.*)?$/, (route) =>
    route.fulfill(json({ data: [application], count: 1 })),
  )
  await page.route(`**/api/v1/applications/${APPLICATION_ID}`, (route) =>
    route.fulfill(
      json({
        ...application,
        tasks: [userTask],
        readiness: {
          is_ready: false,
          required_total: 0,
          required_done: 0,
          blocking_tasks: [],
        },
      }),
    ),
  )
  await page.route(`**/api/v1/programs/${PROGRAM_ID}`, (route) =>
    route.fulfill(json(program)),
  )
  await page.route(
    `**/api/v1/applications/${APPLICATION_ID}/tasks`,
    async (route) => {
      created = true
      await route.fulfill(
        json({
          ...userTask,
          id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          title: route.request().postDataJSON().title,
        }),
      )
    },
  )
  await page.route(
    `**/api/v1/application-tasks/${userTask.id}*`,
    async (route) => {
      if (route.request().method() === "PATCH") updated = true
      if (route.request().method() === "DELETE") deleted = true
      await route.fulfill(
        json(
          route.request().method() === "DELETE"
            ? { message: "Task deleted" }
            : { ...userTask, title: "准备技术面试", version: 2 },
        ),
      )
    },
  )
  await page.goto("/applications")

  await page.getByRole("button", { name: "新增任务" }).click()
  await page.getByLabel("任务名称").fill("整理作品集")
  await page.getByRole("button", { name: "保存任务" }).click()
  await expect.poll(() => created).toBe(true)

  await page.getByRole("button", { name: "编辑 准备面试" }).click()
  await page.getByLabel("任务名称").fill("准备技术面试")
  await page.getByRole("button", { name: "保存任务" }).click()
  await expect.poll(() => updated).toBe(true)

  await page.getByRole("button", { name: "删除 准备面试" }).click()
  await page.getByRole("button", { name: "确认删除" }).click()
  await expect.poll(() => deleted).toBe(true)
})
