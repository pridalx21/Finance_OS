import { useQuery } from '@tanstack/react-query'
import { reportsApi } from '../services/api'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'

interface ExpensesByCategoryChartProps {
  accountId: string
}

export default function ExpensesByCategoryChart({ accountId }: ExpensesByCategoryChartProps) {
  const { data, isLoading } = useQuery({
    queryKey: ['expenses-by-category', accountId],
    queryFn: () => reportsApi.expensesByCategory(accountId),
    enabled: !!accountId,
  })

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Ausgaben nach Kategorie</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground">Lade...</p>
        </CardContent>
      </Card>
    )
  }

  if (!data || data.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Ausgaben nach Kategorie</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground">Keine Ausgaben vorhanden.</p>
        </CardContent>
      </Card>
    )
  }

  const formatCHF = (cents: number) =>
    new Intl.NumberFormat('de-CH', { style: 'currency', currency: 'CHF' }).format(cents / 100)

  const total = data.reduce((sum, item) => sum + item.total_cents, 0)

  const chartData = data.map((item) => ({
    name: item.category_name,
    value: item.total_cents / 100,
    color: item.category_color,
  }))

  return (
    <Card>
      <CardHeader>
        <CardTitle>Ausgaben nach Kategorie</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={chartData}
                cx="50%"
                cy="50%"
                innerRadius={60}
                outerRadius={90}
                paddingAngle={2}
                dataKey="value"
              >
                {chartData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.color} />
                ))}
              </Pie>
              <Tooltip
                formatter={(value) => formatCHF(Number(value) * 100)}
                contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155' }}
                labelStyle={{ color: '#f8fafc' }}
              />
              <Legend
                formatter={(value) => <span className="text-sm text-foreground">{value}</span>}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
        {/* Liste der Kategorien mit Beträgen */}
        <div className="mt-4 space-y-2">
          {data.map((item) => (
            <div key={item.category_id} className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2">
                <span
                  className="w-3 h-3 rounded-full"
                  style={{ backgroundColor: item.category_color }}
                />
                <span>{item.category_name}</span>
              </div>
              <div className="flex items-center gap-4">
                <span className="font-semibold">{formatCHF(item.total_cents)}</span>
                <span className="text-muted-foreground w-12 text-right">
                  {total > 0 ? Math.round((item.total_cents / total) * 100) : 0}%
                </span>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
