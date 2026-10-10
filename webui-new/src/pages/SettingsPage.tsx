import { PageHeader } from '@/components/layout/PageHeader'
import { ApiKeyManager } from '@/components/settings/ApiKeyManager'
import { EnvPreview } from '@/components/settings/EnvPreview'

export default function SettingsPage() {
  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader
        title="Settings"
        description="Manage client API keys and view the current runtime configuration"
      />
      <ApiKeyManager />
      <EnvPreview />
    </div>
  )
}
