import { useQuery } from '@tanstack/react-query'
import { transactionsApi, categoriesApi } from '../services/api'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'


export default function TransactionList({ accountId }: { accountId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['transactions', accountId],
    queryFn: () => transactionsApi.list({ account_id: accountId, limit: 20 }),
    enabled: !!accountId,
  })

  const { data: categories } = useQuery({
    queryKey: ['categories'],
    queryFn: () => categoriesApi.list(),
  })

  const categoryMap = new Map(categories?.map((c) => [c.id, c]) || [])

  const formatCHF = (cents: number) =>
    new Intl.NumberFormat('de-CH', { style: 'currency', currency: 'CHF' }).format(cents / 100)

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr)
    return date.toLocaleDateString('de-CH', { day: '2-digit', month: '2-digit', year: 'numeric' })
  }

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Letzte Transaktionen</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground">Lade...</p>
        </CardContent>
      </Card>
    )
  }

  if (!data || data.items.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Letzte Transaktionen</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground">Keine Transaktionen vorhanden.</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Letzte Transaktionen</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {data.items.map((txn) => {
            const cat = txn.category_id ? categoryMap.get(txn.category_id) : null
            return (
              <div
                key={txn.id}
                className="flex items-center justify-between p-3 rounded-md bg-muted/50 hover:bg-muted transition-colors"
              >
                <div className="flex items-center gap-3">
                  <div
                    className="w-2 h-2 rounded-full"
                    style={{ backgroundColor: cat?.color || '#6b7280' }}
                  />
                  <div>
                    <p className="text-sm font-medium">
                      {txn.description || cat?.name || (txn.type === 'INCOME' ? 'Einnahme' : 'Ausgabe')}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {formatDate(txn.date)}
                      {cat && ` · ${cat.name}`}
                    </p>
                  </div>
                </div>
                <span
                  className={`font-semibold text-sm ${
                    txn.type === 'INCOME' ? 'text-success' : 'text-destructive'
                  }`}
                >
                  {txn.type === 'INCOME' ? '+' : '-'}{formatCHF(txn.amount_cents)}
                </span>
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}
