"""Category service."""
from sqlalchemy.orm import Session
from app.models.category import Category
from app.schemas.category import CategoryCreate, CategoryUpdate


DEFAULT_CATEGORIES = [
    # Einnahmen
    {"name": "Gehalt", "type": "INCOME", "color": "#22c55e", "icon": "briefcase"},
    {"name": "Sonstige Einnahmen", "type": "INCOME", "color": "#10b981", "icon": "plus-circle"},
    # Ausgaben
    {"name": "Lebensmittel", "type": "EXPENSE", "color": "#ef4444", "icon": "shopping-cart"},
    {"name": "Miete/Wohnen", "type": "EXPENSE", "color": "#f97316", "icon": "home"},
    {"name": "Transport", "type": "EXPENSE", "color": "#eab308", "icon": "car"},
    {"name": "Freizeit", "type": "EXPENSE", "color": "#8b5cf6", "icon": "gamepad-2"},
    {"name": "Gesundheit", "type": "EXPENSE", "color": "#ec4899", "icon": "heart"},
    {"name": "Sonstiges", "type": "EXPENSE", "color": "#6b7280", "icon": "more-horizontal"},
]


class CategoryService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, data: CategoryCreate) -> Category:
        category = Category(
            name=data.name,
            type=data.type,
            parent_id=data.parent_id,
            color=data.color,
            icon=data.icon,
        )
        self.db.add(category)
        self.db.commit()
        self.db.refresh(category)
        return category

    def get(self, category_id: str) -> Category | None:
        return self.db.query(Category).filter(Category.id == category_id).first()

    def list_all(self, type_filter: str | None = None, include_archived: bool = False) -> list[Category]:
        query = self.db.query(Category)
        if type_filter:
            query = query.filter(Category.type == type_filter)
        if not include_archived:
            query = query.filter(Category.archived_at.is_(None))
        return query.all()

    def update(self, category_id: str, data: CategoryUpdate) -> Category | None:
        category = self.get(category_id)
        if not category:
            return None
        if data.name is not None:
            category.name = data.name
        if data.color is not None:
            category.color = data.color
        if data.icon is not None:
            category.icon = data.icon
        if data.archived_at is not None:
            category.archived_at = data.archived_at
        self.db.commit()
        self.db.refresh(category)
        return category

    def seed_defaults(self) -> list[Category]:
        """Seed default categories if none exist."""
        existing = self.db.query(Category).count()
        if existing > 0:
            return []
        created = []
        for cat_data in DEFAULT_CATEGORIES:
            category = Category(**cat_data)
            self.db.add(category)
            created.append(category)
        self.db.commit()
        for c in created:
            self.db.refresh(c)
        return created
