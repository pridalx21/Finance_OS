import { useQuery } from '@tanstack/react-query'
import { reportsApi } from '../services/api'
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

interface IncomeVsExpenseChartProps {
  accountId: string
}

export default function IncomeVsExpenseChart({ accountId }: IncomeVsExpenseChartProps) {
  const { data, isLoading } = useQuery({
    queryKey: ['income-vs-expense', accountId],
    queryFn: () => reportsApi.incomeVsExpense(accountId),
    enabled: !!accountId,
  })

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Einnahmen vs. Ausgaben</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground">Lade...</p>
        </CardContent>
      </Card>
    )
  }

  if (!data) return null

  const formatCHF = (cents: number) =>
    new Intl.NumberFormat('de-CH', { style: 'currency', currency: 'CHF' }).format(cents / 100)

  const chartData = [
    {
      name: 'Einnahmen',
      Betrag: data.total_income_cents / 100,
    },
    {
      name: 'Ausgaben',
      Betrag: data.total_expense_cents / 100,
    },
  ]

  return (
    <Card>
      <CardHeader>
        <CardTitle>Einnahmen vs. Ausgaben</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="name" stroke="#94a3b8" />
              <YAxis stroke="#94a3b8" tickFormatter={(v) => `CHF ${v}`} />
              <Tooltip
                formatter={(value) => formatCHF(Number(value) * 100)}
                contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155' }}
                labelStyle={{ color: '#f8fafc' }}
              />
              <Bar dataKey="Betrag" fill="#3b82f6" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-4 grid grid-cols-3 gap-4 text-center text-sm">
          <div>
            <p className="text-muted-foreground">Einnahmen</p>
            <p className="text-success font-semibold">{formatCHF(data.total_income_cents)}</p>
          </div>
          <div>
            <p className="text-muted-foreground">Ausgaben</p>
            <p className="text-destructive font-semibold">{formatCHF(data.total_expense_cents)}</p>
          </div>
          <div>
            <p className="text-muted-foreground">Netto</p>
            <p className={`font-semibold ${data.net_cents >= 0 ? 'text-success' : 'text-destructive'}`}>
              {formatCHF(data.net_cents)}
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
