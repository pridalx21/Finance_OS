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
} from '../types'

const api = axios.create({
  baseURL: '/api',
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
  list: (type?: 'INCOME' | 'EXPENSE') =>
    api.get<Category[]>('/categories', { params: type ? { type } : {} }).then((r) => r.data),
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
}
