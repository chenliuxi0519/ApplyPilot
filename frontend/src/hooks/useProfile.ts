import { useQuery } from "@tanstack/react-query"

import { ProfileService } from "@/client"

/** 档案在多个页面都要用，缓存一分钟，避免每次切换页面都重新请求。 */
const PROFILE_STALE_MS = 60_000

/**
 * 读取当前用户的个人档案。尚未建档时 `data` 为 `null`，这是正常状态而非错误。
 */
export function useProfile() {
  return useQuery({
    queryKey: ["profile"],
    queryFn: () => ProfileService.readProfileMe(),
    staleTime: PROFILE_STALE_MS,
  })
}
