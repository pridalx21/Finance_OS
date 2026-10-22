import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { debtsApi } from '../services/api'
import type { Debt } from '../types'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'

function formatCHF(cents: number) {
  return new Intl.NumberFormat('de-CH', { style: 'currency', currency: 'CHF' }).format(cents / 100)
}

export default function DebtManager({ accountId }: { accountId?: string }) {
  const queryClient = useQueryClient()
  const [creditor, setCreditor] = useState('')
  const [amount, setAmount] = useState('')
  const [type, setType] = useState<'OWED' | 'RECEIVABLE'>('OWED')
  const [dueDate, setDueDate] = useState('')
  const [description, setDescription] = useState('')
  const [payAmounts, setPayAmounts] = useState<Record<string, string>>({})

  const { data: debts } = useQuery({
    queryKey: ['debts', accountId],
    queryFn: () => debtsApi.list(accountId ? { account_id: accountId } : {}),
  })

  const { data: summary } = useQuery({
    queryKey: ['debts', 'summary', accountId],
    queryFn: () => debtsApi.summary(accountId),
  })

  const createMutation = useMutation({
    mutationFn: () =>
      debtsApi.create({
        account_id: accountId,
        creditor: creditor.trim() || 'Unbekannt',
        type,
        amount_cents: Math.round(parseFloat(amount || '0') * 100),
        due_date: dueDate || undefined,
        description: description || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['debts'] })
      setCreditor('')
      setAmount('')
      setDueDate('')
      setDescription('')
    },
  })

  const payMutation = useMutation({
    mutationFn: ({ id, value }: { id: string; value: string }) =>
      debtsApi.pay(id, { amount_cents: Math.round(parseFloat(value || '0') * 100) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['debts'] }),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => debtsApi.delete(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['debts'] }),
  })

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault()
    if (!amount || parseFloat(amount) <= 0) return
    createMutation.mutate()
  }

  const handlePay = (debt: Debt) => {
    const value = payAmounts[debt.id]
    if (!value || parseFloat(value) <= 0) return
    payMutation.mutate({ id: debt.id, value })
    setPayAmounts((prev) => ({ ...prev, [debt.id]: '' }))
  }

  const openDebts = (debts ?? []).filter((d) => d.status !== 'PAID' && d.status !== 'CANCELLED')

  return (
    <Card>
      <CardHeader>
        <CardTitle>Schulden</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Zusammenfassung */}
        {summary && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <div className="p-3 rounded-md bg-muted/50">
              <p className="text-muted-foreground">Offene Schulden</p>
              <p className="font-semibold text-destructive">{formatCHF(summary.open_debt_cents)}</p>
            </div>
            <div className="p-3 rounded-md bg-muted/50">
              <p className="text-muted-foreground">Offene Forderungen</p>
              <p className="font-semibold text-success">{formatCHF(summary.open_receivable_cents)}</p>
            </div>
            <div className="p-3 rounded-md bg-muted/50">
              <p className="text-muted-foreground">Gesamt Schulden</p>
              <p className="font-semibold">{formatCHF(summary.total_debt_cents)}</p>
            </div>
            <div className="p-3 rounded-md bg-muted/50">
              <p className="text-muted-foreground">Bezahlt</p>
              <p className="font-semibold">{summary.paid_count}</p>
            </div>
          </div>
        )}

        {/* Neue Schuld */}
        <form onSubmit={handleCreate} className="grid grid-cols-1 md:grid-cols-5 gap-2 items-end">
          <div>
            <label className="text-xs text-muted-foreground">Gläubiger/Schuldner</label>
            <Input value={creditor} onChange={(e) => setCreditor(e.target.value)} placeholder="z. B. Bank" />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Betrag (CHF)</label>
            <Input type="number" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Typ</label>
            <select
              className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={type}
              onChange={(e) => setType(e.target.value as 'OWED' | 'RECEIVABLE')}
            >
              <option value="OWED">Schuld (ich schulde)</option>
              <option value="RECEIVABLE">Forderung (mir wird geschuldet)</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Fällig am</label>
            <Input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
          </div>
          <Button type="submit" disabled={createMutation.isPending}>
            {createMutation.isPending ? 'Wird angelegt...' : 'Hinzufügen'}
          </Button>
        </form>

        {/* Liste */}
        <div className="space-y-3">
          {openDebts.length === 0 && (
            <p className="text-sm text-muted-foreground">Keine offenen Schulden.</p>
          )}
          {openDebts.map((debt) => (
            <div key={debt.id} className="p-3 rounded-md bg-muted/50 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <div>
                  <p className="font-medium text-sm">
                    {debt.creditor}
                    <span className="ml-2 text-xs text-muted-foreground">
                      {debt.type === 'OWED' ? 'Schuld' : 'Forderung'}
                    </span>
                  </p>
                  {debt.description && (
                    <p className="text-xs text-muted-foreground">{debt.description}</p>
                  )}
                  {debt.due_date && (
                    <p className="text-xs text-muted-foreground">
                      Fällig: {new Date(debt.due_date).toLocaleDateString('de-CH')}
                    </p>
                  )}
                </div>
                <div className="text-right">
                  <p className="font-semibold text-sm">{formatCHF(debt.remaining_cents)}</p>
                  <p className="text-xs text-muted-foreground">von {formatCHF(debt.amount_cents)}</p>
                </div>
              </div>
              <div className="flex gap-2 items-center">
                <Input
                  type="number"
                  step="0.01"
                  placeholder="Betrag"
                  className="h-8 text-sm"
                  value={payAmounts[debt.id] || ''}
                  onChange={(e) =>
                    setPayAmounts((prev) => ({ ...prev, [debt.id]: e.target.value }))
                  }
                />
                <Button size="sm" variant="outline" onClick={() => handlePay(debt)} disabled={payMutation.isPending}>
                  Zahlen
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => deleteMutation.mutate(debt.id)}
                  disabled={deleteMutation.isPending}
                >
                  Archivieren
                </Button>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}