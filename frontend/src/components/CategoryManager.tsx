import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { categoriesApi } from '../services/api'
import type { Category } from '../types'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import CategoryForm from './CategoryForm'

export default function CategoryManager() {
  const queryClient = useQueryClient()
  const [showArchived, setShowArchived] = useState(false)

  const { data: categories } = useQuery({
    queryKey: ['categories', 'all', showArchived],
    queryFn: () => categoriesApi.list(undefined, showArchived),
  })

  const archiveMutation = useMutation({
    mutationFn: (id: string) => categoriesApi.update(id, { archived_at: new Date().toISOString() }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['categories'] }),
  })

  const income = (categories ?? []).filter((c) => c.type === 'INCOME')
  const expense = (categories ?? []).filter((c) => c.type === 'EXPENSE')

  const renderList = (list: Category[], title: string) => (
    <div>
      <h3 className="text-sm font-semibold text-muted-foreground mb-2">{title}</h3>
      {list.length === 0 ? (
        <p className="text-sm text-muted-foreground">Keine Kategorien.</p>
      ) : (
        <ul className="space-y-2">
          {list.map((cat) => (
            <li key={cat.id} className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span
                  className="w-3 h-3 rounded-full"
                  style={{ backgroundColor: cat.color || '#6b7280' }}
                />
                <span className={cat.archived_at ? 'line-through text-muted-foreground' : ''}>
                  {cat.name}
                </span>
                {cat.archived_at && (
                  <span className="text-xs text-muted-foreground">(archiviert)</span>
                )}
              </div>
              <div className="flex gap-1">
                {!cat.archived_at && (
                  <>
                    <CategoryForm
                      category={cat}
                      trigger={<Button size="sm" variant="outline">Bearbeiten</Button>}
                    />
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => archiveMutation.mutate(cat.id)}
                      disabled={archiveMutation.isPending}
                    >
                      Archivieren
                    </Button>
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Kategorien verwalten</CardTitle>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => setShowArchived((v) => !v)}
          >
            {showArchived ? 'Aktive anzeigen' : 'Archivierte anzeigen'}
          </Button>
          <CategoryForm trigger={<Button size="sm">Neue Kategorie</Button>} />
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {renderList(income, 'Einnahmen')}
        {renderList(expense, 'Ausgaben')}
      </CardContent>
    </Card>
  )
}
