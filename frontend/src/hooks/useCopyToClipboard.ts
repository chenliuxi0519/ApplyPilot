import { useCallback, useState } from "react"

type CopiedValue = string | null

type CopyFn = (text: string) => Promise<boolean>

export function useCopyToClipboard(): [CopiedValue, CopyFn] {
  const [copiedText, setCopiedText] = useState<CopiedValue>(null)

  const copy: CopyFn = useCallback(async (text) => {
    if (!navigator?.clipboard) {
      console.warn("当前浏览器不支持剪贴板功能")
      return false
    }

    try {
      await navigator.clipboard.writeText(text)
      setCopiedText(text)

      setTimeout(() => setCopiedText(null), 2000)

      return true
    } catch (error) {
      console.warn("复制失败", error)
      setCopiedText(null)
      return false
    }
  }, [])

  return [copiedText, copy]
}
