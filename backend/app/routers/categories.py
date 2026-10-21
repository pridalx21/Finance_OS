"""Categories router."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.schemas.category import CategoryCreate, CategoryRead, CategoryUpdate
from app.services.category_service import CategoryService

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.post("", response_model=CategoryRead, status_code=201)
def create_category(data: CategoryCreate, db: Session = Depends(get_db)):
    service = CategoryService(db)
    return service.create(data)


@router.get("", response_model=list[CategoryRead])
def list_categories(
    type: str | None = Query(None, pattern="^(INCOME|EXPENSE)$"),
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
):
    service = CategoryService(db)
    return service.list_all(type_filter=type, include_archived=include_archived)


@router.get("/{category_id}", response_model=CategoryRead)
def get_category(category_id: str, db: Session = Depends(get_db)):
    service = CategoryService(db)
    category = service.get(category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Kategorie nicht gefunden")
    return category


@router.patch("/{category_id}", response_model=CategoryRead)
def update_category(category_id: str, data: CategoryUpdate, db: Session = Depends(get_db)):
    service = CategoryService(db)
    category = service.update(category_id, data)
    if not category:
        raise HTTPException(status_code=404, detail="Kategorie nicht gefunden")
    return category


@router.post("/seed", response_model=list[CategoryRead])
def seed_categories(db: Session = Depends(get_db)):
    service = CategoryService(db)
    return service.seed_defaults()
