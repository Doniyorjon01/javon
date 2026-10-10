"""
Pagination
==========
Same contract as hik-backend: 20 items by default, at most 100.

    @router.get("/books/", response_model=CustomPage[BookOut])
    async def get_books(db: AsyncSession = Depends(get_pg_db), ...):
        stmt = db_catalog.get_books(...)        # the db layer returns a Select
        return await paginate(db, stmt)         # fastapi_pagination.ext.sqlalchemy

Every list endpoint is paginated; an unbounded list is a bug.
"""

from fastapi import Query
from fastapi_pagination import Page
from fastapi_pagination.customization import CustomizedPage, UseName, UseParamsFields

CustomPage = CustomizedPage[
    Page,
    UseName("CustomPage"),
    UseParamsFields(size=Query(20, ge=1, le=100)),
]
