import axios from 'axios'
import type {
  Account,
  AccountBalance,
  Category,
  Transaction,
  TransactionList,
  ExpenseByCategory,
  IncomeVsExpense,
  MonthlyTrendEntry,
  WeeklyTrendEntry,
  WeeklyReport,
  MonthlyReport,
  Debt,
  DebtPayment,
  DebtSummary,
  Reconciliation,
  ExpectedBalance,
  Purchase,
  PurchaseItem,
  Product,
  Receipt,
} from '../types'

const api = axios.create({
  baseURL: `${import.meta.env.BASE_URL}api`,
  headers: { 'Content-Type': 'application/json' },
})

// Error interceptor
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response) {
      const status = error.response.status
      const detail = error.response.data?.detail || error.response.data?.message || 'Unbekannter Fehler'
      console.error(`API Error ${status}: ${detail}`)
      return Promise.reject(new Error(detail))
    }
    if (error.request) {
      console.error('Network Error: Keine Antwort vom Server')
      return Promise.reject(new Error('Server nicht erreichbar'))
    }
    return Promise.reject(error)
  }
)

// Accounts
export const accountsApi = {
  list: () => api.get<Account[]>('/accounts').then((r) => r.data),
  get: (id: string) => api.get<Account>(`/accounts/${id}`).then((r) => r.data),
  create: (data: { name: string; currency?: string; initial_balance_cents?: number }) =>
    api.post<Account>('/accounts', data).then((r) => r.data),
  balance: (id: string) => api.get<AccountBalance>(`/accounts/${id}/balance`).then((r) => r.data),
}

// Categories
export const categoriesApi = {
  list: (type?: 'INCOME' | 'EXPENSE', includeArchived?: boolean) =>
    api.get<Category[]>('/categories', { params: { ...(type ? { type } : {}), ...(includeArchived ? { include_archived: true } : {}) } }).then((r) => r.data),
  get: (id: string) => api.get<Category>(`/categories/${id}`).then((r) => r.data),
  create: (data: { name: string; type: 'INCOME' | 'EXPENSE'; color?: string; icon?: string }) =>
    api.post<Category>('/categories', data).then((r) => r.data),
  update: (id: string, data: Partial<Category>) =>
    api.patch<Category>(`/categories/${id}`, data).then((r) => r.data),
  seed: () => api.post<Category[]>('/categories/seed').then((r) => r.data),
}

// Transactions
export const transactionsApi = {
  list: (params: {
    account_id: string
    type?: 'INCOME' | 'EXPENSE'
    category_id?: string
    limit?: number
    offset?: number
  }) => api.get<TransactionList>('/transactions', { params }).then((r) => r.data),
  get: (id: string) => api.get<Transaction>(`/transactions/${id}`).then((r) => r.data),
  create: (data: {
    account_id: string
    type: 'INCOME' | 'EXPENSE'
    amount_cents: number
    category_id?: string
    description?: string
    date?: string
    idempotency_key?: string
  }) => api.post<Transaction>('/transactions', data).then((r) => r.data),
  reverse: (id: string) => api.post<Transaction>(`/transactions/${id}/reverse`).then((r) => r.data),
}

// Reports
export const reportsApi = {
  expensesByCategory: (accountId: string) =>
    api.get<ExpenseByCategory[]>('/reports/expenses-by-category', { params: { account_id: accountId } }).then((r) => r.data),
  incomeVsExpense: (accountId: string) =>
    api.get<IncomeVsExpense>('/reports/income-vs-expense', { params: { account_id: accountId } }).then((r) => r.data),
  monthlyTrend: (accountId: string, months = 6) =>
    api.get<MonthlyTrendEntry[]>('/reports/monthly-trend', { params: { account_id: accountId, months } }).then((r) => r.data),
  weekly: (accountId: string, week?: string) =>
    api.get<WeeklyReport>('/reports/weekly', { params: { account_id: accountId, ...(week ? { week } : {}) } }).then((r) => r.data),
  weeklyTrend: (accountId: string, weeks = 8) =>
    api.get<WeeklyTrendEntry[]>('/reports/weekly-trend', { params: { account_id: accountId, weeks } }).then((r) => r.data),
  monthly: (accountId: string, month?: string) =>
    api.get<MonthlyReport>('/reports/monthly', { params: { account_id: accountId, ...(month ? { month } : {}) } }).then((r) => r.data),
}

// Debts
export const debtsApi = {
  list: (params?: { account_id?: string; status?: string; type?: string; include_archived?: boolean }) =>
    api.get<Debt[]>('/debts', { params }).then((r) => r.data),
  get: (id: string) => api.get<Debt>(`/debts/${id}`).then((r) => r.data),
  create: (data: {
    account_id?: string
    creditor?: string
    counterparty?: string
    name?: string
    type?: string
    amount_cents: number
    interest_rate?: number
    due_date?: string
    status?: string
    description?: string
    note?: string
    idempotency_key?: string
  }) => api.post<Debt>('/debts', data).then((r) => r.data),
  update: (id: string, data: Partial<Debt>) => api.patch<Debt>(`/debts/${id}`, data).then((r) => r.data),
  delete: (id: string) => api.delete(`/debts/${id}`).then((r) => r.data),
  summary: (accountId?: string) =>
    api.get<DebtSummary>('/debts/summary', { params: accountId ? { account_id: accountId } : {} }).then((r) => r.data),
  payments: (debtId: string, includeCancelled = true) =>
    api
      .get<DebtPayment[]>(`/debts/${debtId}/payments`, {
        params: { include_cancelled: includeCancelled },
      })
      .then((r) => r.data),
  pay: (
    debtId: string,
    data: {
      amount_cents: number
      date?: string
      note?: string
      /** Book the payment on an account (expense for a debt, income for a receivable) */
      create_transaction?: boolean
      account_id?: string
      idempotency_key?: string
    },
  ) => api.post<DebtPayment>(`/debts/${debtId}/payments`, data).then((r) => r.data),
  cancelPayment: (paymentId: string, reason?: string) =>
    api
      .post<DebtPayment>(`/debts/payments/${paymentId}/cancel`, null, {
        params: reason ? { reason } : {},
      })
      .then((r) => r.data),
}

// Reconciliation
export const reconciliationsApi = {
  list: (accountId?: string) =>
    api.get<Reconciliation[]>('/reconciliation', { params: accountId ? { account_id: accountId } : {} }).then((r) => r.data),
  create: (data: {
    account_id: string
    actual_balance_cents: number
    date?: string
    note?: string
    create_transaction?: boolean
    idempotency_key?: string
  }) => api.post<Reconciliation>('/reconciliation', data).then((r) => r.data),
  /** System balance for a cut-off date (today when no date is given) */
  expectedBalance: (accountId: string, date?: string) =>
    api
      .get<ExpectedBalance>('/reconciliation/expected-balance', {
        params: { account_id: accountId, ...(date ? { date } : {}) },
      })
      .then((r) => r.data),
}

// Products
export const productsApi = {
  list: () => api.get<Product[]>('/purchases/products').then((r) => r.data),
  create: (data: { gtin?: string; normalized_name: string; brand?: string; package_size?: string; default_category_id?: string }) =>
    api.post<Product>('/purchases/products', data).then((r) => r.data),
  byGtin: (gtin: string) => api.get<Product>(`/purchases/products/by-gtin/${gtin}`).then((r) => r.data),
}

// Receipts
export const receiptsApi = {
  create: (data: { file_reference?: string; ocr_text?: string; merchant?: string; purchased_at?: string; total_cents?: number; currency?: string }) =>
    api.post<Receipt>('/purchases/receipts', data).then((r) => r.data),
  get: (id: string) => api.get<Receipt>(`/purchases/receipts/${id}`).then((r) => r.data),
}

// Purchases
export const purchasesApi = {
  list: (params?: { account_id?: string; status?: string; include_archived?: boolean }) =>
    api.get<Purchase[]>('/purchases', { params }).then((r) => r.data),
  get: (id: string) => api.get<Purchase>(`/purchases/${id}`).then((r) => r.data),
  create: (data: any) => api.post<Purchase>('/purchases', data).then((r) => r.data),
  update: (id: string, data: any) => api.patch<Purchase>(`/purchases/${id}`, data).then((r) => r.data),
  post: (id: string) => api.post<Purchase>(`/purchases/${id}/post`).then((r) => r.data),
  delete: (id: string) => api.delete(`/purchases/${id}`).then((r) => r.data),
  setItemCategory: (itemId: string, params: { category_id?: string; purpose?: string; project_ref?: string; save_rule?: boolean; rule_scope?: string; match_value?: string }) =>
    api.patch<PurchaseItem>(`/purchases/items/${itemId}/category`, null, { params }).then((r) => r.data),
  merge: (data: { barcode_gtins: string[]; ocr_lines: any[] }) =>
    api.post<any[]>('/purchases/merge', data).then((r) => r.data),
  rules: (includeArchived?: boolean) =>
    api.get<any[]>('/purchases/rules', { params: includeArchived ? { include_archived: true } : {} }).then((r) => r.data),
  createRule: (data: any) => api.post<any>('/purchases/rules', data).then((r) => r.data),
}
