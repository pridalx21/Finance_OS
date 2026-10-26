import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { transactionsApi, categoriesApi, accountsApi } from '../services/api'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { parseAmountToCents } from '../lib/money'

export default function QuickExpense() {
  const [amounts, setAmounts] = useState<Record<string, string>>({})
  const queryClient = useQueryClient()

  const { data: accounts } = useQuery({
    queryKey: ['accounts'],
    queryFn: accountsApi.list,
  })

  const { data: categories } = useQuery({
    queryKey: ['categories', 'EXPENSE'],
    queryFn: () => categoriesApi.list('EXPENSE'),
  })

  const mutation = useMutation({
    mutationFn: ({ categoryId, amount }: { categoryId: string; amount: string }) => {
      const cents = parseAmountToCents(amount)
      if (cents === null || cents <= 0) {
        throw new Error('Bitte einen Betrag grösser als 0 eingeben.')
      }
      return transactionsApi.create({
        account_id: accounts?.[0]?.id || '',
        type: 'EXPENSE',
        amount_cents: cents,
        category_id: categoryId,
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['transactions'] })
      queryClient.invalidateQueries({ queryKey: ['balance'] })
      queryClient.invalidateQueries({ queryKey: ['reports'] })
    },
  })

  const handleQuickAdd = (categoryId: string) => {
    const amount = amounts[categoryId]
    const cents = amount ? parseAmountToCents(amount) : null
    if (cents === null || cents <= 0) return
    mutation.mutate({ categoryId, amount })
    setAmounts((prev) => ({ ...prev, [categoryId]: '' }))
  }

  if (!categories || categories.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Schnellausgabe</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground">Keine Ausgaben-Kategorien vorhanden.</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Schnellausgabe nach Kategorie</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {categories.map((cat) => (
            <div key={cat.id} className="flex items-center gap-2">
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className="w-2 h-2 rounded-full"
                    style={{ backgroundColor: cat.color || '#6b7280' }}
                  />
                  <span className="text-sm font-medium">{cat.name}</span>
                </div>
                <Input
                  type="text"
                  inputMode="decimal"
                  placeholder="0.00"
                  aria-label={`Betrag für ${cat.name}`}
                  value={amounts[cat.id] || ''}
                  onChange={(e) =>
                    setAmounts((prev) => ({ ...prev, [cat.id]: e.target.value }))
                  }
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleQuickAdd(cat.id)
                  }}
                  className="h-8 text-sm"
                />
              </div>
              <Button
                size="sm"
                variant="outline"
                className="mt-5"
                onClick={() => handleQuickAdd(cat.id)}
                disabled={mutation.isPending}
              >
                +
              </Button>
            </div>
          ))}
        </div>
        {mutation.error && (
          <p className="text-sm text-destructive mt-3" role="alert">
            {mutation.error.message}
          </p>
        )}
      </CardContent>
    </Card>
  )
}
