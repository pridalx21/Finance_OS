"""Tests for the purchases plugin."""
from decimal import Decimal


def _setup(plugin_client):
    account_id = plugin_client.post("/api/accounts", json={"name": "Test", "currency": "CHF", "initial_balance_cents": 100000}).json()["id"]
    cat_id = plugin_client.post("/api/categories", json={"name": "Lebensmittel", "type": "EXPENSE"}).json()["id"]
    return account_id, cat_id


def test_create_manual_purchase(plugin_client):
    account_id, cat_id = _setup(plugin_client)
    resp = plugin_client.post("/api/purchases", json={
        "account_id": account_id,
        "merchant": "Migros",
        "currency": "CHF",
        "total_cents": 1500,
        "items": [
            {"raw_name": "Milch", "quantity": "2", "unit": "Stk", "unit_price_cents": 750, "line_total_cents": 1500, "category_id": cat_id},
        ],
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["merchant"] == "Migros"
    assert data["total_cents"] == 1500
    assert data["items_total_cents"] == 1500
    assert len(data["items"]) == 1
    assert data["items"][0]["categorization_source"] == "MANUAL"


def test_idempotency_no_duplicate(plugin_client):
    account_id, cat_id = _setup(plugin_client)
    payload = {
        "account_id": account_id,
        "merchant": "Coop",
        "total_cents": 1000,
        "idempotency_key": "imp-1",
        "items": [{"raw_name": "Brot", "quantity": "1", "line_total_cents": 1000}],
    }
    r1 = plugin_client.post("/api/purchases", json=payload)
    assert r1.status_code == 201
    r2 = plugin_client.post("/api/purchases", json=payload)
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]
    # only one purchase
    lst = plugin_client.get("/api/purchases").json()
    assert len(lst) == 1


def test_idempotency_conflict(plugin_client):
    account_id, _ = _setup(plugin_client)
    payload = {
        "account_id": account_id,
        "merchant": "Coop",
        "total_cents": 1000,
        "idempotency_key": "imp-2",
        "items": [{"raw_name": "Brot", "quantity": "1", "line_total_cents": 1000}],
    }
    r1 = plugin_client.post("/api/purchases", json=payload)
    assert r1.status_code == 201
    payload2 = dict(payload)
    payload2["total_cents"] = 2000
    r2 = plugin_client.post("/api/purchases", json=payload2)
    assert r2.status_code == 409


def test_post_creates_transaction_and_no_duplicate(plugin_client):
    account_id, cat_id = _setup(plugin_client)
    resp = plugin_client.post("/api/purchases", json={
        "account_id": account_id,
        "merchant": "Denner",
        "total_cents": 2500,
        "items": [{"raw_name": "Apfel", "quantity": "5", "line_total_cents": 2500}],
    })
    pid = resp.json()["id"]
    # before post: no transaction
    txs_before = plugin_client.get(f"/api/transactions?account_id={account_id}").json()["total"]
    assert txs_before == 0
    # post
    post_resp = plugin_client.post(f"/api/purchases/{pid}/post")
    assert post_resp.status_code == 200, post_resp.text
    data = post_resp.json()
    assert data["status"] == "POSTED"
    assert data["transaction_id"] is not None
    txs_after = plugin_client.get(f"/api/transactions?account_id={account_id}").json()["total"]
    assert txs_after == 1
    # balance decreased
    bal = plugin_client.get(f"/api/accounts/{account_id}/balance").json()["balance_cents"]
    assert bal == 100000 - 2500
    # posting again does not create second transaction
    plugin_client.post(f"/api/purchases/{pid}/post")
    txs_again = plugin_client.get(f"/api/transactions?account_id={account_id}").json()["total"]
    assert txs_again == 1


def test_create_transaction_flag(plugin_client):
    account_id, _ = _setup(plugin_client)
    resp = plugin_client.post("/api/purchases", json={
        "account_id": account_id,
        "merchant": "Aldi",
        "total_cents": 900,
        "create_transaction": True,
        "items": [{"raw_name": "X", "quantity": "1", "line_total_cents": 900}],
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "POSTED"
    assert data["transaction_id"] is not None
    txs = plugin_client.get(f"/api/transactions?account_id={account_id}").json()["total"]
    assert txs == 1


def test_idempotent_import_no_duplicate_transaction(plugin_client):
    account_id, _ = _setup(plugin_client)
    payload = {
        "account_id": account_id,
        "merchant": "Lidl",
        "total_cents": 1200,
        "idempotency_key": "imp-tx",
        "create_transaction": True,
        "items": [{"raw_name": "Y", "quantity": "1", "line_total_cents": 1200}],
    }
    r1 = plugin_client.post("/api/purchases", json=payload)
    r2 = plugin_client.post("/api/purchases", json=payload)
    assert r1.json()["id"] == r2.json()["id"]
    txs = plugin_client.get(f"/api/transactions?account_id={account_id}").json()["total"]
    assert txs == 1


def test_totals_mismatch_stored(plugin_client):
    account_id, _ = _setup(plugin_client)
    resp = plugin_client.post("/api/purchases", json={
        "account_id": account_id,
        "merchant": "M",
        "total_cents": 1000,
        "items": [{"raw_name": "A", "quantity": "1", "line_total_cents": 800}],
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["total_cents"] == 1000
    assert data["items_total_cents"] == 800


def test_product_create_and_gtin_lookup(plugin_client):
    resp = plugin_client.post("/api/purchases/products", json={
        "gtin": "7610000000001",
        "normalized_name": "Milch 1L",
        "brand": "Migros",
        "default_category_id": None,
    })
    assert resp.status_code == 201
    pid = resp.json()["id"]
    # upsert by gtin
    resp2 = plugin_client.post("/api/purchases/products", json={
        "gtin": "7610000000001",
        "normalized_name": "Milch 1L (updated)",
    })
    assert resp2.status_code == 201
    assert resp2.json()["id"] == pid
    # lookup
    r = plugin_client.get("/api/purchases/products/by-gtin/7610000000001")
    assert r.status_code == 200
    assert r.json()["normalized_name"] == "Milch 1L (updated)"


def test_categorization_rule_priority(plugin_client):
    account_id, cat_id = _setup(plugin_client)
    cat2 = plugin_client.post("/api/categories", json={"name": "Haushalt", "type": "EXPENSE"}).json()["id"]
    # product
    prod = plugin_client.post("/api/purchases/products", json={
        "gtin": "111", "normalized_name": "Hammer", "default_category_id": cat_id,
    }).json()["id"]
    # rule merchant -> cat2, confirmed
    plugin_client.post("/api/purchases/rules", json={
        "scope": "MERCHANT", "match_value": "Bauhaus", "category_id": cat2, "priority": 5, "confirmed": True,
    })
    resp = plugin_client.post("/api/purchases", json={
        "account_id": account_id,
        "merchant": "Bauhaus",
        "total_cents": 1000,
        "items": [{"product_id": prod, "raw_name": "Hammer", "quantity": "1", "line_total_cents": 1000}],
    })
    assert resp.status_code == 201
    item = resp.json()["items"][0]
    # rule should win over product default
    assert item["category_id"] == cat2
    assert item["categorization_source"] == "RULE"


def test_manual_category_not_overwritten_by_product_default(plugin_client):
    account_id, cat_id = _setup(plugin_client)
    cat2 = plugin_client.post("/api/categories", json={"name": "Haushalt", "type": "EXPENSE"}).json()["id"]
    prod = plugin_client.post("/api/purchases/products", json={
        "gtin": "222", "normalized_name": "Schraube", "default_category_id": cat_id,
    }).json()["id"]
    resp = plugin_client.post("/api/purchases", json={
        "account_id": account_id,
        "merchant": "Hornbach",
        "total_cents": 500,
        "items": [{"product_id": prod, "raw_name": "Schraube", "quantity": "1", "line_total_cents": 500, "category_id": cat2}],
    })
    assert resp.status_code == 201
    item = resp.json()["items"][0]
    assert item["category_id"] == cat2
    assert item["categorization_source"] == "MANUAL"


def test_unknown_product_unsichere_zuordnung(plugin_client):
    account_id, _ = _setup(plugin_client)
    resp = plugin_client.post("/api/purchases", json={
        "account_id": account_id,
        "merchant": "Unbekannt",
        "total_cents": 300,
        "items": [{"raw_name": "XYZ123", "quantity": "1", "line_total_cents": 300}],
    })
    assert resp.status_code == 201
    item = resp.json()["items"][0]
    assert item["category_id"] is None
    assert item["categorization_source"] == "UNKNOWN"


def test_set_item_category_and_save_rule(plugin_client):
    account_id, cat_id = _setup(plugin_client)
    resp = plugin_client.post("/api/purchases", json={
        "account_id": account_id,
        "merchant": "Migros",
        "total_cents": 400,
        "items": [{"raw_name": "Keks", "quantity": "1", "line_total_cents": 400}],
    })
    item_id = resp.json()["items"][0]["id"]
    r = plugin_client.patch(f"/api/purchases/items/{item_id}/category", params={
        "category_id": cat_id, "save_rule": True, "rule_scope": "TEXT", "match_value": "Keks",
    })
    assert r.status_code == 200
    assert r.json()["category_id"] == cat_id
    assert r.json()["categorization_source"] == "MANUAL"
    # rule created
    rules = plugin_client.get("/api/purchases/rules").json()
    assert any(ru["match_value"] == "Keks" for ru in rules)


def test_historical_item_unchanged_on_product_update(plugin_client):
    account_id, cat_id = _setup(plugin_client)
    cat2 = plugin_client.post("/api/categories", json={"name": "Haushalt", "type": "EXPENSE"}).json()["id"]
    prod = plugin_client.post("/api/purchases/products", json={
        "gtin": "333", "normalized_name": "Bohrer", "default_category_id": cat_id,
    }).json()["id"]
    # purchase with product default suggestion
    resp = plugin_client.post("/api/purchases", json={
        "account_id": account_id,
        "merchant": "Bau",
        "total_cents": 1000,
        "items": [{"product_id": prod, "raw_name": "Bohrer", "quantity": "1", "line_total_cents": 1000}],
    })
    item = resp.json()["items"][0]
    assert item["category_id"] == cat_id
    # update product default category
    # (no direct patch endpoint for product, but re-create upsert changes default)
    plugin_client.post("/api/purchases/products", json={
        "gtin": "333", "normalized_name": "Bohrer", "default_category_id": cat2,
    })
    # historical purchase item unchanged
    p = plugin_client.get(f"/api/purchases/{resp.json()['id']}").json()
    assert p["items"][0]["category_id"] == cat_id


def test_merge_sources(plugin_client):
    account_id, _ = _setup(plugin_client)
    # create product
    plugin_client.post("/api/purchases/products", json={"gtin": "444", "normalized_name": "Milch"})
    resp = plugin_client.post("/api/purchases/merge", json={
        "barcode_gtins": ["444", "999"],
        "ocr_lines": [
            {"name": "Milch", "quantity": 2, "line_total_cents": 3000},
            {"name": "Brot", "quantity": 1, "line_total_cents": 2500, "uncertain": True},
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    # milch matched
    milch = [d for d in data if d.get("gtin") == "444"][0]
    assert milch["matched"] is True
    assert milch["uncertain"] is False
    # unknown barcode
    unknown = [d for d in data if d.get("gtin") == "999"][0]
    assert unknown["matched"] is False
    assert unknown["uncertain"] is True


def test_archive_purchase_voids_transaction(plugin_client):
    account_id, _ = _setup(plugin_client)
    resp = plugin_client.post("/api/purchases", json={
        "account_id": account_id,
        "merchant": "X",
        "total_cents": 700,
        "create_transaction": True,
        "items": [{"raw_name": "Z", "quantity": "1", "line_total_cents": 700}],
    })
    pid = resp.json()["id"]
    tx_count_before = plugin_client.get(f"/api/transactions?account_id={account_id}").json()["total"]
    assert tx_count_before == 1
    del_resp = plugin_client.delete(f"/api/purchases/{pid}")
    assert del_resp.status_code == 200
    # transaction reversed -> still present but voided; active count 0? transactions list includes reversed
    txs = plugin_client.get(f"/api/transactions?account_id={account_id}").json()
    assert txs["total"] == 2  # original + storno


def test_receipt_create_and_link(plugin_client):
    account_id, _ = _setup(plugin_client)
    r = plugin_client.post("/api/purchases/receipts", json={
        "file_reference": "receipt.jpg",
        "ocr_text": "Migros ...",
        "merchant": "Migros",
        "total_cents": 1000,
        "processing_status": "PENDING",
    })
    assert r.status_code == 201
    rid = r.json()["id"]
    resp = plugin_client.post("/api/purchases", json={
        "account_id": account_id,
        "merchant": "Migros",
        "total_cents": 1000,
        "receipt_id": rid,
        "source": "OCR",
        "items": [{"raw_name": "X", "quantity": "1", "line_total_cents": 1000}],
    })
    assert resp.status_code == 201
    assert resp.json()["receipt_id"] == rid
    # receipt processing status updated
    rr = plugin_client.get(f"/api/purchases/receipts/{rid}").json()
    assert rr["processing_status"] == "PROCESSED"
    assert rr["purchase_id"] == resp.json()["id"]


def test_currency_mismatch_rejected(plugin_client):
    account_id, _ = _setup(plugin_client)
    resp = plugin_client.post("/api/purchases", json={
        "account_id": account_id,
        "merchant": "X",
        "currency": "EUR",
        "total_cents": 500,
        "create_transaction": True,
        "items": [{"raw_name": "Z", "quantity": "1", "line_total_cents": 500}],
    })
    assert resp.status_code == 422


def test_post_requires_account(plugin_client):
    _, _ = _setup(plugin_client)
    resp = plugin_client.post("/api/purchases", json={
        "merchant": "X",
        "total_cents": 500,
        "items": [{"raw_name": "Z", "quantity": "1", "line_total_cents": 500}],
    })
    assert resp.status_code == 201
    pid = resp.json()["id"]
    post_resp = plugin_client.post(f"/api/purchases/{pid}/post")
    assert post_resp.status_code == 422


def test_edited_purchase_before_post(plugin_client):
    account_id, cat_id = _setup(plugin_client)
    resp = plugin_client.post("/api/purchases", json={
        "account_id": account_id,
        "merchant": "X",
        "total_cents": 500,
        "items": [{"raw_name": "Z", "quantity": "1", "line_total_cents": 500}],
    })
    pid = resp.json()["id"]
    upd = plugin_client.patch(f"/api/purchases/{pid}", json={
        "merchant": "Y",
        "items": [{"raw_name": "Z2", "quantity": "2", "line_total_cents": 1000}],
    })
    assert upd.status_code == 200
    assert upd.json()["merchant"] == "Y"
    assert upd.json()["items"][0]["raw_name"] == "Z2"


def test_posted_purchase_cannot_be_edited(plugin_client):
    account_id, _ = _setup(plugin_client)
    resp = plugin_client.post("/api/purchases", json={
        "account_id": account_id,
        "merchant": "X",
        "total_cents": 500,
        "create_transaction": True,
        "items": [{"raw_name": "Z", "quantity": "1", "line_total_cents": 500}],
    })
    pid = resp.json()["id"]
    upd = plugin_client.patch(f"/api/purchases/{pid}", json={"merchant": "Y"})
    assert upd.status_code == 409