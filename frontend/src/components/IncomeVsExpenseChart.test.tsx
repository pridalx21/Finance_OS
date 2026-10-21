import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import IncomeVsExpenseChart from './IncomeVsExpenseChart'
import * as api from '../services/api'

vi.mock('../services/api', () => ({
  reportsApi: {
    incomeVsExpense: vi.fn(),
    expensesByCategory: vi.fn(),
  },
}))

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
})

function renderWithClient(ui: React.ReactElement) {
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

describe('IncomeVsExpenseChart', () => {
  beforeEach(() => {
    queryClient.clear()
  })

  it('shows totals for income and expense', async () => {
    vi.mocked(api.reportsApi.incomeVsExpense).mockResolvedValue({
      total_income_cents: 500000,
      total_expense_cents: 15000,
      net_cents: 485000,
    })

    renderWithClient(<IncomeVsExpenseChart accountId="acc-1" />)

    await waitFor(() => {
      expect(screen.getByText(/150\.00/)).toBeInTheDocument()
    })
    expect(screen.getByText('Einnahmen vs. Ausgaben')).toBeInTheDocument()
    expect(screen.getByText(/5.?000\.00/)).toBeInTheDocument()
  })
})
