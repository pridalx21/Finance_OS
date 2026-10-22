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
}

export interface DebtSummary {
  total_debt_cents: number
  total_receivable_cents: number
  open_debt_cents: number
  open_receivable_cents: number
  total_open_cents: number
  count: number
  open_count: number
  paid_count: number
}
