export interface Account {
  id: string
  name: string
  currency: string
  initial_balance_cents: number
  created_at: string
  archived_at: string | null
}

export interface AccountBalance {
  account_id: string
  account_name: string
  currency: string
  initial_balance_cents: number
  total_income_cents: number
  total_expense_cents: number
  balance_cents: number
}

export interface Category {
  id: string
  name: string
  type: 'INCOME' | 'EXPENSE'
  parent_id: string | null
  color: string | null
  icon: string | null
  created_at: string
  archived_at: string | null
}

export interface Transaction {
  id: string
  account_id: string
  type: 'INCOME' | 'EXPENSE'
  amount_cents: number
  category_id: string | null
  description: string | null
  date: string
  created_at: string
  idempotency_key: string | null
  reversed_by: string | null
  reverses_id: string | null
}

export interface TransactionList {
  items: Transaction[]
  total: number
  page: number
  page_size: number
}

export interface ExpenseByCategory {
  category_id: string
  category_name: string
  category_color: string
  category_icon: string
  total_cents: number
}

export interface IncomeVsExpense {
  total_income_cents: number
  total_expense_cents: number
  net_cents: number
}

export interface MonthlyTrendEntry {
  month: string
  income_cents: number
  expense_cents: number
}

export interface Debt {
  id: string
  account_id: string | null
  creditor: string
  counterparty: string | null
  name: string | null
  title: string | null
  type: 'OWED' | 'RECEIVABLE'
  amount_cents: number
  remaining_cents: number
  balance_cents: number | null
  paid_cents: number | null
  payment_count: number
  correction_cents: number
  is_overdue: boolean
  interest_rate: number | null
  due_date: string | null
  status: 'OPEN' | 'PAID' | 'CANCELLED' | 'OVERDUE'
  description: string | null
  note: string | null
  created_at: string
  archived_at: string | null
}

export interface DebtPayment {
  id: string
  debt_id: string
  amount_cents: number
  date: string
  note: string | null
  created_at: string
  idempotency_key: string | null
  /** Booking on an account; null means "recorded without account movement" */
  transaction_id: string | null
  cancelled_at: string | null
  cancel_reason: string | null
  is_cancelled: boolean
}

export interface DebtSummary {
  total_debt_cents: number
  total_receivable_cents: number
  open_debt_cents: number
  open_receivable_cents: number
  /** Sum of both open positions (not a net value) */
  total_open_cents: number
  /** Open receivables minus open debts */
  net_open_cents: number
  count: number
  open_count: number
  paid_count: number
  cancelled_count: number
  archived_count: number
}

export interface Reconciliation {
  id: string
  account_id: string
  reconciliation_date: string
  actual_balance_cents: number
  expected_balance_cents: number
  difference_cents: number
  note: string | null
  created_at: string
  /** Bookings that produced the expected balance at the time */
  basis_transaction_ids: string[]
}

export interface ExpectedBalance {
  account_id: string
  date: string
  expected_balance_cents: number
  transaction_count: number
}
