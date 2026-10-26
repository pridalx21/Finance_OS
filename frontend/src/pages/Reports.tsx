import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { accountsApi, reportsApi } from '../services/api'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'

function formatCHF(cents: number): string {
  return new Intl.NumberFormat('de-CH', { style: 'currency', currency: 'CHF' }).format(cents / 100)
}

function currentWeek(): string {
  const d = new Date()
  const date = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()))
  const dayNum = date.getUTCDay() || 7
  date.setUTCDate(date.getUTCDate() + 4 - dayNum)
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1))
  const weekNo = Math.ceil((((date.getTime() - yearStart.getTime()) / 86400000) + 1) / 7)
  return `${date.getUTCFullYear()}-W${String(weekNo).padStart(2, '0')}`
}

function currentMonth(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

export default function Reports() {
  const { data: accounts } = useQuery({
    queryKey: ['accounts'],
    queryFn: accountsApi.list,
  })

  const [selectedAccountId, setSelectedAccountId] = useState<string>('')
  const accountId = selectedAccountId || accounts?.[0]?.id || ''
  const [mode, setMode] = useState<'week' | 'month'>('month')
  const [week, setWeek] = useState<string>(currentWeek())
  const [month, setMonth] = useState<string>(currentMonth())

  const weeklyReportQuery = useQuery({
    queryKey: ['weekly-report', accountId, week],
    queryFn: () => reportsApi.weekly(accountId, week),
    enabled: !!accountId && mode === 'week',
  })

  const monthlyReportQuery = useQuery({
    queryKey: ['monthly-report', accountId, month],
    queryFn: () => reportsApi.monthly(accountId, month),
    enabled: !!accountId && mode === 'month',
  })

  const weeklyTrendQuery = useQuery({
    queryKey: ['weekly-trend', accountId, 8],
    queryFn: () => reportsApi.weeklyTrend(accountId, 8),
    enabled: !!accountId && mode === 'week',
  })

  const monthlyTrendQuery = useQuery({
    queryKey: ['monthly-trend', accountId, 8],
    queryFn: () => reportsApi.monthlyTrend(accountId, 8),
    enabled: !!accountId && mode === 'month',
  })

  const report = mode === 'week' ? weeklyReportQuery.data : monthlyReportQuery.data
  const isLoading = mode === 'week' ? weeklyReportQuery.isLoading : monthlyReportQuery.isLoading
  const trendData = mode === 'week' ? weeklyTrendQuery.data : monthlyTrendQuery.data

  const trendChartData = (trendData ?? []).map((entry) => ({
    period: 'week' in entry ? entry.week : entry.month,
    Einnahmen: ('income_cents' in entry ? entry.income_cents : 0) / 100,
    Ausgaben: ('expense_cents' in entry ? entry.expense_cents : 0) / 100,
  }))

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border bg-card/50 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Berichte</h1>
            <p className="text-muted-foreground text-sm">Wochen- und Monatsübersichten</p>
          </div>
          <div className="flex gap-2 items-center">
            {accounts && accounts.length > 1 && (
              <select
                className="border border-border rounded-md px-2 py-1 bg-background text-foreground"
                value={accountId}
                onChange={(e) => setSelectedAccountId(e.target.value)}
              >
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto p-6 space-y-6">
        <div className="flex gap-2">
          <button
            className={`px-3 py-1 rounded-md border ${mode === 'week' ? 'bg-primary text-primary-foreground' : 'bg-background'}`}
            onClick={() => setMode('week')}
          >
            Woche
          </button>
          <button
            className={`px-3 py-1 rounded-md border ${mode === 'month' ? 'bg-primary text-primary-foreground' : 'bg-background'}`}
            onClick={() => setMode('month')}
          >
            Monat
          </button>
          <div className="ml-auto">
            {mode === 'week' ? (
              <input
                type="week"
                className="border border-border rounded-md px-2 py-1 bg-background text-foreground"
                value={week}
                onChange={(e) => setWeek(e.target.value)}
              />
            ) : (
              <input
                type="month"
                className="border border-border rounded-md px-2 py-1 bg-background text-foreground"
                value={month}
                onChange={(e) => setMonth(e.target.value)}
              />
            )}
          </div>
        </div>

        {isLoading && (
          <Card>
            <CardContent className="p-6">
              <p className="text-muted-foreground">Lade...</p>
            </CardContent>
          </Card>
        )}

        {report && (
          <>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <Card>
                <CardHeader>
                  <CardTitle>Einnahmen</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-success font-semibold">{formatCHF(report.total_income_cents)}</p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle>Ausgaben</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-destructive font-semibold">{formatCHF(report.total_expense_cents)}</p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle>Netto</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className={`font-semibold ${report.net_cents >= 0 ? 'text-success' : 'text-destructive'}`}>
                    {formatCHF(report.net_cents)}
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle>Transaktionen</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="font-semibold">{report.transaction_count}</p>
                </CardContent>
              </Card>
            </div>

            {report.previous_period && (
              <Card>
                <CardHeader>
                  <CardTitle>Vergleich zur Vorperiode ({report.previous_period})</CardTitle>
                </CardHeader>
                <CardContent className="grid grid-cols-3 gap-4 text-center text-sm">
                  <div>
                    <p className="text-muted-foreground">Einnahmen</p>
                    <p className={report.total_income_cents - report.previous_total_income_cents >= 0 ? 'text-success' : 'text-destructive'}>
                      {formatCHF(report.total_income_cents - report.previous_total_income_cents)}
                    </p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Ausgaben</p>
                    <p className={report.total_expense_cents - report.previous_total_expense_cents <= 0 ? 'text-success' : 'text-destructive'}>
                      {formatCHF(report.total_expense_cents - report.previous_total_expense_cents)}
                    </p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Netto</p>
                    <p className={report.net_cents - report.previous_net_cents >= 0 ? 'text-success' : 'text-destructive'}>
                      {formatCHF(report.net_cents - report.previous_net_cents)}
                    </p>
                  </div>
                </CardContent>
              </Card>
            )}

            <Card>
              <CardHeader>
                <CardTitle>Ausgaben nach Kategorie</CardTitle>
              </CardHeader>
              <CardContent>
                {report.expenses_by_category.length === 0 ? (
                  <p className="text-muted-foreground">Keine Ausgaben in dieser Periode.</p>
                ) : (
                  <ul className="space-y-2">
                    {report.expenses_by_category.map((c) => (
                      <li key={c.category_id} className="flex items-center justify-between">
                        <span className="flex items-center gap-2">
                          <span className="inline-block w-3 h-3 rounded-full" style={{ backgroundColor: c.category_color }} />
                          {c.category_name}
                        </span>
                        <span className="font-semibold">{formatCHF(c.total_cents)}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </>
        )}

        {trendChartData.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Verlauf (letzte 8 Perioden)</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={trendChartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="period" stroke="#94a3b8" />
                    <YAxis stroke="#94a3b8" tickFormatter={(v) => `CHF ${v}`} />
                    <Tooltip formatter={(value) => formatCHF(Number(value) * 100)} />
                    <Bar dataKey="Einnahmen" fill="#22c55e" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="Ausgaben" fill="#ef4444" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>
        )}
      </main>
    </div>
  )
}