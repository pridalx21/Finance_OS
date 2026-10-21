import { useQuery } from '@tanstack/react-query'
import { reportsApi } from '../services/api'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'

interface MonthlyTrendChartProps {
  accountId: string
}

function formatMonth(key: string): string {
  const [year, month] = key.split('-').map(Number)
  return new Date(year, month - 1, 1).toLocaleDateString('de-CH', {
    month: 'short',
    year: '2-digit',
  })
}

export default function MonthlyTrendChart({ accountId }: MonthlyTrendChartProps) {
  const { data, isLoading } = useQuery({
    queryKey: ['monthly-trend', accountId],
    queryFn: () => reportsApi.monthlyTrend(accountId, 6),
    enabled: !!accountId,
  })

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Verlauf (6 Monate)</CardTitle>
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

  const chartData = data.map((entry) => ({
    month: formatMonth(entry.month),
    Einnahmen: entry.income_cents / 100,
    Ausgaben: entry.expense_cents / 100,
  }))

  return (
    <Card>
      <CardHeader>
        <CardTitle>Verlauf (6 Monate)</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="month" stroke="#94a3b8" />
              <YAxis stroke="#94a3b8" tickFormatter={(v) => `CHF ${v}`} />
              <Tooltip
                formatter={(value) => formatCHF(Number(value) * 100)}
                contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155' }}
                labelStyle={{ color: '#f8fafc' }}
              />
              <Legend
                formatter={(value) => <span className="text-sm text-foreground">{value}</span>}
              />
              <Line
                type="monotone"
                dataKey="Einnahmen"
                stroke="#22c55e"
                strokeWidth={2}
                dot={{ r: 3 }}
              />
              <Line
                type="monotone"
                dataKey="Ausgaben"
                stroke="#ef4444"
                strokeWidth={2}
                dot={{ r: 3 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  )
}
