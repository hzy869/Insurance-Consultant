from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.product.repository import ProductRepository
from decimal import Decimal
from app.common.schemas import PageResult
from app.infra.database import get_session, AsyncSessionFactory
from app.modules.product.schemas import ProductResponse
from app.modules.product.service import ProductService

router = APIRouter(prefix="/api/v1/products", tags=["产品相关接口"])

# 1.抽取公共函数，来生成service
def get_product_service(session: AsyncSession = Depends(get_session)):
    return ProductService(session)
# 2.需要什么，就让FastAPI注入什么，把这个依赖的东西作为参数
# 3.在参数列表中，指定这个依赖的内容的来源，Depends(来源函数名)

@router.get("")
async def list_product(
    category: str | None = None,
    name: str | None = None,
    page: int | None = Query(default=None, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    service:ProductService = Depends(get_product_service)
):
    # 调用Service，返回product列表
    products = await ProductRepository(session).query_by_category(category, name)
    data = [ProductResponse.model_validate(product, from_attributes=True) for product in products]
    if page is None:
        return data
    start = (page - 1) * page_size
    return {"items": data[start:start + page_size], "page": page, "page_size": page_size, "total": len(data)}


@router.get("/candidates", response_model=list[ProductResponse])
async def list_candidates(
    categories: list[str] = Query(min_length=1),
    premium_min: Decimal | None = None,
    limit_per_category: int = Query(default=5, ge=1, le=100),
    service:ProductService = Depends(get_product_service)
) -> list[ProductResponse]:
    # 2.查询结果
    return await service.list_candidates(
        categories=categories,
        premium_min=premium_min,
        limit_per_category=limit_per_category,
    )
