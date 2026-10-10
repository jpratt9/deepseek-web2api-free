import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import DashboardPage from '@/pages/DashboardPage'
import AccountsPage from '@/pages/AccountsPage'
import PlaygroundPage from '@/pages/PlaygroundPage'
import SettingsPage from '@/pages/SettingsPage'
import NotFoundPage from '@/pages/NotFoundPage'

// basename: '/webui' — the SPA is served under /webui/* by the backend,
// so client-side navigation keeps the prefix and deep links refresh cleanly.
// No auth gate: this proxy runs on localhost, so the panel opens straight
// to the dashboard with no login.
const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'accounts', element: <AccountsPage /> },
      { path: 'accounts/:id', element: <AccountsPage /> },
      { path: 'playground', element: <PlaygroundPage /> },
      { path: 'settings', element: <SettingsPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
], { basename: '/webui' })

export function App() {
  return <RouterProvider router={router} />
}
