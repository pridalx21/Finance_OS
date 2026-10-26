import { useQuery } from '@tanstack/react-query'
import { accountsApi } from '../services/api'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'

interface BalanceCardProps {
  accountId: string
}

export default function BalanceCard({ accountId }: BalanceCardProps) {
  const { data: balance, isLoading } = useQuery({
    queryKey: ['balance', accountId],
    queryFn: () => accountsApi.balance(accountId),
    enabled: !!accountId,
  })

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Kontostand</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground">Lade...</p>
        </CardContent>
      </Card>
    )
  }

  if (!balance) return null

  const formatCHF = (cents: number) =>
    new Intl.NumberFormat('de-CH', { style: 'currency', currency: 'CHF' }).format(cents / 100)

  return (
    <Card>
      <CardHeader>
        <CardTitle>{balance.account_name}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="text-3xl sm:text-4xl font-bold break-words">{formatCHF(balance.balance_cents)}</div>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-muted-foreground">Einnahmen</p>
            <p className="text-success font-semibold">{formatCHF(balance.total_income_cents)}</p>
          </div>
          <div>
            <p className="text-muted-foreground">Ausgaben</p>
            <p className="text-destructive font-semibold">{formatCHF(balance.total_expense_cents)}</p>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
