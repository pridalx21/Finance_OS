import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ExpensesByCategoryChart from './ExpensesByCategoryChart'
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

describe('ExpensesByCategoryChart', () => {
  beforeEach(() => {
    queryClient.clear()
  })

  it('lists each category with amount and share', async () => {
    vi.mocked(api.reportsApi.expensesByCategory).mockResolvedValue([
      {
        category_id: 'c1',
        category_name: 'Lebensmittel',
        category_color: '#ef4444',
        category_icon: 'shopping-cart',
        total_cents: 7500,
      },
      {
        category_id: 'c2',
        category_name: 'Transport',
        category_color: '#eab308',
        category_icon: 'car',
        total_cents: 2500,
      },
    ])

    renderWithClient(<ExpensesByCategoryChart accountId="acc-1" />)

    await waitFor(() => {
      expect(screen.getByText('Lebensmittel')).toBeInTheDocument()
    })
    expect(screen.getByText('Transport')).toBeInTheDocument()
    expect(screen.getByText('CHF 75.00')).toBeInTheDocument()
    expect(screen.getByText('CHF 25.00')).toBeInTheDocument()
    expect(screen.getByText('75%')).toBeInTheDocument()
    expect(screen.getByText('25%')).toBeInTheDocument()
  })

  it('shows empty state when no expenses exist', async () => {
    vi.mocked(api.reportsApi.expensesByCategory).mockResolvedValue([])

    renderWithClient(<ExpensesByCategoryChart accountId="acc-1" />)

    await waitFor(() => {
      expect(screen.getByText('Keine Ausgaben vorhanden.')).toBeInTheDocument()
    })
  })
})
