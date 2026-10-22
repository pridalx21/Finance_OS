import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { accountsApi, categoriesApi } from '../services/api'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import BalanceCard from '../components/BalanceCard'
import AccountForm from '../components/AccountForm'
import TransactionForm from '../components/TransactionForm'
import QuickExpense from '../components/QuickExpense'
import CategoryManager from '../components/CategoryManager'
import DebtManager from '../components/DebtManager'
import TransactionList from '../components/TransactionList'
import IncomeVsExpenseChart from '../components/IncomeVsExpenseChart'
import ExpensesByCategoryChart from '../components/ExpensesByCategoryChart'
import MonthlyTrendChart from '../components/MonthlyTrendChart'

export default function Dashboard() {
  const queryClient = useQueryClient()
  const { data: accounts, isLoading } = useQuery({
    queryKey: ['accounts'],
    queryFn: accountsApi.list,
  })

  const { data: categories } = useQuery({
    queryKey: ['categories'],
    queryFn: () => categoriesApi.list(),
  })

  const account = accounts?.[0]

  const seedMutation = useMutation({
    mutationFn: categoriesApi.seed,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['categories'] })
    },
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <p className="text-muted-foreground">Lade...</p>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border bg-card/50 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Finance OS</h1>
            <p className="text-muted-foreground text-sm">Persönliches Finanzsystem</p>
          </div>
          <div className="flex gap-2">
            {!account && <AccountForm />}
            {account && (
              <>
                <TransactionForm type="INCOME" />
                <TransactionForm type="EXPENSE" />
              </>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto p-6 space-y-6">
        {!account ? (
          <Card>
            <CardHeader>
              <CardTitle>Willkommen bei Finance OS</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-muted-foreground">
                Erstelle ein Konto, um mit der Verwaltung deiner Finanzen zu beginnen.
              </p>
              <AccountForm trigger={<Button>Konto anlegen</Button>} />
            </CardContent>
          </Card>
        ) : (
          <>
            {/* Kontostand */}
            <BalanceCard accountId={account.id} />

            {/* Charts */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <IncomeVsExpenseChart accountId={account.id} />
              <ExpensesByCategoryChart accountId={account.id} />
            </div>

            {/* Verlauf */}
            <MonthlyTrendChart accountId={account.id} />

            {/* Schnellausgabe */}
            <QuickExpense />

            {/* Kategorien verwalten */}
            <CategoryManager />

            {/* Schulden verwalten */}
            <DebtManager accountId={account.id} />

            {/* Letzte Transaktionen */}
            <TransactionList accountId={account.id} />
          </>
        )}

        {/* Kategorien seeden (falls leer) */}
        {categories && categories.length === 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Keine Kategorien</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-muted-foreground mb-4">
                Es sind noch keine Kategorien vorhanden. Möchtest du die Standard-Kategorien anlegen?
              </p>
              <Button onClick={() => seedMutation.mutate()} disabled={seedMutation.isPending}>
                {seedMutation.isPending ? 'Wird angelegt...' : 'Standard-Kategorien anlegen'}
              </Button>
            </CardContent>
          </Card>
        )}
      </main>
    </div>
  )
}
