"""Accounts router."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.schemas.account import AccountCreate, AccountRead, AccountBalance
from app.services.account_service import AccountService

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.post("", response_model=AccountRead, status_code=201)
def create_account(data: AccountCreate, db: Session = Depends(get_db)):
    service = AccountService(db)
    return service.create(data)


@router.get("", response_model=list[AccountRead])
def list_accounts(db: Session = Depends(get_db)):
    service = AccountService(db)
    return service.list_all()


@router.get("/{account_id}", response_model=AccountRead)
def get_account(account_id: str, db: Session = Depends(get_db)):
    service = AccountService(db)
    account = service.get(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Konto nicht gefunden")
    return account


@router.get("/{account_id}/balance", response_model=AccountBalance)
def get_balance(account_id: str, db: Session = Depends(get_db)):
    service = AccountService(db)
    balance = service.balance(account_id)
    if not balance:
        raise HTTPException(status_code=404, detail="Konto nicht gefunden")
    return balance
