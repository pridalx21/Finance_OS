"""Reports router."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.services.report_service import ReportService

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/expenses-by-category")
def expenses_by_category(
    account_id: str = Query(...),
    db: Session = Depends(get_db),
):
    service = ReportService(db)
    return service.expenses_by_category(account_id)


@router.get("/income-vs-expense")
def income_vs_expense(
    account_id: str = Query(...),
    db: Session = Depends(get_db),
):
    service = ReportService(db)
    return service.income_vs_expense(account_id)


@router.get("/monthly-trend")
def monthly_trend(
    account_id: str = Query(...),
    months: int = Query(6, ge=1, le=36),
    db: Session = Depends(get_db),
):
    service = ReportService(db)
    return service.monthly_trend(account_id, months=months)
