import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { debtsApi } from '../services/api'
import type { Debt } from '../types'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { formatCHF, formatDate, parseAmountToCents } from '../lib/money'
import { newIdempotencyKey } from '../lib/idempotency'

interface Props {
  accountId?: string
}

export default function DebtManager({ accountId }: Props) {
  const queryClient = useQueryClient()
  const [creditor, setCreditor] = useState('')
  const [amount, setAmount] = useState('')
  const [type, setType] = useState<'OWED' | 'RECEIVABLE'>('OWED')
  const [dueDate, setDueDate] = useState('')
  const [description, setDescription] = useState('')
  const [bookOnAccount, setBookOnAccount] = useState(true)
  const [payAmounts, setPayAmounts] = useState<Record<string, string>>({})
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [formError, setFormError] = useState<string | null>(null)

  // Idempotency keys: one key per action until it succeeded. A repeated
  // request (double click, retry) can therefore never create a second entry.
  const createKey = useRef<string | null>(null)
  const payKeys = useRef<Record<string, string>>({})

  const { data: debts, isLoading } = useQuery({
    queryKey: ['debts', accountId],
    queryFn: () => debtsApi.list(accountId ? { account_id: accountId } : {}),
  })

  const { data: summary } = useQuery({
    queryKey: ['debts', 'summary', accountId],
    queryFn: () => debtsApi.summary(accountId),
  })

  const { data: payments, isLoading: paymentsLoading } = useQuery({
    queryKey: ['debts', 'payments', expanded],
    queryFn: async () => {
      const ids = Object.keys(expanded).filter((id) => expanded[id])
      const result: Record<string, Awaited<ReturnType<typeof debtsApi.payments>>> = {}
      for (const id of ids) {
        result[id] = await debtsApi.payments(id)
      }
      return result
    },
    enabled: Object.values(expanded).some(Boolean),
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['debts'] })
    queryClient.invalidateQueries({ queryKey: ['balance'] })
    queryClient.invalidateQueries({ queryKey: ['reports'] })
    queryClient.invalidateQueries({ queryKey: ['transactions'] })
  }

  const createMutation = useMutation({
    mutationFn: () => {
      const cents = parseAmountToCents(amount)
      if (cents === null || cents <= 0) {
        throw new Error('Bitte einen Betrag grösser als 0 eingeben.')
      }
      if (!creditor.trim()) {
        throw new Error('Bitte Gläubiger bzw. Gegenpartei angeben.')
      }
      if (!createKey.current) createKey.current = newIdempotencyKey()
      return debtsApi.create({
        account_id: accountId,
        creditor: creditor.trim(),
        type,
        amount_cents: cents,
        due_date: dueDate || undefined,
        description: description || undefined,
        idempotency_key: createKey.current,
      })
    },
    onSuccess: () => {
      invalidate()
      createKey.current = null
      setFormError(null)
      setCreditor('')
      setAmount('')
      setDueDate('')
      setDescription('')
    },
    onError: (error: Error) => setFormError(error.message),
  })

  const payMutation = useMutation({
    mutationFn: ({ id, value }: { id: string; value: string }) => {
      const cents = parseAmountToCents(value)
      if (cents === null || cents <= 0) {
        throw new Error('Bitte einen Betrag grösser als 0 eingeben.')
      }
      if (!payKeys.current[id]) payKeys.current[id] = newIdempotencyKey()
      return debtsApi.pay(id, {
        amount_cents: cents,
        create_transaction: bookOnAccount,
        account_id: accountId,
        idempotency_key: payKeys.current[id],
      })
    },
    onSuccess: (_data, variables) => {
      invalidate()
      delete payKeys.current[variables.id]
      setPayAmounts((prev) => ({ ...prev, [variables.id]: '' }))
    },
  })

  const cancelMutation = useMutation({
    mutationFn: (paymentId: string) => debtsApi.cancelPayment(paymentId),
    onSuccess: invalidate,
  })

  const archiveMutation = useMutation({
    mutationFn: (id: string) => debtsApi.delete(id),
    onSuccess: invalidate,
  })

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault()
    setFormError(null)
    createMutation.mutate()
  }

  const handlePay = (debt: Debt) => {
    const value = payAmounts[debt.id]
    if (!value) return
    payMutation.mutate({ id: debt.id, value })
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
              <p className="text-muted-foreground">Netto offene Position</p>
              <p className="font-semibold">{formatCHF(summary.net_open_cents)}</p>
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
            <label className="text-xs text-muted-foreground" htmlFor="debt-creditor">
              Gläubiger/Schuldner
            </label>
            <Input
              id="debt-creditor"
              value={creditor}
              onChange={(e) => setCreditor(e.target.value)}
              placeholder="z. B. Bank"
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground" htmlFor="debt-amount">
              Betrag (CHF)
            </label>
            <Input
              id="debt-amount"
              type="text"
              inputMode="decimal"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="0.00"
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground" htmlFor="debt-type">
              Typ
            </label>
            <select
              id="debt-type"
              className="h-8 w-full rounded-lg border border-input bg-background px-2.5 text-sm"
              value={type}
              onChange={(e) => setType(e.target.value as 'OWED' | 'RECEIVABLE')}
            >
              <option value="OWED">Schuld (ich schulde)</option>
              <option value="RECEIVABLE">Forderung (mir wird geschuldet)</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-muted-foreground" htmlFor="debt-due">
              Fällig am
            </label>
            <Input id="debt-due" type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
          </div>
          <Button type="submit" disabled={createMutation.isPending}>
            {createMutation.isPending ? 'Wird angelegt...' : 'Hinzufügen'}
          </Button>
        </form>

        {(formError || createMutation.error) && (
          <p className="text-sm text-destructive" role="alert">
            {formError ?? createMutation.error?.message}
          </p>
        )}

        {/* Liste */}
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Lade Schulden...</p>
        ) : openDebts.length === 0 ? (
          <p className="text-sm text-muted-foreground">Keine offenen Schulden.</p>
        ) : (
          <div className="space-y-3">
            {openDebts.map((debt) => {
              const debtPayments = payments?.[debt.id]
              return (
                <div key={debt.id} className="p-3 rounded-md bg-muted/50 space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <div>
                      <p className="font-medium text-sm">
                        {debt.creditor}
                        <span className="ml-2 text-xs text-muted-foreground">
                          {debt.type === 'OWED' ? 'Schuld' : 'Forderung'}
                        </span>
                        {debt.is_overdue && (
                          <span className="ml-2 text-xs text-destructive">überfällig</span>
                        )}
                      </p>
                      {debt.description && (
                        <p className="text-xs text-muted-foreground">{debt.description}</p>
                      )}
                      {debt.due_date && (
                        <p className="text-xs text-muted-foreground">Fällig: {formatDate(debt.due_date)}</p>
                      )}
                    </div>
                    <div className="text-right">
                      <p className="font-semibold text-sm">{formatCHF(debt.remaining_cents)}</p>
                      <p className="text-xs text-muted-foreground">
                        von {formatCHF(debt.amount_cents)} · bezahlt {formatCHF(debt.paid_cents ?? 0)}
                      </p>
                    </div>
                  </div>
                  <div className="flex gap-2 items-center flex-wrap">
                    <Input
                      type="text"
                      inputMode="decimal"
                      placeholder="Betrag"
                      aria-label={`Zahlungsbetrag für ${debt.creditor}`}
                      className="h-8 text-sm w-32"
                      value={payAmounts[debt.id] || ''}
                      onChange={(e) =>
                        setPayAmounts((prev) => ({ ...prev, [debt.id]: e.target.value }))
                      }
                    />
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handlePay(debt)}
                      disabled={payMutation.isPending || !payAmounts[debt.id]}
                    >
                      Zahlen
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        setExpanded((prev) => ({ ...prev, [debt.id]: !prev[debt.id] }))
                      }
                    >
                      {expanded[debt.id] ? 'Zahlungen ausblenden' : 'Zahlungen anzeigen'}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => archiveMutation.mutate(debt.id)}
                      disabled={archiveMutation.isPending}
                    >
                      Archivieren
                    </Button>
                  </div>

                  {expanded[debt.id] && (
                    <div className="text-xs space-y-1 border-t pt-2">
                      {paymentsLoading && <p className="text-muted-foreground">Lade Zahlungen...</p>}
                      {!paymentsLoading && (debtPayments?.length ?? 0) === 0 && (
                        <p className="text-muted-foreground">Noch keine Zahlungen.</p>
                      )}
                      {debtPayments?.map((payment) => (
                        <div key={payment.id} className="flex items-center justify-between gap-2">
                          <span className={payment.is_cancelled ? 'line-through text-muted-foreground' : ''}>
                            {formatDate(payment.date)} · {formatCHF(payment.amount_cents)}
                            {payment.transaction_id ? ' · gebucht' : ' · ohne Kontobewegung'}
                            {payment.is_cancelled ? ' · storniert' : ''}
                          </span>
                          {!payment.is_cancelled && (
                            <Button
                              size="xs"
                              variant="ghost"
                              onClick={() => cancelMutation.mutate(payment.id)}
                              disabled={cancelMutation.isPending}
                            >
                              Stornieren
                            </Button>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}

        {payMutation.error && (
          <p className="text-sm text-destructive" role="alert">
            {payMutation.error.message}
          </p>
        )}
        {cancelMutation.error && (
          <p className="text-sm text-destructive" role="alert">
            {cancelMutation.error.message}
          </p>
        )}
        {archiveMutation.error && (
          <p className="text-sm text-destructive" role="alert">
            {archiveMutation.error.message}
          </p>
        )}

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={bookOnAccount}
            onChange={(e) => setBookOnAccount(e.target.checked)}
          />
          Zahlung als Buchung erfassen (Ausgabe bei Schuld, Einnahme bei Forderung)
        </label>
      </CardContent>
    </Card>
  )
}
