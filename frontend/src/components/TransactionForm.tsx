import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { transactionsApi, categoriesApi, accountsApi } from '../services/api'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Label } from '../components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '../components/ui/dialog'
import { parseAmountToCents } from '../lib/money'

interface TransactionFormProps {
  type: 'INCOME' | 'EXPENSE'
  trigger?: React.ReactElement
}

export default function TransactionForm({ type, trigger }: TransactionFormProps) {
  const [open, setOpen] = useState(false)
  const [amount, setAmount] = useState('')
  const [description, setDescription] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [accountId, setAccountId] = useState('')
  const queryClient = useQueryClient()

  const { data: accounts } = useQuery({
    queryKey: ['accounts'],
    queryFn: accountsApi.list,
  })

  const { data: categories } = useQuery({
    queryKey: ['categories', type],
    queryFn: () => categoriesApi.list(type),
  })

  const mutation = useMutation({
    mutationFn: () => {
      const cents = parseAmountToCents(amount)
      if (cents === null || cents <= 0) {
        throw new Error('Bitte einen Betrag grösser als 0 eingeben.')
      }
      return transactionsApi.create({
        account_id: accountId || accounts?.[0]?.id || '',
        type,
        amount_cents: cents,
        category_id: categoryId || undefined,
        description: description || undefined,
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['transactions'] })
      queryClient.invalidateQueries({ queryKey: ['balance'] })
      queryClient.invalidateQueries({ queryKey: ['reports'] })
      setOpen(false)
      setAmount('')
      setDescription('')
      setCategoryId('')
    },
  })

  const label = type === 'INCOME' ? 'Einnahme' : 'Ausgabe'

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          trigger ?? (
            <Button variant={type === 'EXPENSE' ? 'destructive' : 'default'}>{label} erfassen</Button>
          )
        }
      />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{label} erfassen</DialogTitle>
          <DialogDescription>Erfasse eine neue {label.toLowerCase()}.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-4">
          {accounts && accounts.length > 1 && (
            <div className="space-y-2">
              <Label>Konto</Label>
              <Select value={accountId} onValueChange={(v) => setAccountId(v || '')}>
                <SelectTrigger>
                  <SelectValue placeholder="Konto wählen" />
                </SelectTrigger>
                <SelectContent>
                  {accounts.map((acc) => (
                    <SelectItem key={acc.id} value={acc.id}>
                      {acc.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          <div className="space-y-2">
            <Label htmlFor="amount">Betrag (CHF)</Label>
            <Input
              id="amount"
              type="text"
              inputMode="decimal"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="0.00"
            />
          </div>
          <div className="space-y-2">
            <Label>Kategorie</Label>
            <Select value={categoryId} onValueChange={(v) => setCategoryId(v || '')}>
              <SelectTrigger>
                <SelectValue placeholder="Kategorie wählen" />
              </SelectTrigger>
              <SelectContent>
                {categories?.map((cat) => (
                  <SelectItem key={cat.id} value={cat.id}>
                    {cat.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="description">Beschreibung (optional)</Label>
            <Input
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="z. B. Einkauf Migros"
            />
          </div>
          {mutation.error && (
            <p className="text-sm text-destructive" role="alert">
              {mutation.error.message}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Abbrechen
          </Button>
          <Button
            variant={type === 'EXPENSE' ? 'destructive' : 'default'}
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending || !amount}
          >
            {mutation.isPending ? 'Wird gespeichert...' : 'Speichern'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
