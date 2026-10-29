import { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { purchasesApi, productsApi, receiptsApi, accountsApi, categoriesApi } from '../services/api'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Label } from '../components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select'
import { parseAmountToCents } from '../lib/money'
import type { Purchase, PurchaseItem, Product, Category } from '../types'

type DraftItem = {
  raw_name: string
  quantity: string
  unit: string
  unit_price: string
  line_total: string
  category_id: string | null
  product_id: string | null
  uncertain: boolean
}

export default function PurchaseManager() {
  const qc = useQueryClient()
  const { data: accounts } = useQuery({ queryKey: ['accounts'], queryFn: accountsApi.list })
  const { data: categories } = useQuery({ queryKey: ['categories', 'EXPENSE'], queryFn: () => categoriesApi.list('EXPENSE') })
  const { data: purchases } = useQuery({ queryKey: ['purchases'], queryFn: () => purchasesApi.list() })
  // products loaded on demand via productsApi

  const [accountId, setAccountId] = useState<string>('')
  const [merchant, setMerchant] = useState('')
  const [total, setTotal] = useState('')
  const [source, setSource] = useState('MANUAL')
  const [items, setItems] = useState<DraftItem[]>([])
  const [barcodeInput, setBarcodeInput] = useState('')
  const [ocrText, setOcrText] = useState('')
  const [receiptRef, setReceiptRef] = useState('')
  const [cameraOpen, setCameraOpen] = useState(false)
  const [scanMsg, setScanMsg] = useState('')
  const videoRef = useRef<HTMLVideoElement>(null)
  const streamRef = useRef<MediaStream | null>(null)

  useEffect(() => {
    if (accounts && accounts.length && !accountId) setAccountId(accounts[0].id)
  }, [accounts, accountId])

  // camera barcode scanning
  useEffect(() => {
    if (!cameraOpen) return
    let detector: any = null
    let raf = 0
    let cancelled = false
    async function start() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
        streamRef.current = stream
        if (videoRef.current) {
          videoRef.current.srcObject = stream
          await videoRef.current.play()
        }
        const BD = (window as any).BarcodeDetector
        if (BD) {
          detector = new BD({ formats: ['ean_13', 'ean_8', 'upc_a', 'upc_e'] })
        } else {
          setScanMsg('BarcodeDetector nicht verfügbar – manuelle Eingabe nutzen.')
        }
        const tick = async () => {
          if (cancelled) return
          if (detector && videoRef.current && videoRef.current.readyState >= 2) {
            try {
              const codes = await detector.detect(videoRef.current)
              if (codes && codes.length) {
                const code = codes[0].rawValue
                setScanMsg(`Erkannt: ${code}`)
                handleBarcode(code)
                stopCamera()
                return
              }
            } catch (e) { /* ignore */ }
          }
          raf = requestAnimationFrame(tick)
        }
        raf = requestAnimationFrame(tick)
      } catch (e) {
        setScanMsg('Kamera nicht verfügbar.')
      }
    }
    start()
    return () => {
      cancelled = true
      if (raf) cancelAnimationFrame(raf)
      stopCamera()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameraOpen])

  function stopCamera() {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
    setCameraOpen(false)
  }

  async function handleBarcode(code: string) {
    setBarcodeInput(code)
    // lookup product locally
    try {
      const p = await productsApi.byGtin(code)
      addItemFromProduct(p)
      setScanMsg(`Produkt gefunden: ${p.normalized_name}`)
    } catch {
      // try Open Food Facts
      try {
        const res = await fetch(`https://world.openfoodfacts.org/api/v0/product/${code}.json`, { signal: AbortSignal.timeout(5000) })
        const json = await res.json()
        if (json.status === 1 && json.product) {
          const name = json.product.product_name || json.product.product_name_de || code
          const brand = json.product.brands || ''
          // create product locally
          const created = await productsApi.create({ gtin: code, normalized_name: name, brand })
          addItemFromProduct(created)
          setScanMsg(`Open Food Facts: ${name}`)
          qc.invalidateQueries({ queryKey: ['products'] })
          return
        }
      } catch { /* offline or fail */ }
      // unknown product -> manual
      setItems((prev) => [...prev, { raw_name: code, quantity: '1', unit: '', unit_price: '', line_total: '', category_id: null, product_id: null, uncertain: true }])
      setScanMsg('Unbekannter Barcode – bitte manuell erfassen.')
    }
  }

  function addItemFromProduct(p: Product) {
    setItems((prev) => [...prev, {
      raw_name: p.normalized_name,
      quantity: '1',
      unit: p.package_size || '',
      unit_price: '',
      line_total: '',
      category_id: p.default_category_id,
      product_id: p.id,
      uncertain: false,
    }])
  }

  function addManualItem() {
    setItems((prev) => [...prev, { raw_name: '', quantity: '1', unit: '', unit_price: '', line_total: '', category_id: null, product_id: null, uncertain: false }])
  }

  function updateItem(idx: number, patch: Partial<DraftItem>) {
    setItems((prev) => prev.map((it, i) => (i === idx ? { ...it, ...patch } : it)))
  }

  function removeItem(idx: number) {
    setItems((prev) => prev.filter((_, i) => i !== idx))
  }

  const createMutation = useMutation({
    mutationFn: async () => {
      // optional receipt
      let receipt_id: string | undefined
      if (receiptRef || ocrText) {
        const r = await receiptsApi.create({ file_reference: receiptRef || undefined, ocr_text: ocrText || undefined, merchant: merchant || undefined, total_cents: parseAmountToCents(total) ?? undefined })
        receipt_id = r.id
      }
      const payload = {
        account_id: accountId || undefined,
        merchant: merchant || undefined,
        currency: 'CHF',
        total_cents: parseAmountToCents(total),
        receipt_id,
        source,
        items: items.map((it) => ({
          product_id: it.product_id,
          raw_name: it.raw_name || undefined,
          quantity: it.quantity || '1',
          unit: it.unit || undefined,
          unit_price_cents: parseAmountToCents(it.unit_price),
          line_total_cents: parseAmountToCents(it.line_total),
          category_id: it.category_id,
        })),
      }
      return purchasesApi.create(payload)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['purchases'] })
      setItems([])
      setMerchant('')
      setTotal('')
      setOcrText('')
      setReceiptRef('')
      setScanMsg('')
    },
  })

  const postMutation = useMutation({
    mutationFn: (id: string) => purchasesApi.post(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['purchases'] }),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => purchasesApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['purchases'] }),
  })

  const catName = (id: string | null) => categories?.find((c: Category) => c.id === id)?.name || '—'

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader><CardTitle>Neuen Einkauf erfassen</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <Label>Konto</Label>
              <Select value={accountId} onValueChange={(v) => setAccountId(v ?? '')}>
                <SelectTrigger><SelectValue placeholder="Konto" /></SelectTrigger>
                <SelectContent>
                  {(accounts || []).map((a: any) => <SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Händler</Label>
              <Input value={merchant} onChange={(e) => setMerchant(e.target.value)} placeholder="Migros" />
            </div>
            <div>
              <Label>Gesamtbetrag (CHF)</Label>
              <Input value={total} onChange={(e) => setTotal(e.target.value)} placeholder="0.00" />
            </div>
            <div>
              <Label>Quelle</Label>
              <Select value={source} onValueChange={(v) => setSource(v ?? 'MANUAL')}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="MANUAL">Manuell</SelectItem>
                  <SelectItem value="BARCODE">Barcode</SelectItem>
                  <SelectItem value="OCR">OCR/Bon</SelectItem>
                  <SelectItem value="MIXED">Kombiniert</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Barcode scan */}
          <div className="border rounded p-3 space-y-2">
            <div className="flex gap-2 items-center">
              <Input value={barcodeInput} onChange={(e) => setBarcodeInput(e.target.value)} placeholder="Barcode (EAN-13/8, UPC)" />
              <Button variant="outline" onClick={() => handleBarcode(barcodeInput)} disabled={!barcodeInput}>Übernehmen</Button>
              <Button variant="outline" onClick={() => setCameraOpen(true)}>Kamera</Button>
            </div>
            {cameraOpen && (
              <div className="space-y-2">
                <video ref={videoRef} className="w-full max-w-sm rounded" playsInline muted />
                <Button variant="outline" size="sm" onClick={stopCamera}>Kamera stoppen</Button>
              </div>
            )}
            {scanMsg && <p className="text-sm text-muted-foreground">{scanMsg}</p>}
          </div>

          {/* Receipt / OCR */}
          <div className="border rounded p-3 space-y-2">
            <Label>Beleg (optional)</Label>
            <Input value={receiptRef} onChange={(e) => setReceiptRef(e.target.value)} placeholder="Dateiname/Referenz" />
            <Label>OCR-Text (optional, manuell einfügen)</Label>
            <textarea className="w-full border rounded p-2 text-sm" rows={4} value={ocrText} onChange={(e) => setOcrText(e.target.value)} placeholder="Kassenbon-Text..." />
          </div>

          {/* Items */}
          <div className="space-y-2">
            <div className="flex justify-between items-center">
              <Label>Positionen</Label>
              <Button variant="outline" size="sm" onClick={addManualItem}>+ Position</Button>
            </div>
            {items.length === 0 && <p className="text-sm text-muted-foreground">Noch keine Positionen.</p>}
            {items.map((it, idx) => (
              <div key={idx} className={`border rounded p-2 space-y-2 ${it.uncertain ? 'border-yellow-400' : ''}`}>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  <Input placeholder="Bezeichnung" value={it.raw_name} onChange={(e) => updateItem(idx, { raw_name: e.target.value })} />
                  <Input placeholder="Menge" value={it.quantity} onChange={(e) => updateItem(idx, { quantity: e.target.value })} />
                  <Input placeholder="Einzelpreis" value={it.unit_price} onChange={(e) => updateItem(idx, { unit_price: e.target.value })} />
                  <Input placeholder="Zeilensumme" value={it.line_total} onChange={(e) => updateItem(idx, { line_total: e.target.value })} />
                </div>
                <div className="flex gap-2 items-center">
                  <Select value={it.category_id || ''} onValueChange={(v) => updateItem(idx, { category_id: v || null })}>
                    <SelectTrigger className="w-48"><SelectValue placeholder="Kategorie" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="">— keine —</SelectItem>
                      {(categories || []).map((c: Category) => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  <span className="text-xs text-muted-foreground">{it.uncertain ? 'unsicher' : ''} {it.product_id ? 'produkt' : ''}</span>
                  <Button variant="outline" size="sm" onClick={() => removeItem(idx)}>Entfernen</Button>
                </div>
              </div>
            ))}
          </div>

          {createMutation.error && <p className="text-sm text-destructive" role="alert">{(createMutation.error as Error).message}</p>}
          <Button onClick={() => createMutation.mutate()} disabled={createMutation.isPending}>
            {createMutation.isPending ? 'Speichert...' : 'Einkauf speichern'}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Gespeicherte Einkäufe</CardTitle></CardHeader>
        <CardContent>
          {!purchases || purchases.length === 0 ? <p className="text-muted-foreground">Keine Einkäufe.</p> : (
            <div className="space-y-3">
              {purchases.map((p: Purchase) => (
                <div key={p.id} className="border rounded p-3 space-y-2">
                  <div className="flex justify-between items-center">
                    <div>
                      <span className="font-medium">{p.merchant || 'Einkauf'}</span>
                      <span className="text-sm text-muted-foreground ml-2">{p.purchased_at ? new Date(p.purchased_at).toLocaleDateString() : ''}</span>
                      <span className="text-sm ml-2">{(p.total_cents ?? 0) / 100} CHF</span>
                      <span className="ml-2 text-xs px-2 py-0.5 rounded bg-muted">{p.status}</span>
                    </div>
                    <div className="flex gap-2">
                      {p.status !== 'POSTED' && p.account_id && (
                        <Button size="sm" onClick={() => postMutation.mutate(p.id)} disabled={postMutation.isPending}>Buchen</Button>
                      )}
                      <Button size="sm" variant="outline" onClick={() => deleteMutation.mutate(p.id)}>Archivieren</Button>
                    </div>
                  </div>
                  <div className="text-sm">
                    {p.items.map((it: PurchaseItem) => (
                      <div key={it.id} className="flex justify-between">
                        <span>{it.raw_name || '—'} × {Number(it.quantity)}</span>
                        <span>{it.category_id ? catName(it.category_id) : 'keine Kategorie'} {(it.line_total_cents ?? 0) / 100}</span>
                      </div>
                    ))}
                  </div>
                  {p.transaction_id && <p className="text-xs text-muted-foreground">Transaktion: {p.transaction_id}</p>}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}