"""Transactions router."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.schemas.transaction import TransactionCreate, TransactionRead, TransactionList
from app.services.transaction_service import TransactionService

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


@router.post("", response_model=TransactionRead, status_code=201)
def create_transaction(data: TransactionCreate, db: Session = Depends(get_db)):
    service = TransactionService(db)
    try:
        return service.create(data)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=TransactionList)
def list_transactions(
    account_id: str = Query(...),
    type: str | None = Query(None, pattern="^(INCOME|EXPENSE)$"),
    category_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    service = TransactionService(db)
    items, total = service.list_by_account(
        account_id=account_id,
        type_filter=type,
        category_id=category_id,
        limit=limit,
        offset=offset,
    )
    return TransactionList(items=items, total=total, page=offset // limit + 1, page_size=limit)


@router.get("/{transaction_id}", response_model=TransactionRead)
def get_transaction(transaction_id: str, db: Session = Depends(get_db)):
    service = TransactionService(db)
    transaction = service.get(transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaktion nicht gefunden")
    return transaction


@router.post("/{transaction_id}/reverse", response_model=TransactionRead, status_code=201)
def reverse_transaction(transaction_id: str, db: Session = Depends(get_db)):
    service = TransactionService(db)
    reversal = service.reverse(transaction_id)
    if not reversal:
        raise HTTPException(status_code=404, detail="Transaktion nicht gefunden oder bereits storniert")
    return reversal
