import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import MonthlyTrendChart from './MonthlyTrendChart'
import * as api from '../services/api'

vi.mock('../services/api', () => ({
  reportsApi: {
    monthlyTrend: vi.fn(),
  },
}))

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
})

function renderWithClient(ui: React.ReactElement) {
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

describe('MonthlyTrendChart', () => {
  beforeEach(() => {
    queryClient.clear()
  })

  it('renders the title once data is loaded', async () => {
    vi.mocked(api.reportsApi.monthlyTrend).mockResolvedValue([
      { month: '2026-05', income_cents: 500000, expense_cents: 120000 },
      { month: '2026-06', income_cents: 500000, expense_cents: 90000 },
    ])

    renderWithClient(<MonthlyTrendChart accountId="acc-1" />)

    await waitFor(() => {
      expect(screen.getByText('Verlauf (6 Monate)')).toBeInTheDocument()
    })
    expect(api.reportsApi.monthlyTrend).toHaveBeenCalledWith('acc-1', 6)
  })

  it('shows a loading state before data arrives', () => {
    vi.mocked(api.reportsApi.monthlyTrend).mockReturnValue(new Promise(() => {}))

    renderWithClient(<MonthlyTrendChart accountId="acc-1" />)

    expect(screen.getByText('Lade...')).toBeInTheDocument()
  })
})
