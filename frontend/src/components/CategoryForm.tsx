import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { categoriesApi } from '../services/api'
import type { Category } from '../types'
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

interface CategoryFormProps {
  trigger?: React.ReactElement
  category?: Category
  defaultType?: 'INCOME' | 'EXPENSE'
}

const COLOR_PRESETS = ['#22c55e', '#10b981', '#ef4444', '#f97316', '#eab308', '#8b5cf6', '#ec4899', '#6b7280', '#3b82f6', '#14b8a6']

export default function CategoryForm({ trigger, category, defaultType }: CategoryFormProps) {
  const isEdit = !!category
  const [open, setOpen] = useState(false)
  const [name, setName] = useState(category?.name ?? '')
  const [type, setType] = useState<'INCOME' | 'EXPENSE'>(category?.type ?? defaultType ?? 'EXPENSE')
  const [color, setColor] = useState(category?.color ?? '#6b7280')
  const [icon, setIcon] = useState(category?.icon ?? '')
  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: () => {
      if (isEdit && category) {
        return categoriesApi.update(category.id, { name, color, icon: icon || undefined })
      }
      return categoriesApi.create({ name, type, color, icon: icon || undefined })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['categories'] })
      setOpen(false)
      if (!isEdit) {
        setName('')
        setColor('#6b7280')
        setIcon('')
      }
    },
  })

  const reset = () => {
    setName(category?.name ?? '')
    setType(category?.type ?? defaultType ?? 'EXPENSE')
    setColor(category?.color ?? '#6b7280')
    setIcon(category?.icon ?? '')
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (v) reset() }}>
      <DialogTrigger render={trigger ?? <Button>Kategorie anlegen</Button>} />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isEdit ? 'Kategorie bearbeiten' : 'Kategorie anlegen'}</DialogTitle>
          <DialogDescription>
            {isEdit ? 'Bearbeite die Kategorie.' : 'Erstelle eine neue Einnahme- oder Ausgaben-Kategorie.'}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="cat-name">Name</Label>
            <Input
              id="cat-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="z. B. Lebensmittel"
            />
          </div>
          {!isEdit && (
            <div className="space-y-2">
              <Label>Typ</Label>
              <Select value={type} onValueChange={(v) => setType((v as 'INCOME' | 'EXPENSE') || 'EXPENSE')}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="INCOME">Einnahme</SelectItem>
                  <SelectItem value="EXPENSE">Ausgabe</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}
          <div className="space-y-2">
            <Label>Farbe</Label>
            <div className="flex flex-wrap gap-2">
              {COLOR_PRESETS.map((c) => (
                <button
                  key={c}
                  type="button"
                  className="w-7 h-7 rounded-full border-2"
                  style={{ backgroundColor: c, borderColor: color === c ? '#000' : 'transparent' }}
                  onClick={() => setColor(c)}
                />
              ))}
              <Input
                value={color}
                onChange={(e) => setColor(e.target.value)}
                className="w-24 h-7 text-xs"
                placeholder="#rrggbb"
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="cat-icon">Icon (optional)</Label>
            <Input
              id="cat-icon"
              value={icon}
              onChange={(e) => setIcon(e.target.value)}
              placeholder="z. B. shopping-cart"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Abbrechen
          </Button>
          <Button onClick={() => mutation.mutate()} disabled={mutation.isPending || !name}>
            {mutation.isPending ? 'Wird gespeichert...' : isEdit ? 'Speichern' : 'Erstellen'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
