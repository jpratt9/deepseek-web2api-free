import { useState } from 'react'
import { Loader2, Plus, Save } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { post, put, ApiCallError } from '@/lib/api'
import { toast } from '@/hooks/use-toast'
import type { Account } from '@/lib/types'

interface Props {
  /** When set, the form is in "edit" mode. */
  account?: Account | null
  onSaved: (saved: Account) => void
  onCancel?: () => void
}

export function AccountForm({ account, onSaved, onCancel }: Props) {
  const isEdit = !!account
  const [email, setEmail] = useState(account?.email ?? '')
  const [token, setToken] = useState('')
  const [cookies, setCookies] = useState('')
  const [busy, setBusy] = useState(false)

  const handleSave = async () => {
    if (busy) return
    setBusy(true)
    try {
      if (isEdit && account) {
        const body: Record<string, string> = { email }
        if (token) body.token = token
        if (cookies) body.cookies = cookies
        await put(`/admin/api/accounts/${encodeURIComponent(account.id)}`, body)
        toast({ title: 'Account saved', variant: 'success' })
        // Refetch the account to get the fresh data.
        const saved: Account = { ...account, email: email || account.email }
        onSaved(saved)
      } else {
        if (!token || !cookies) {
          toast({ title: 'Token and Cookies cannot be empty', variant: 'destructive' })
          setBusy(false)
          return
        }
        const res = await post<{ ok: boolean; account: Account }>('/admin/api/accounts', {
          token,
          cookies,
          email: email || '',
        })
        toast({ title: 'Account added', variant: 'success' })
        onSaved(res.account)
        setEmail('')
        setToken('')
        setCookies('')
      }
    } catch (e) {
      const msg = e instanceof ApiCallError ? e.message : String(e)
      toast({ title: 'Save failed', description: msg, variant: 'destructive' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <Label htmlFor="acct-email">Label (email / note)</Label>
        <Input
          id="acct-email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="e.g. user@example.com"
          autoComplete="off"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="acct-token">Token</Label>
        <Input
          id="acct-token"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder={isEdit ? 'Leave blank to keep the current Token' : 'Authorization Bearer token (without the "Bearer" prefix)'}
          autoComplete="off"
          className="font-mono text-xs"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="acct-cookies">Cookies</Label>
        <Input
          id="acct-cookies"
          value={cookies}
          onChange={(e) => setCookies(e.target.value)}
          placeholder={isEdit ? 'Leave blank to keep the current Cookies' : 'cf_clearance=...; session=...'}
          autoComplete="off"
          className="font-mono text-xs"
        />
      </div>
      <div className="flex items-center gap-2 pt-2">
        <Button onClick={handleSave} disabled={busy}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : isEdit ? <Save className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
          {isEdit ? 'Save' : 'Add'}
        </Button>
        {isEdit && onCancel && (
          <Button variant="outline" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
        )}
      </div>
      {!isEdit && (
        <p className="text-xs text-muted-foreground">
          New accounts are persisted to data/accounts.json.
        </p>
      )}
    </div>
  )
}
