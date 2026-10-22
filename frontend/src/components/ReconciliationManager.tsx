import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { reconciliationsApi, accountsApi } from '../services/api'
import type { Reconciliation } from '../types'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'

function formatCHF(cents: number) {
  return new Intl.NumberFormat('de-CH', { style: 'currency', currency: 'CHF' }).format(cents / 100)
}

export default function ReconciliationManager({ accountId }: { accountId: string }) {
  const queryClient = useQueryClient()
  const [actual, setActual] = useState('')
  const [date, setDate] = useState('')
  const [note, setNote] = useState('')

  const { data: balance } = useQuery({
    queryKey: ['balance', accountId],
    queryFn: () => accountsApi.balance(accountId),
  })

  const { data: reconciliations } = useQuery({
    queryKey: ['reconciliations', accountId],
    queryFn: () => reconciliationsApi.list(accountId),
  })

  const expected = balance?.balance_cents ?? 0
  const actualCents = actual ? Math.round(parseFloat(actual) * 100) : 0
  const diff = actualCents - expected

  const createMutation = useMutation({
    mutationFn: () =>
      reconciliationsApi.create({
        account_id: accountId,
        actual_balance_cents: actualCents,
        date: date || undefined,
        note: note || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reconciliations', accountId] })
      setActual('')
      setDate('')
      setNote('')
    },
  })

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault()
    if (!actual) return
    createMutation.mutate()
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Kontostandsabgleich</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
          <div className="p-3 rounded-md bg-muted/50">
            <p className="text-muted-foreground">System-Kontostand</p>
            <p className="font-semibold">{formatCHF(expected)}</p>
          </div>
          <div className="p-3 rounded-md bg-muted/50">
            <p className="text-muted-foreground">Tatsächlicher Stand</p>
            <p className="font-semibold">{actual ? formatCHF(actualCents) : '—'}</p>
          </div>
          <div className="p-3 rounded-md bg-muted/50">
            <p className="text-muted-foreground">Differenz</p>
            <p className={`font-semibold ${diff !== 0 ? 'text-destructive' : ''}`}>{formatCHF(diff)}</p>
          </div>
        </div>

        <form onSubmit={handleCreate} className="grid grid-cols-1 md:grid-cols-4 gap-2 items-end">
          <div>
            <label className="text-xs text-muted-foreground">Tatsächlicher Kontostand (CHF)</label>
            <Input type="number" step="0.01" value={actual} onChange={(e) => setActual(e.target.value)} placeholder="0.00" />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Abgleichdatum</label>
            <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Notiz</label>
            <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="z. B. fehlende Buchung" />
          </div>
          <Button type="submit" disabled={createMutation.isPending || !actual}>
            {createMutation.isPending ? 'Wird gespeichert...' : 'Abgleich abschliessen'}
          </Button>
        </form>
        <p className="text-xs text-muted-foreground">
          Der Abgleich erzeugt keine Buchungen und ändert keine bestehenden Daten. Die Differenz wird nur dokumentiert.
        </p>

        <div className="space-y-2">
          {(reconciliations ?? []).length === 0 && (
            <p className="text-sm text-muted-foreground">Keine bisherigen Abgleiche.</p>
          )}
          {(reconciliations ?? []).map((r: Reconciliation) => (
            <div key={r.id} className="p-3 rounded-md bg-muted/50 text-sm space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">
                  {new Date(r.reconciliation_date).toLocaleDateString('de-CH')}
                </span>
                <span className="font-semibold">
                  Differenz: {formatCHF(r.difference_cents)}
                </span>
              </div>
              <div className="flex gap-4 text-xs text-muted-foreground">
                <span>System: {formatCHF(r.expected_balance_cents)}</span>
                <span>Tatsächlich: {formatCHF(r.actual_balance_cents)}</span>
              </div>
              {r.note && <p className="text-xs">{r.note}</p>}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}