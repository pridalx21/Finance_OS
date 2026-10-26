import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { reconciliationsApi } from '../services/api'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { formatCHF, formatDate, parseAmountToCents } from '../lib/money'
import { newIdempotencyKey } from '../lib/idempotency'

interface Props {
  accountId: string
}

export default function ReconciliationManager({ accountId }: Props) {
  const queryClient = useQueryClient()
  const [actual, setActual] = useState('')
  const [date, setDate] = useState('')
  const [note, setNote] = useState('')
  const [formError, setFormError] = useState<string | null>(null)

  const { data: expected, isLoading } = useQuery({
    queryKey: ['reconciliation', 'expected', accountId, date],
    queryFn: () => reconciliationsApi.expectedBalance(accountId, date || undefined),
    enabled: !!accountId,
  })

  const { data: reconciliations } = useQuery({
    queryKey: ['reconciliations', accountId],
    queryFn: () => reconciliationsApi.list(accountId),
  })

  const createMutation = useMutation({
    mutationFn: () => {
      const cents = parseAmountToCents(actual)
      if (cents === null) {
        throw new Error('Bitte einen gültigen Betrag eingeben.')
      }
      return reconciliationsApi.create({
        account_id: accountId,
        actual_balance_cents: cents,
        date: date || undefined,
        note: note || undefined,
        create_transaction: true,
        idempotency_key: newIdempotencyKey(),
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reconciliations', accountId] })
      queryClient.invalidateQueries({ queryKey: ['reconciliation', 'expected'] })
      queryClient.invalidateQueries({ queryKey: ['balance'] })
      queryClient.invalidateQueries({ queryKey: ['transactions'] })
      queryClient.invalidateQueries({ queryKey: ['reports'] })
      setActual('')
      setDate('')
      setNote('')
      setFormError(null)
    },
    onError: (error: Error) => setFormError(error.message),
  })

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault()
    setFormError(null)
    createMutation.mutate()
  }

  // The system balance of the selected cut-off date (today when no date is set)
  const expectedCents = expected?.expected_balance_cents ?? 0
  const actualCents = parseAmountToCents(actual)
  const diff = actualCents === null ? null : actualCents - expectedCents

  return (
    <Card>
      <CardHeader>
        <CardTitle>Kontostandsabgleich</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
          <div className="p-3 rounded-md bg-muted/50">
            <p className="text-muted-foreground">
              System-Kontostand{date ? ' (Stichtag)' : ' (heute)'}
            </p>
            <p className="font-semibold">
              {isLoading ? 'Lade...' : formatCHF(expectedCents)}
            </p>
          </div>
          <div className="p-3 rounded-md bg-muted/50">
            <p className="text-muted-foreground">Tatsächlicher Stand</p>
            <p className="font-semibold">
              {actualCents === null ? '—' : formatCHF(actualCents)}
            </p>
          </div>
          <div className="p-3 rounded-md bg-muted/50">
            <p className="text-muted-foreground">Differenz</p>
            <p className={`font-semibold ${diff !== null && diff !== 0 ? 'text-destructive' : ''}`}>
              {diff === null ? '—' : formatCHF(diff)}
            </p>
          </div>
        </div>

        <form onSubmit={handleCreate} className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2 items-end">
          <div>
            <label className="text-xs text-muted-foreground" htmlFor="rec-actual">
              Tatsächlicher Kontostand (CHF)
            </label>
            <Input
              id="rec-actual"
              type="text"
              inputMode="decimal"
              value={actual}
              onChange={(e) => setActual(e.target.value)}
              placeholder="0.00"
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground" htmlFor="rec-date">
              Abgleichdatum (Stichtag)
            </label>
            <Input id="rec-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </div>
          <div>
            <label className="text-xs text-muted-foreground" htmlFor="rec-note">
              Notiz
            </label>
            <Input
              id="rec-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="z. B. fehlende Buchung"
            />
          </div>
          <Button type="submit" disabled={createMutation.isPending || actualCents === null}>
            {createMutation.isPending ? 'Wird gespeichert...' : 'Abgleich abschliessen'}
          </Button>
        </form>

        {(formError || createMutation.error) && (
          <p className="text-sm text-destructive" role="alert">
            {formError ?? createMutation.error?.message}
          </p>
        )}

        <p className="text-xs text-muted-foreground">
          Der Abgleich gleicht den Kontostand an den tatsächlichen Wert an: Die Differenz wird als
          Korrekturbuchung erfasst. Der System-Kontostand bezieht nur Buchungen ein, die am gewählten
          Stichtag wirksam waren.
        </p>

        <div className="space-y-2">
          {(reconciliations ?? []).length === 0 && (
            <p className="text-sm text-muted-foreground">Keine bisherigen Abgleiche.</p>
          )}
          {(reconciliations ?? []).map((r) => (
            <div key={r.id} className="p-3 rounded-md bg-muted/50 text-sm space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">{formatDate(r.reconciliation_date)}</span>
                <span className="font-semibold">Differenz: {formatCHF(r.difference_cents)}</span>
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
