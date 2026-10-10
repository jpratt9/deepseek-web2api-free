import { useState } from 'react'
import { RotateCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { post, ApiCallError } from '@/lib/api'
import { toast } from '@/hooks/use-toast'
import type { ReloginResponse } from '@/lib/types'

interface Props {
  accountId: string
  onDone?: () => void
}

export function ReloginButton({ accountId, onDone }: Props) {
  const [busy, setBusy] = useState(false)
  const handleClick = async () => {
    setBusy(true)
    try {
      const res = await post<ReloginResponse>(`/admin/api/accounts/${encodeURIComponent(accountId)}/relogin`)
      if (res.ok) {
        toast({ title: 'Re-login succeeded', variant: 'success' })
      } else {
        toast({ title: 'Re-login failed', description: res.message, variant: 'destructive' })
      }
      onDone?.()
    } catch (e) {
      const msg = e instanceof ApiCallError ? e.message : String(e)
      toast({ title: 'Re-login failed', description: msg, variant: 'destructive' })
    } finally {
      setBusy(false)
    }
  }
  return (
    <Button variant="outline" size="sm" onClick={handleClick} disabled={busy}>
      <RotateCw className={`h-3.5 w-3.5 ${busy ? 'animate-spin' : ''}`} />
      Re-login
    </Button>
  )
}
