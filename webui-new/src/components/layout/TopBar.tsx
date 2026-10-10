import { Moon, Sun, Monitor, RefreshCw } from 'lucide-react'
import { useThemeStore, applyTheme } from '@/stores/theme'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useTheme } from '@/hooks/useTheme'

interface TopBarProps {
  onRefresh?: () => void
  refreshing?: boolean
}

export function TopBar({ onRefresh, refreshing }: TopBarProps) {
  const theme = useThemeStore((s) => s.theme)
  const setTheme = useThemeStore((s) => s.setTheme)
  const { effective } = useTheme()

  const ThemeIcon = effective === 'dark' ? Moon : Sun

  return (
    <header className="flex h-14 items-center justify-end gap-2 border-b bg-card/40 px-4 backdrop-blur">
      {onRefresh && (
        <Button variant="ghost" size="icon" onClick={onRefresh} disabled={refreshing} aria-label="Refresh">
          <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
        </Button>
      )}

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" aria-label="Toggle theme">
            <ThemeIcon className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-40">
          <DropdownMenuLabel>Theme</DropdownMenuLabel>
          <DropdownMenuItem onClick={() => { setTheme('light'); applyTheme('light') }}>
            <Sun className="mr-2 h-4 w-4" /> Light
            {theme === 'light' && <span className="ml-auto text-primary">✓</span>}
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => { setTheme('dark'); applyTheme('dark') }}>
            <Moon className="mr-2 h-4 w-4" /> Dark
            {theme === 'dark' && <span className="ml-auto text-primary">✓</span>}
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => { setTheme('system'); applyTheme('system') }}>
            <Monitor className="mr-2 h-4 w-4" /> System
            {theme === 'system' && <span className="ml-auto text-primary">✓</span>}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </header>
  )
}
