import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from pydantic import BaseModel, Field, AliasChoices
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database import get_session
from app.modules.auth.router import current_user
from app.modules.insurance_plan.schemas import InsurancePlanCreate
from app.modules.insurance_plan.service import InsurancePlanService

router = APIRouter(prefix="/api/v1", tags=["保险业务"])
Session = Annotated[AsyncSession, Depends(get_session)]
User = Annotated[int, Depends(current_user)]


async def rows(session, sql: str, **params):
    return [dict(row) for row in (await session.execute(text(sql), params)).mappings()]


async def plan_detail(session, user_id: int, plan_id: UUID):
    plans = await rows(session, "SELECT * FROM insurance_plans WHERE id=:id AND user_id=:uid", id=plan_id, uid=user_id)
    if not plans:
        raise HTTPException(404, "INSURANCE_PLAN_NOT_FOUND")
    items = await rows(session, "SELECT i.*, p.name, p.category, to_jsonb(p) AS product FROM insurance_plan_items i JOIN products p ON p.id=i.product_id WHERE i.plan_id=:id ORDER BY i.priority,i.id", id=plan_id)
    return {**plans[0], "items": items}


@router.get("/products/{product_id}")
async def product_detail(product_id: int, session: Session):
    products = await rows(session, "SELECT * FROM products WHERE id=:id AND status='active'", id=product_id)
    if not products:
        raise HTTPException(404, "PRODUCT_NOT_FOUND")
    return products[0]


@router.get("/products/{product_id}/pricing-schema")
async def pricing_schema(product_id: int, session: Session, scenario: str = "premium_by_coverage"):
    schemas = await rows(session, "SELECT product_id,scenario,schema_version,schema_json AS schema FROM product_pricing_schemas WHERE product_id=:id AND scenario=:scenario AND status='active' ORDER BY activated_at DESC NULLS LAST LIMIT 1", id=product_id, scenario=scenario)
    if not schemas:
        raise HTTPException(404, "PRICING_SCHEMA_NOT_FOUND")
    return schemas[0]


class QuoteRequest(BaseModel):
    product_id: int = Field(gt=0)
    scenario: str = "premium_by_coverage"
    answers: dict[str, Any]


@router.post("/premium/calculate")
async def calculate(form: QuoteRequest, session: Session, user_id: User):
    await product_detail(form.product_id, session)
    bindings = await rows(session, "SELECT b.*,s.schema_json,s.schema_version,a.adapter_type,a.insurer_code FROM product_pricing_bindings b JOIN product_pricing_schemas s ON s.id=b.pricing_schema_id AND s.status='active' JOIN insurer_api_adapters a ON a.id=b.adapter_id AND a.status='active' WHERE b.product_id=:id AND s.scenario=:scenario AND b.status='active' ORDER BY b.updated_at DESC LIMIT 1", id=form.product_id, scenario=form.scenario)
    if not bindings:
        raise HTTPException(404, "PRICING_BINDING_NOT_FOUND")
    binding = bindings[0]
    if binding["adapter_type"] != "mock":
        raise HTTPException(422, "仅支持教学 mock 试算适配器")
    answers = {"plan_code": "basic", **form.answers}
    for field in binding["schema_json"]["fields"]:
        value = answers.get(field["key"])
        if field.get("required") and value is None:
            raise HTTPException(422, f"MISSING_PRICING_PARAMS: {field['key']}")
        if value is None:
            continue
        options = field.get("options", binding["schema_json"].get(field.get("options_ref"), []))
        allowed = [option.get("value") if isinstance(option, dict) else option for option in options]
        numeric = field["type"] in ("integer", "number", "money")
        if allowed and not numeric and value not in allowed:
            raise HTTPException(422, f"INVALID_PRICING_PARAMS: {field['key']}")
        if field["type"] in ("integer", "number", "money"):
            try:
                number = Decimal(str(value))
                if not number.is_finite() or isinstance(value, bool):
                    raise ValueError()
                if field["type"] == "integer" and number != number.to_integral_value():
                    raise ValueError()
                if number < field.get("min", 0) or number > field.get("max", 10**12):
                    raise ValueError()
                if allowed and number not in [Decimal(str(option)) for option in allowed]:
                    raise ValueError()
                answers[field["key"]] = int(number) if number == number.to_integral_value() else float(number)
            except (ValueError, ArithmeticError):
                raise HTTPException(422, f"INVALID_PRICING_PARAMS: {field['key']}") from None
    config = binding["mock_config"]
    plan_code = answers["plan_code"]
    base = config.get("base_premium_by_plan", {}).get(plan_code)
    if base is None:
        raise HTTPException(422, "INVALID_PRICING_PARAMS: plan_code")
    amount = Decimal(str(base))
    age = Decimal(str(answers.get("insured.age", 0)))
    for band in config.get("age_factor", []):
        if band["min"] <= age <= band["max"]:
            amount *= Decimal(str(band["factor"]))
            break
    for name, key in [("gender_factor", "insured.gender"), ("social_security_factor", "insured.social_security"), ("deductible_factor", "coverage.deductible"), ("occupation_factor", "insured.occupation_class")]:
        amount *= Decimal(str(config.get(name, {}).get(str(answers.get(key)), 1)))
    if config.get("coverage_factor_enabled"):
        amount *= Decimal(str(answers["coverage.coverage_amount"])) / Decimal(str(config["coverage_unit"]))
    amount = amount.quantize(Decimal("0.01"))
    quote_id = uuid4()
    expiry = datetime.now(timezone.utc) + timedelta(minutes=30)
    result = {"quote_id": str(quote_id), "product_id": form.product_id, "plan_code": plan_code, "pricing_mode": "mock_adapter", "annual_premium": str(amount), "payment_frequency": "annual", "breakdown": [{"item": "main", "name": plan_code, "premium": str(amount), "source": {"adapter": binding["insurer_code"], "mode": "mock"}}], "warnings": ["教学模拟报价，真实保费以保险公司试算及核保结果为准"], "expires_at": expiry.isoformat()}
    await session.execute(text("INSERT INTO premium_quotes(id,user_id,product_id,request_params,result,total_premium,pricing_mode,expires_at) VALUES(:id,:uid,:pid,CAST(:params AS jsonb),CAST(:result AS jsonb),:amount,'mock_adapter',:expiry)"), {"id": quote_id, "uid": user_id, "pid": form.product_id, "params": form.model_dump_json(), "result": json.dumps(result), "amount": amount, "expiry": expiry})
    await session.commit()
    return result


@router.get("/insurance-plans")
async def list_plans(session: Session, user_id: User):
    plans = await rows(session, "SELECT id FROM insurance_plans WHERE user_id=:uid ORDER BY updated_at DESC", uid=user_id)
    return {"items": [await plan_detail(session, user_id, p["id"]) for p in plans]}


async def current_plan_id(session, user_id):
    return await session.scalar(text("SELECT id FROM insurance_plans WHERE user_id=:uid AND status!='insured' ORDER BY updated_at DESC,id LIMIT 1"), {"uid": user_id})


@router.get("/insurance-plans/current")
async def current_plan(session: Session, user_id: User):
    plan_id = await current_plan_id(session, user_id)
    return await plan_detail(session, user_id, plan_id)


@router.put("/insurance-plans/current")
async def put_plan(form: InsurancePlanCreate, session: Session, user_id: User):
    # 串行化同一用户的当前方案更新，保护已投保项及其快照。
    await session.execute(text("SELECT id FROM users WHERE id=:uid FOR UPDATE"), {"uid": user_id})
    service = InsurancePlanService(session)
    if await service.build_preview(form) is None:
        raise HTTPException(422, "方案中包含无效产品")
    plan_id = await current_plan_id(session, user_id)
    next_version = 1
    if plan_id:
        next_version = await session.scalar(text("SELECT version+1 FROM insurance_plans WHERE id=:id"), {"id": plan_id})
        items = await rows(session, "SELECT * FROM insurance_plan_items WHERE plan_id=:id", id=plan_id)
        protected = {row["product_id"] for row in items if row["status"] == "insured"}
        if protected:
            raise HTTPException(409, "已部分投保的方案不能覆盖，请创建新的方案")
        await session.execute(text("DELETE FROM insurance_plan_items WHERE plan_id=:id"), {"id": plan_id})
        await session.execute(text("DELETE FROM insurance_plans WHERE id=:id"), {"id": plan_id})
    plan_id = plan_id or uuid4()
    await service.repository.insert_plan(plan_id, user_id, form)
    await session.execute(text("UPDATE insurance_plans SET version=:version WHERE id=:id"), {"version": next_version, "id": plan_id})
    await session.commit()
    return await plan_detail(session, user_id, plan_id)


@router.get("/insurance-plans/{plan_id}")
async def get_plan(plan_id: UUID, session: Session, user_id: User):
    return await plan_detail(session, user_id, plan_id)


@router.patch("/insurance-plans/{plan_id}/items/{item_id}/insured")
async def insure(plan_id: UUID, item_id: UUID, session: Session, user_id: User):
    await session.execute(text("SELECT id FROM insurance_plans WHERE id=:id AND user_id=:uid FOR UPDATE"), {"id": plan_id, "uid": user_id})
    plan = await plan_detail(session, user_id, plan_id)
    item = next((i for i in plan["items"] if i["id"] == item_id), None)
    if item is None:
        raise HTTPException(404, "PLAN_ITEM_NOT_FOUND")
    if item["status"] != "insured":
        policy_id = uuid5(NAMESPACE_URL, f"policy:{item_id}")
        await session.execute(text("INSERT INTO policies(id,user_id,product_id,policy_number,status,effective_at,expires_at,premium_amount,payment_frequency,policy_snapshot) VALUES(:id,:uid,:pid,:number,'active',now(),now()+interval '1 year',:amount,'annual',CAST(:snapshot AS jsonb)) ON CONFLICT(id) DO NOTHING"), {"id": policy_id, "uid": user_id, "pid": item["product_id"], "number": f"POL-DEMO-{item_id.hex}", "amount": item["annual_premium_budget"], "snapshot": json.dumps(jsonable_encoder(item))})
        await session.execute(text("UPDATE insurance_plan_items SET status='insured',updated_at=now() WHERE id=:id"), {"id": item_id})
        await session.execute(text("UPDATE insurance_plans SET status=CASE WHEN EXISTS(SELECT 1 FROM insurance_plan_items WHERE plan_id=:id AND status='uninsured') THEN 'applying' ELSE 'insured' END,updated_at=now() WHERE id=:id"), {"id": plan_id})
    await session.commit()
    return await plan_detail(session, user_id, plan_id)


@router.get("/policies")
async def policies(session: Session, user_id: User, status: str = "all"):
    return {"items": await rows(session, "SELECT a.*,to_jsonb(p) AS product FROM policies a JOIN products p ON p.id=a.product_id WHERE a.user_id=:uid AND (:status='all' OR a.status=:status) ORDER BY a.effective_at DESC", uid=user_id, status=status)}


@router.get("/policies/{policy_id}")
async def policy(policy_id: UUID, session: Session, user_id: User):
    found = await rows(session, "SELECT a.*,to_jsonb(p) AS product FROM policies a JOIN products p ON p.id=a.product_id WHERE a.id=:id AND a.user_id=:uid", id=policy_id, uid=user_id)
    if not found:
        raise HTTPException(404, "POLICY_NOT_FOUND")
    return found[0]


@router.get("/claims")
async def claims(session: Session, user_id: User, policy_id: UUID | None = None, status: str = "all"):
    return {"items": await rows(session, "SELECT c.*,to_jsonb(p) AS policy,c.status AS status_message FROM claims c LEFT JOIN policies p ON p.id=c.policy_id AND p.user_id=c.user_id WHERE c.user_id=:uid AND (CAST(:pid AS uuid) IS NULL OR c.policy_id=:pid) AND (:status='all' OR c.status=:status) ORDER BY c.updated_at DESC", uid=user_id, pid=policy_id, status=status)}


@router.get("/claims/{claim_id}")
async def claim(claim_id: UUID, session: Session, user_id: User):
    found = await rows(session, "SELECT c.*,to_jsonb(p) AS policy,c.status AS status_message FROM claims c LEFT JOIN policies p ON p.id=c.policy_id AND p.user_id=c.user_id WHERE c.id=:id AND c.user_id=:uid", id=claim_id, uid=user_id)
    if not found:
        raise HTTPException(404, "CLAIM_NOT_FOUND")
    return found[0]


@router.get("/claim-guides/application-form")
async def application_form():
    # 生成一页可打印的教学用表格，使用 PDF 内置字体，无外部字体依赖。
    stream = b"BT /F1 18 Tf 50 780 Td (DEMO CLAIM APPLICATION) Tj /F1 12 Tf 0 -50 Td (Policy number: ____________________) Tj 0 -40 Td (Applicant: ________________________) Tj 0 -40 Td (Claim description: ________________) Tj 0 -40 Td (Supporting documents: _____________) Tj 0 -80 Td (Submit the signed application to your insurer.) Tj ET"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>", b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(pdf)
    pdf.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return Response(bytes(pdf), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="claim-application-form.pdf"'})


@router.get("/claim-guides/{policy_id}")
async def guide(policy_id: UUID, session: Session, user_id: User):
    owned = await policy(policy_id, session, user_id)
    return {"product_name": owned["product"]["name"], "download_uri": "/api/v1/claim-guides/application-form", "steps": [{"title": "联系承保公司", "description": "报案并确认当前事故所需材料"}, {"title": "提交申请", "description": "向承保公司提交材料并跟踪进度"}], "materials": [{"name": "理赔申请书", "required": True, "remark": "其他材料按承保公司和事故类型确认"}], "notes": ["教学演示指引，受理、审核及支付由承保公司办理"]}


class OrderRequest(BaseModel):
    quote_ids: list[UUID] = Field(min_length=1, validation_alias=AliasChoices("quote_ids", "quoteIds"))
    idempotency_key: str = Field(min_length=1, max_length=160)
    thread_id: UUID | None = Field(default=None, validation_alias=AliasChoices("thread_id", "threadId"))
    confirmation_id: str | None = Field(default=None, max_length=60)
    recommendation_snapshot: dict | None = None
    items: list[dict[str, Any]] | None = None


@router.get("/orders")
async def orders(session: Session, user_id: User):
    found = await rows(session, "SELECT * FROM orders WHERE user_id=:uid ORDER BY created_at DESC", uid=user_id)
    return {"items": [{**item, "idempotency_key": (item["idempotency_key"] or "").removeprefix(f"{user_id}:")} for item in found]}


@router.post("/orders")
async def create_order(form: OrderRequest, session: Session, user_id: User):
    fingerprint = hashlib.sha256(json.dumps(form.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
    key = f"{user_id}:{form.idempotency_key}"
    if len(key) > 160:
        raise HTTPException(422, "幂等键过长")
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": key})
    existing = await rows(session, "SELECT * FROM orders WHERE idempotency_key=:key AND user_id=:uid", key=key, uid=user_id)
    if existing:
        if existing[0].get("idempotency_fingerprint") != fingerprint:
            raise HTTPException(409, "幂等键已用于其他请求")
        return {**existing[0], "idempotency_key": form.idempotency_key}
    if form.thread_id and not await session.scalar(text("SELECT id FROM chat_threads WHERE id=:id AND user_id=:uid"), {"id": form.thread_id, "uid": user_id}):
        raise HTTPException(404, "CHAT_THREAD_NOT_FOUND")
    quotes = await rows(session, "SELECT * FROM premium_quotes WHERE id=ANY(:ids) AND user_id=:uid AND expires_at>now()", ids=form.quote_ids, uid=user_id)
    if len(quotes) != len(set(form.quote_ids)):
        raise HTTPException(404, "QUOTE_NOT_FOUND")
    order_id = uuid4()
    items = [{"product_id": quote["product_id"], "quote_id": str(quote["id"])} for quote in quotes]
    if form.items is not None:
        if sorted(str(item.get("product_id")) for item in form.items) != sorted(str(item["product_id"]) for item in items):
            raise HTTPException(422, "订单项必须与报价产品一致")
        items = form.items
    created = await rows(session, "INSERT INTO orders(id,user_id,thread_id,order_number,idempotency_key,idempotency_fingerprint,items,quote_ids,total_premium,recommendation_snapshot) VALUES(:id,:uid,:thread,:number,:key,:fingerprint,CAST(:items AS jsonb),:quotes,:total,CAST(:snapshot AS jsonb)) RETURNING *", id=order_id, uid=user_id, thread=form.thread_id, number=f"ORD-{order_id.hex}", key=key, fingerprint=fingerprint, items=json.dumps(items), quotes=form.quote_ids, total=sum(q["total_premium"] for q in quotes), snapshot=json.dumps(form.recommendation_snapshot))
    await session.commit()
    return {**created[0], "idempotency_key": form.idempotency_key}


@router.get("/orders/{order_id}")
async def order(order_id: UUID, session: Session, user_id: User):
    found = await rows(session, "SELECT * FROM orders WHERE id=:id AND user_id=:uid", id=order_id, uid=user_id)
    if not found:
        raise HTTPException(404, "ORDER_NOT_FOUND")
    return {**found[0], "idempotency_key": (found[0]["idempotency_key"] or "").removeprefix(f"{user_id}:")}


@router.post("/orders/{order_id}/cancel")
async def cancel_order(order_id: UUID, session: Session, user_id: User):
    found = await rows(session, "SELECT * FROM orders WHERE id=:id AND user_id=:uid FOR UPDATE", id=order_id, uid=user_id)
    if not found:
        raise HTTPException(404, "ORDER_NOT_FOUND")
    if found[0]["status"] not in ("pending_payment", "cancelled"):
        raise HTTPException(409, "当前订单状态不允许取消")
    await session.execute(text("UPDATE orders SET status='cancelled',updated_at=now() WHERE id=:id"), {"id": order_id})
    await session.commit()
    return await order(order_id, session, user_id)
