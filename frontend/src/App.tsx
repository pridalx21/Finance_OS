import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Reports from './pages/Reports'
import PurchaseManager from './components/PurchaseManager'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, '') || '/'}>
        <nav style={{ padding: '0.5rem 1rem', borderBottom: '1px solid #e5e7eb', display: 'flex', gap: '1rem' }}>
          <a href={`${import.meta.env.BASE_URL}dashboard`}>Dashboard</a>
          <a href={`${import.meta.env.BASE_URL}reports`}>Berichte</a>
          <a href={`${import.meta.env.BASE_URL}purchases`}>Einkäufe</a>
        </nav>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
<Route path="/reports" element={<Reports />} />
<Route path="/purchases" element={<PurchaseManager />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
