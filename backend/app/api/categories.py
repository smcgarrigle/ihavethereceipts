import html as html_mod

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Category, Item, ReceiptItem
from app.services.spend import LINE_TOTAL

router = APIRouter()


@router.get("/list", response_class=HTMLResponse)
def list_categories(db: Session = Depends(get_db)):
    """List all categories with item counts and spending"""

    # Get categories with stats
    categories_query = (
        db.query(
            Category,
            func.count(Item.id).label("item_count"),
            func.count(ReceiptItem.id).label("purchase_count"),
            func.sum(LINE_TOTAL).label("total_spent"),
        )
        .outerjoin(Item, Category.id == Item.category_id)
        .outerjoin(ReceiptItem, Item.id == ReceiptItem.item_id)
        .group_by(Category.id)
        .order_by(func.sum(LINE_TOTAL).desc())
        .all()
    )

    if not categories_query:
        return "<p class='text-gray-500 dark:text-gray-400'>No categories found</p>"

    html = '<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">'

    for category, item_count, purchase_count, total_spent in categories_query:
        total_spent = total_spent or 0

        # Category icon/color based on name
        icon_colors = {
            "Produce": "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
            "Dairy": "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
            "Meat": "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
            "Bakery": "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400",
            "Pantry": "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400",
            "Beverages": "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
            "Frozen": "bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-400",
            "Deli": "bg-pink-100 text-pink-700 dark:bg-pink-900/30 dark:text-pink-400",
            "Health & Beauty": "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400",
            "Household": "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-400",
            "Other": "bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-400",
        }

        color_class = icon_colors.get(
            category.name, "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-400"
        )

        escaped_category_name = html_mod.escape(category.name)

        # Protect the 'Other' category from deletion
        delete_button = ""
        if category.name.lower() != "other":
            if item_count == 0:
                confirm_msg = f"There are zero items in this category. Do you want to delete '{escaped_category_name}'?"
            else:
                confirm_msg = f"There are {item_count} items in this category. They will be moved to 'Other'. Do you want to delete '{escaped_category_name}'?"

            delete_button = f"""
            <button
                class='px-3 py-1 text-xs bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 rounded hover:bg-red-200 dark:hover:bg-red-900/50'
                hx-delete='/api/categories/{category.id}'
                hx-confirm="{confirm_msg}">
                Delete
            </button>
            """

        html += f"""
        <div class='p-6 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg hover:shadow-md transition'>
            <div class='flex items-center justify-between mb-4'>
                <div class='flex items-center space-x-3'>
                    <div class='w-12 h-12 rounded-full {color_class} flex items-center justify-center font-bold text-lg'>
                        {escaped_category_name[0]}
                    </div>
                    <h3 class='text-lg font-semibold'>
                        <a href='/items?category={category.id}' title='View all items in this category'
                           class='text-gray-900 dark:text-white hover:text-blue-600 dark:hover:text-blue-400 transition-colors'>{escaped_category_name}</a>
                    </h3>
                </div>
                {delete_button}
            </div>

            <div class='space-y-2 text-sm'>
                <div class='flex justify-between'>
                    <span class='text-gray-600 dark:text-gray-400'>Items:</span>
                    <span class='font-medium text-gray-900 dark:text-white'>{item_count}</span>
                </div>
                <div class='flex justify-between'>
                    <span class='text-gray-600 dark:text-gray-400'>Purchases:</span>
                    <span class='font-medium text-gray-900 dark:text-white'>{purchase_count}</span>
                </div>
                <div class='flex justify-between border-t dark:border-gray-700 pt-2'>
                    <span class='text-gray-600 dark:text-gray-400'>Total Spent:</span>
                    <span class='font-bold text-lg text-gray-900 dark:text-white'>${total_spent:.2f}</span>
                </div>
            </div>

            <button
                class='mt-4 w-full px-4 py-2 bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 rounded hover:bg-blue-200 dark:hover:bg-blue-900/50 text-sm font-medium'
                hx-get='/api/items/list?category_id={category.id}'
                hx-target='#modal-content'
                hx-swap='innerHTML'
                onclick='openCategoryItemsModal(this)'>
                View Items
            </button>
        </div>
        """

    html += "</div>"

    # Add modal for viewing items
    html += """
        <div id='category-items-modal' class='hidden fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4'
            role='dialog' aria-modal='true' aria-labelledby='category-items-modal-title'
            onclick='if(event.target === this) closeCategoryItemsModal()'>
            <div class='bg-white dark:bg-gray-800 rounded-lg shadow-2xl w-full max-w-4xl max-h-[80vh] flex flex-col'>
                <!-- Header -->
                <div class='flex justify-between items-center p-6 border-b dark:border-gray-700'>
                    <h3 id='category-items-modal-title' class='text-xl font-semibold text-gray-900 dark:text-white'>Category Items</h3>
                    <button onclick='closeCategoryItemsModal()'
                            aria-label="Close"
                            class='text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 text-2xl'>
                        ×
                    </button>
                </div>

                <!-- Scrollable Content -->
                <div id='modal-content' class='overflow-y-auto p-6 flex-1'>
                    <!-- Content loaded by HTMX -->
                </div>
            </div>
        </div>
        """

    return html


class CreateCategoryRequest(BaseModel):
    name: str


@router.post("/create")
def create_category(request: CreateCategoryRequest, db: Session = Depends(get_db)):
    """Create a new category"""

    category_name = request.name.strip()
    if not category_name:
        raise HTTPException(status_code=400, detail="Category name cannot be empty")

    category_name = category_name[:50].title()

    # Check if category already exists
    existing = db.query(Category).filter(Category.name == category_name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Category already exists")

    # Create new category
    category = Category(name=category_name)
    db.add(category)
    db.commit()
    db.refresh(category)

    return {
        "success": True,
        "message": f"Category '{category_name}' created",
        "category_id": category.id,
    }


@router.delete("/{category_id}")
def delete_category(category_id: int, db: Session = Depends(get_db)):
    """Delete a category and reassign items to 'Other'"""
    from fastapi.responses import JSONResponse

    category = db.query(Category).filter(Category.id == category_id).first()

    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    if (category.name or "").lower() == "other":
        raise HTTPException(status_code=400, detail="Cannot delete the 'Other' category.")

    # Check if any items use this category
    items_count = db.query(Item).filter(Item.category_id == category_id).count()

    try:
        if items_count > 0:
            # Find 'Other' category
            other_category = db.query(Category).filter(Category.name.ilike("other")).first()
            if not other_category:
                other_category = Category(name="Other")
                db.add(other_category)
                db.flush()

            # Reassign items
            db.query(Item).filter(Item.category_id == category_id).update(
                {"category_id": other_category.id}
            )

        db.delete(category)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting category: {str(e)}") from e

    return JSONResponse(
        content={"success": True, "message": f"Category '{category.name}' deleted"},
        headers={"HX-Refresh": "true"},
    )
