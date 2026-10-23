import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DebtManager from './DebtManager'
import * as api from '../services/api'
import type { Debt, DebtSummary } from '../types'

vi.mock('../services/api', () => ({
  debtsApi: {
    list: vi.fn(),
    summary: vi.fn(),
    create: vi.fn(),
    pay: vi.fn(),
    payments: vi.fn(),
    cancelPayment: vi.fn(),
    delete: vi.fn(),
  },
}))

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
})

function renderWithClient(ui: React.ReactElement) {
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

const debt: Debt = {
  id: 'debt-1',
  account_id: 'acc-1',
  creditor: 'Bank',
  counterparty: 'Bank',
  name: 'Bank',
  title: 'Bank',
  type: 'OWED',
  amount_cents: 10000,
  remaining_cents: 10000,
  balance_cents: 10000,
  paid_cents: 0,
  payment_count: 0,
  correction_cents: 0,
  is_overdue: false,
  interest_rate: null,
  due_date: null,
  status: 'OPEN',
  description: null,
  note: null,
  created_at: '2026-05-01T00:00:00',
  archived_at: null,
}

const summary: DebtSummary = {
  total_debt_cents: 10000,
  total_receivable_cents: 0,
  open_debt_cents: 10000,
  open_receivable_cents: 0,
  total_open_cents: 10000,
  net_open_cents: -10000,
  count: 1,
  open_count: 1,
  paid_count: 0,
  cancelled_count: 0,
  archived_count: 0,
}

describe('DebtManager', () => {
  beforeEach(() => {
    queryClient.clear()
    vi.mocked(api.debtsApi.list).mockResolvedValue([debt])
    vi.mocked(api.debtsApi.summary).mockResolvedValue(summary)
    vi.mocked(api.debtsApi.payments).mockResolvedValue([])
  })

  it('shows the open debts and the summary', async () => {
    renderWithClient(<DebtManager accountId="acc-1" />)

    await waitFor(() => {
      expect(screen.getByText('Bank')).toBeInTheDocument()
    })
    // The remaining amount appears in the list and in the summary
    expect(screen.getAllByText('100.00 CHF').length).toBeGreaterThan(0)
    expect(screen.getByText('Offene Schulden')).toBeInTheDocument()
  })

  it('sends the amount in Rappen without floating point errors', async () => {
    vi.mocked(api.debtsApi.create).mockResolvedValue(debt)
    const user = userEvent.setup()
    renderWithClient(<DebtManager accountId="acc-1" />)

    await waitFor(() => expect(screen.getByText('Bank')).toBeInTheDocument())

    await user.type(screen.getByLabelText('Gläubiger/Schuldner'), 'Mami')
    await user.type(screen.getByLabelText('Betrag (CHF)'), '8.115')
    await user.click(screen.getByRole('button', { name: 'Hinzufügen' }))

    await waitFor(() => {
      expect(api.debtsApi.create).toHaveBeenCalledWith(
        expect.objectContaining({ amount_cents: 812, creditor: 'Mami' }),
      )
    })
  })

  it('refuses a debt without a counterparty', async () => {
    const user = userEvent.setup()
    renderWithClient(<DebtManager accountId="acc-1" />)

    await waitFor(() => expect(screen.getByText('Bank')).toBeInTheDocument())

    await user.type(screen.getByLabelText('Betrag (CHF)'), '10.00')
    await user.click(screen.getByRole('button', { name: 'Hinzufügen' }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Gläubiger')
    })
    expect(api.debtsApi.create).not.toHaveBeenCalled()
  })

  it('shows the error message of the server', async () => {
    vi.mocked(api.debtsApi.create).mockRejectedValue(new Error('Betrag übersteigt die Restschuld'))
    const user = userEvent.setup()
    renderWithClient(<DebtManager accountId="acc-1" />)

    await waitFor(() => expect(screen.getByText('Bank')).toBeInTheDocument())

    await user.type(screen.getByLabelText('Gläubiger/Schuldner'), 'Bank')
    await user.type(screen.getByLabelText('Betrag (CHF)'), '10.00')
    await user.click(screen.getByRole('button', { name: 'Hinzufügen' }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Betrag übersteigt die Restschuld')
    })
  })

  it('records a partial payment', async () => {
    vi.mocked(api.debtsApi.pay).mockResolvedValue({
      id: 'pay-1',
      debt_id: 'debt-1',
      amount_cents: 3000,
      date: '2026-05-02T00:00:00',
      note: null,
      created_at: '2026-05-02T00:00:00',
      idempotency_key: 'key-1',
      transaction_id: null,
      cancelled_at: null,
      cancel_reason: null,
      is_cancelled: false,
    })
    const user = userEvent.setup()
    renderWithClient(<DebtManager accountId="acc-1" />)

    await waitFor(() => expect(screen.getByText('Bank')).toBeInTheDocument())

    await user.type(screen.getByLabelText('Zahlungsbetrag für Bank'), '30.00')
    await user.click(screen.getByRole('button', { name: 'Zahlen' }))

    await waitFor(() => {
      expect(api.debtsApi.pay).toHaveBeenCalledWith(
        'debt-1',
        expect.objectContaining({ amount_cents: 3000 }),
      )
    })
  })

  it('shows the payments of a debt including cancelled ones', async () => {
    vi.mocked(api.debtsApi.payments).mockResolvedValue([
      {
        id: 'pay-1',
        debt_id: 'debt-1',
        amount_cents: 3000,
        date: '2026-05-02T00:00:00',
        note: null,
        created_at: '2026-05-02T00:00:00',
        idempotency_key: null,
        transaction_id: 'tx-1',
        cancelled_at: null,
        cancel_reason: null,
        is_cancelled: false,
      },
    ])
    const user = userEvent.setup()
    renderWithClient(<DebtManager accountId="acc-1" />)

    await waitFor(() => expect(screen.getByText('Bank')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Zahlungen anzeigen' }))

    await waitFor(() => {
      expect(screen.getByText(/30\.00 CHF/)).toBeInTheDocument()
    })
    expect(screen.getByText(/gebucht/)).toBeInTheDocument()
  })
})
