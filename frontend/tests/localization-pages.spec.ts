import { expect, type Page, test } from "@playwright/test"

const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
})
const currentUser = {
  id: "11111111-1111-4111-8111-111111111111",
  email: "admin@example.com",
  full_name: "测试管理员",
  is_active: true,
  is_superuser: true,
}

async function authenticated(page: Page) {
  await page.addInitScript(() =>
    localStorage.setItem("access_token", "browser-test-token"),
  )
  await page.route("**/api/v1/users/me", (route) =>
    route.fulfill(json(currentUser)),
  )
}

test("登录、注册和找回密码页面使用中文", async ({ page }) => {
  await page.addInitScript(() => localStorage.removeItem("access_token"))
  await page.goto("/login")
  await expect(
    page.getByRole("heading", { name: "登录你的账户" }),
  ).toBeVisible()
  await expect(page.getByRole("button", { name: "登录" })).toBeVisible()
  await page.goto("/signup")
  await expect(page.getByRole("heading", { name: "创建账户" })).toBeVisible()
  await page.goto("/recover-password")
  await expect(page.getByRole("heading", { name: "找回密码" })).toBeVisible()
})

test("账户设置页面及表单全部使用中文", async ({ page }) => {
  await authenticated(page)
  await page.goto("/settings")
  await expect(page.getByRole("heading", { name: "账户设置" })).toBeVisible()
  for (const tab of ["个人资料", "密码", "危险操作"])
    await expect(page.getByRole("tab", { name: tab })).toBeVisible()
  await page.getByRole("button", { name: "编辑" }).click()
  await expect(page.getByLabel("姓名")).toBeVisible()
  await expect(page.getByLabel("邮箱")).toBeVisible()
  await page.getByRole("button", { name: "取消" }).click()
  await page.getByRole("tab", { name: "密码" }).click()
  await expect(page.getByLabel("当前密码")).toBeVisible()
  await expect(page.getByRole("button", { name: "更新密码" })).toBeVisible()
})

test("用户管理页面及新增表单全部使用中文", async ({ page }) => {
  await authenticated(page)
  await page.route(/\/api\/v1\/users\/(\?.*)?$/, (route) =>
    route.fulfill(json({ data: [currentUser], count: 1 })),
  )
  await page.goto("/admin")
  await expect(page.getByRole("heading", { name: "用户管理" })).toBeVisible()
  await expect(
    page.getByText("普通用户").or(page.getByText("超级管理员")),
  ).toBeVisible()
  await page.getByRole("button", { name: "添加用户" }).click()
  await expect(page.getByRole("heading", { name: "添加用户" })).toBeVisible()
  await expect(page.getByPlaceholder("请输入邮箱")).toBeVisible()
  await expect(page.getByLabel("设为超级管理员")).toBeVisible()
  await expect(page.getByLabel("启用账户")).toBeVisible()
})
