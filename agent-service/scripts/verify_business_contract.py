from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import asyncio
from io import BytesIO
from uuid import uuid4

import httpx
from fastapi import FastAPI
from pypdf import PdfReader
from sqlalchemy import text

from app.modules.auth.router import router as auth
from app.modules.business.router import router as business
from app.modules.product.router import router as products
from app.infra.database import engine


async def main():
    from app.infra.business_schema import ensure_business_schema
    await ensure_business_schema()
    app = FastAPI()
    for router in (auth, products, business):
        app.include_router(router)
    assert '/api/v1/orders' in app.openapi()['paths']
    uid = None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        async def call(method, path, expected=200, **kwargs):
            response = await client.request(method, '/api/v1'+path, **kwargs)
            assert response.status_code == expected, (path, response.status_code, response.text)
            return response
        name = 'verify_'+uuid4().hex[:12]
        try:
            await call('GET','/policies',401)
            registered = (await call('POST','/auth/register',201,json={'username':name,'email':name+'@example.com','password':'test-password-123'})).json()
            uid = registered['user']['id']
            await call('POST','/auth/login',401,json={'username':name,'password':'wrong-password'})
            logged = (await call('POST','/auth/login',json={'username':name,'password':'test-password-123'})).json()
            client.headers['Authorization']='Bearer '+logged['access_token']
            await call('POST','/auth/refresh')
            await call('GET','/products/6')
            await call('GET','/products/6/pricing-schema')
            quote=(await call('POST','/premium/calculate',json={'product_id':6,'answers':{'plan_code':'standard','insured.age':30,'insured.social_security':'yes','coverage.deductible':10000,'coverage.coverage_amount':1000000}})).json()
            assert quote['annual_premium']=='300.00',quote
            zero=(await call('POST','/premium/calculate',json={'product_id':6,'answers':{'plan_code':'standard','insured.age':'30','insured.social_security':'yes','coverage.deductible':'0','coverage.coverage_amount':'1000000'}})).json()
            assert zero['annual_premium']=='450.00',zero
            await call('POST','/premium/calculate',422,json={'product_id':6,'answers':{}})
            plan=(await call('PUT','/insurance-plans/current',json={'plan_name':'Test plan','items':[{'product_id':6,'annual_premium_budget':'300.00'}]})).json()
            await call('GET','/insurance-plans')
            await call('GET','/insurance-plans/current')
            updated=(await call('PUT','/insurance-plans/current',json={'plan_name':'Updated plan','budget_note':'Budget reference','items':[{'product_id':6,'annual_premium_budget':'300.00'}]})).json()
            assert updated['version']==2 and updated['budget_note']=='Budget reference',updated
            plan=updated
            from app.modules.auth.router import token
            from datetime import timedelta
            other={'Authorization':'Bearer '+token(1,'access',timedelta(minutes=1))}
            await call('GET','/insurance-plans/'+plan['id'],404,headers=other)
            path='/insurance-plans/'+plan['id']+'/items/'+plan['items'][0]['id']+'/insured'
            insured=(await call('PATCH',path)).json()
            assert insured['status']=='insured',insured
            await call('PATCH',path)
            await call('GET','/insurance-plans/'+plan['id'],404,headers=other)
            policies=(await call('GET','/policies')).json()['items']
            assert len(policies)==1,policies
            await call('GET','/policies/'+policies[0]['id'])
            await call('GET','/claim-guides/'+policies[0]['id'])
            pdf=await call('GET','/claim-guides/application-form')
            assert 'CLAIM APPLICATION' in PdfReader(BytesIO(pdf.content)).pages[0].extract_text()
            await call('GET','/claims')
            await call('GET','/claims/'+str(uuid4()),404)
            body={'quote_ids':[quote['quote_id']],'idempotency_key':'test-key'}
            order=(await call('POST','/orders',json=body)).json()
            repeated=(await call('POST','/orders',json=body)).json()
            assert repeated['id']==order['id']
            assert repeated['idempotency_key']=='test-key'
            await call('GET','/orders/'+order['id'],404,headers=other)
            await call('POST','/orders',409,json={**body,'recommendation_snapshot':{'changed':True}})
            await call('GET','/orders')
            await call('GET','/orders/'+order['id'])
            await call('POST','/orders/'+order['id']+'/cancel')
            await call('POST','/auth/logout')
            await call('POST','/auth/refresh',401)
            # A valid signature cannot substitute for an active account.
            from app.modules.auth.router import token
            from datetime import timedelta
            client.headers['Authorization']='Bearer '+token(-1,'access',timedelta(minutes=1))
            await call('GET','/insurance-plans/'+plan['id'],401)
        finally:
            if uid:
                async with engine.begin() as connection:
                    for statement in ['DELETE FROM orders WHERE user_id=:uid','DELETE FROM policies WHERE user_id=:uid','DELETE FROM insurance_plans WHERE user_id=:uid','DELETE FROM premium_quotes WHERE user_id=:uid','DELETE FROM users WHERE id=:uid']:
                        await connection.execute(text(statement),{'uid':uid})
    await engine.dispose()
    print('Business contract passed: authentication, mock quote, plans, enrollment idempotence, policies, PDF, claims, order idempotence/cancel')

asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)

