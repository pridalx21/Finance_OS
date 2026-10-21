import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { accountsApi } from '../services/api'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Label } from '../components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '../components/ui/dialog'

interface AccountFormProps {
  trigger?: React.ReactElement
}

export default function AccountForm({ trigger }: AccountFormProps) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [initialBalance, setInitialBalance] = useState('')
  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: () =>
      accountsApi.create({
        name,
        currency: 'CHF',
        initial_balance_cents: Math.round(parseFloat(initialBalance || '0') * 100),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['accounts'] })
      setOpen(false)
      setName('')
      setInitialBalance('')
    },
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={trigger ?? <Button>Konto anlegen</Button>} />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Konto anlegen</DialogTitle>
          <DialogDescription>Erstelle ein neues Konto für deine Finanzen.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="name">Kontoname</Label>
            <Input
              id="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="z. B. Hauptkonto"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="balance">Anfangssaldo (CHF)</Label>
            <Input
              id="balance"
              type="number"
              step="0.01"
              value={initialBalance}
              onChange={(e) => setInitialBalance(e.target.value)}
              placeholder="0.00"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Abbrechen
          </Button>
          <Button onClick={() => mutation.mutate()} disabled={mutation.isPending || !name}>
            {mutation.isPending ? 'Wird erstellt...' : 'Erstellen'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
