import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { get } from '@/lib/api'
import { useToast } from '@/hooks/use-toast'

interface EnvEntry {
  name: string
  value: string
  is_default: boolean
}

interface EnvInfoResponse {
  host: string
  port: number
  accounts_total: number
  crypto: { enabled: boolean; fernet_configured: boolean }
  log_level: string
  log_format: string
  uptime_secs: number
  server_version: string
  env_overrides: EnvEntry[]
}

export function EnvPreview() {
  const [info, setInfo] = useState<EnvInfoResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const { toast } = useToast()

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    get<EnvInfoResponse>('/admin/api/env')
      .then((d) => !cancelled && setInfo(d))
      .catch((e) => {
        if (cancelled) return
        setError(String(e?.message ?? e))
        toast({ title: 'Failed to load environment info', description: String(e?.message ?? e), variant: 'destructive' })
      })
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [toast])

  if (loading && !info) {
    return <div className="text-sm text-muted-foreground">Loading…</div>
  }
  if (error || !info) {
    return <div className="text-sm text-destructive">{error ?? 'Failed to load'}</div>
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Runtime</CardTitle>
        </CardHeader>
        <CardContent className="space-y-1.5 text-sm">
          <Row k="Server version" v={info.server_version} />
          <Row k="Listen address" v={`${info.host}:${info.port}`} />
          <Row k="Uptime" v={info.uptime_secs > 0 ? `${Math.floor(info.uptime_secs / 60)} min` : '—'} />
          <Row k="Logging" v={`${info.log_level} / ${info.log_format}`} />
          <Row
            k="Credential encryption"
            v={info.crypto.enabled ? `Fernet (${info.crypto.fernet_configured ? 'key configured' : 'key missing'})` : 'Plaintext'}
            warn={!info.crypto.enabled}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Account Pool</CardTitle>
        </CardHeader>
        <CardContent className="space-y-1.5 text-sm">
          <Row k="Total" v={String(info.accounts_total)} />
          <Row k="Configured via" v="WebUI / data/accounts.json" />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">All environment variables</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[280px]">Name</TableHead>
                <TableHead>Value</TableHead>
                <TableHead className="w-[100px] text-right">Source</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {info.env_overrides.map((e) => (
                <TableRow key={e.name}>
                  <TableCell className="font-mono text-xs">{e.name}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground break-all">
                    {e.value || <span className="italic">empty</span>}
                  </TableCell>
                  <TableCell className="text-right">
                    {e.is_default ? (
                      <Badge variant="outline">default</Badge>
                    ) : (
                      <Badge variant="secondary">set</Badge>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}

function Row({ k, v, warn }: { k: string; v: string; warn?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-muted-foreground">{k}</span>
      <span className={warn ? 'text-warning font-medium' : 'text-right'}>{v}</span>
    </div>
  )
}
