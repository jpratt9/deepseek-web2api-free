import { useEffect, useState } from 'react'
import { Copy, KeyRound, Plus, Trash2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { useToast } from '@/hooks/use-toast'
import { del, get, post } from '@/lib/api'

interface ApiKeyRecord {
  id: string
  name: string
  prefix: string
  created_at: number
}

interface ApiKeyListResponse {
  keys: ApiKeyRecord[]
}

interface ApiKeyCreateResponse {
  key: string
  api_key: ApiKeyRecord
}

export function ApiKeyManager() {
  const [keys, setKeys] = useState<ApiKeyRecord[]>([])
  const [name, setName] = useState('')
  const [newKey, setNewKey] = useState<string | null>(null)
  const [confirmingId, setConfirmingId] = useState<string | null>(null)
  const [revokingId, setRevokingId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { toast } = useToast()

  useEffect(() => {
    let cancelled = false
    get<ApiKeyListResponse>('/admin/api/api-keys')
      .then((result) => {
        if (!cancelled) setKeys(result.keys)
      })
      .catch((e) => {
        if (cancelled) return
        const message = String(e?.message ?? e)
        setError(message)
        toast({ title: 'Failed to load API keys', description: message, variant: 'destructive' })
      })
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [toast])

  async function createKey() {
    const trimmedName = name.trim()
    if (!trimmedName) {
      toast({ title: 'Please enter a key name', variant: 'destructive' })
      return
    }

    setCreating(true)
    setError(null)
    try {
      const result = await post<ApiKeyCreateResponse>('/admin/api/api-keys', { name: trimmedName })
      setKeys((current) => [result.api_key, ...current])
      setNewKey(result.key)
      setName('')
      setConfirmingId(null)
      toast({ title: 'API key generated', description: 'Copy and save the full key now.' })
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : String(e)
      setError(message)
      toast({ title: 'Failed to generate API key', description: message, variant: 'destructive' })
    } finally {
      setCreating(false)
    }
  }

  async function revokeKey(key: ApiKeyRecord) {
    setRevokingId(key.id)
    setError(null)
    try {
      await del(`/admin/api/api-keys/${encodeURIComponent(key.id)}`)
      setKeys((current) => current.filter((item) => item.id !== key.id))
      setConfirmingId(null)
      toast({ title: 'API key revoked', description: `${key.name} can no longer call the API.` })
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : String(e)
      setError(message)
      toast({ title: 'Failed to revoke API key', description: message, variant: 'destructive' })
    } finally {
      setRevokingId(null)
    }
  }

  async function copyKey() {
    if (!newKey) return
    try {
      await navigator.clipboard.writeText(newKey)
      toast({ title: 'API key copied' })
    } catch {
      toast({
        title: 'Could not copy automatically',
        description: 'Select the key text above and copy it manually.',
        variant: 'destructive',
      })
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1.5">
            <CardTitle className="flex items-center gap-2 text-base">
              <KeyRound className="h-4 w-4" />
              Client API Keys
            </CardTitle>
            <CardDescription>
              Create a separate key for each client; the full value is shown only once at creation, and the server stores only its hash.
            </CardDescription>
          </div>
          <Badge variant="secondary">{keys.length}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => event.key === 'Enter' && void createKey()}
            placeholder="Key name, e.g. Claude Code"
            maxLength={64}
            aria-label="API key name"
            disabled={creating}
          />
          <Button onClick={() => void createKey()} disabled={creating || !name.trim()}>
            <Plus className="h-4 w-4" />
            {creating ? 'Generating…' : 'Generate key'}
          </Button>
        </div>

        {newKey && (
          <div className="space-y-2 rounded-md border border-primary/30 bg-primary/5 p-3">
            <div className="text-sm font-medium">This key is shown only once — copy and save it now.</div>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Input value={newKey} readOnly className="font-mono text-xs select-all" aria-label="Newly generated API key" />
              <Button variant="outline" onClick={() => void copyKey()}>
                <Copy className="h-4 w-4" />Copy
              </Button>
              <Button variant="ghost" onClick={() => setNewKey(null)}>Done</Button>
            </div>
          </div>
        )}

        {error && <p className="text-sm text-destructive">{error}</p>}

        {loading ? (
          <p className="text-sm text-muted-foreground">Loading keys…</p>
        ) : keys.length === 0 ? (
          <p className="rounded-md border border-dashed p-4 text-center text-sm text-muted-foreground">
            No client API keys yet. Generate one to use with the OpenAI-compatible API.
          </p>
        ) : (
          <div className="divide-y rounded-md border">
            {keys.map((key) => (
              <div key={key.id} className="flex flex-col gap-3 p-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0 space-y-1">
                  <div className="truncate text-sm font-medium">{key.name}</div>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                    <code className="font-mono">{key.prefix}…</code>
                    <span>Created {new Date(key.created_at * 1000).toLocaleString()}</span>
                  </div>
                </div>
                {confirmingId === key.id ? (
                  <div className="flex shrink-0 items-center gap-2">
                    <span className="text-xs text-destructive">Confirm revoke?</span>
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={() => void revokeKey(key)}
                      disabled={revokingId === key.id}
                    >
                      {revokingId === key.id ? 'Revoking…' : 'Confirm'}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setConfirmingId(null)} disabled={revokingId === key.id}>
                      Cancel
                    </Button>
                  </div>
                ) : (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="shrink-0 text-muted-foreground hover:text-destructive"
                    onClick={() => setConfirmingId(key.id)}
                    aria-label={`Revoke ${key.name}`}
                  >
                    <Trash2 className="h-4 w-4" />Revoke
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
