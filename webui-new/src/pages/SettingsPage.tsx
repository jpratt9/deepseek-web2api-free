import { PageHeader } from '@/components/layout/PageHeader'
import { EnvPreview } from '@/components/settings/EnvPreview'

export default function SettingsPage() {
  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader
        title="Settings"
        description="The current runtime configuration (read-only)"
      />
      <EnvPreview />
    </div>
  )
}
