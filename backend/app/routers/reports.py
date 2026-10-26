"""Reports router."""
from fastapi import APIRouter, Depends, HTTPException, Query
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


@router.get("/weekly")
def weekly_report(
    account_id: str = Query(...),
    week: str | None = Query(None),
    db: Session = Depends(get_db),
):
    service = ReportService(db)
    try:
        return service.weekly_report(account_id, week=week)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/weekly-trend")
def weekly_trend(
    account_id: str = Query(...),
    weeks: int = Query(8, ge=1, le=52),
    db: Session = Depends(get_db),
):
    service = ReportService(db)
    return service.weekly_trend(account_id, weeks=weeks)


@router.get("/monthly")
def monthly_report(
    account_id: str = Query(...),
    month: str | None = Query(None),
    db: Session = Depends(get_db),
):
    service = ReportService(db)
    try:
        return service.monthly_report(account_id, month=month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))