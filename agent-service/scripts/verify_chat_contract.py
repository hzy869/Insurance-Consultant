from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import asyncio
from uuid import uuid4
import httpx
from sqlalchemy import text
from app.main import app
from app.infra.database import engine


async def main():
    async with app.router.lifespan_context(app):
        paths = app.openapi()['paths']
        count = sum(method in ('get','post','put','patch','delete') for methods in paths.values() for method in methods)
        assert count == 31, count
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            name='chat_verify_'+uuid4().hex[:10]
            user=(await client.post('/api/v1/auth/register',json={'username':name,'email':name+'@example.com','password':'test-password-123'})).json()
            uid=user['user']['id']
            thread=None
            try:
                assert (await client.get('/api/v1/chat-threads',headers={'x-user-id':str(uid)})).status_code==401
                client.headers['Authorization']='Bearer '+user['access_token']
                r=await client.post('/api/v1/chat-threads',json={'title':'Contract verification'})
                assert r.status_code==200,r.text
                thread=r.json()['id']
                before=r.json()['updated_at']
                r=await client.post('/api/v1/chat',json={'thread_id':thread,'message':'你好','payload':{'source':'verification'}})
                assert r.status_code==200 and 'event: done' in r.text,r.text
                history=await client.get(f'/api/v1/chat-threads/{thread}/messages')
                assert len(history.json()['messages'])==2,history.text
                threads=(await client.get('/api/v1/chat-threads')).json()
                assert threads[0]['updated_at']>before
                assert (await client.get(f'/api/v1/chat-threads/{uuid4()}/messages')).status_code==404
                assert (await client.patch(f'/api/v1/chat-threads/{thread}',json={})).status_code==422
                assert (await client.post('/api/v1/chat',json={'thread_id':thread,'decision':{'action':'reject'}})).status_code==422
                paged=await client.get('/api/v1/products?page=1&page_size=2')
                assert len(paged.json()['items'])==2,paged.text
                assert isinstance((await client.get('/api/v1/products')).json(),list)
                assert len((await client.get('/api/v1/products?name=小蜜蜂')).json())>0
            finally:
                if thread:
                    await client.delete('/api/v1/chat-threads/'+thread)
                async with engine.begin() as connection:
                    await connection.execute(text('DELETE FROM users WHERE id=:id'),{'id':uid})
    print('Full application passed: 31 operations, JWT-only identity, SSE greeting, history, activity ordering, request validation and product search/pagination')

asyncio.run(main(),loop_factory=asyncio.SelectorEventLoop)
