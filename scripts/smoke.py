#!/usr/bin/env python3
"""End-to-end smoke checks using only Python's standard library."""
import argparse, json, secrets, urllib.error, urllib.request
CSRF={"X-Requested-With":"second-patient"}
class Client:
    def __init__(self,base): self.base=base.rstrip('/'); self.jar={}
    def request(self,method,path,body=None,csrf=True):
        headers={"Accept":"application/json"}
        if csrf: headers.update(CSRF)
        data=json.dumps(body).encode() if body is not None else None
        if data: headers['Content-Type']='application/json'
        if self.jar: headers['Cookie']='; '.join(f'{k}={v}' for k,v in self.jar.items())
        req=urllib.request.Request(self.base+path,data=data,headers=headers,method=method)
        try:
            with urllib.request.urlopen(req,timeout=8) as r:
                self.cookies(r.headers); raw=r.read(); return r.status,self.decode(raw,r.headers),r.headers
        except urllib.error.HTTPError as e:
            self.cookies(e.headers); raw=e.read(); return e.code,self.decode(raw,e.headers),e.headers
    @staticmethod
    def decode(raw,headers):
        if not raw: return None
        if 'application/json' in headers.get('Content-Type',''):
            try: return json.loads(raw)
            except (ValueError,UnicodeDecodeError): return None
        return raw.decode('utf-8',errors='replace')
    def cookies(self,headers):
        for item in headers.get_all('Set-Cookie',[]):
            first=item.split(';',1)[0]; k,_,v=first.partition('=')
            if v: self.jar[k]=v
            else: self.jar.pop(k,None)
def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--base-url',required=True); args=parser.parse_args(); checks=[]
    def check(name,ok): checks.append((name,bool(ok)))
    c=Client(args.base_url)
    status,h,_=c.request('GET','/api/health'); check('health + database',status==200 and h.get('database')=='ok')
    status,m,_=c.request('GET','/api/v1/meta'); check('meta phase',status==200 and m.get('phase')==1)
    status,_,headers=c.request('GET','/'); check('SPA entry point',status==200 and 'text/html' in headers.get('Content-Type',''))
    status,u,_=c.request('GET','/api/no-such-route'); check('unknown API is JSON 404',status==404 and isinstance(u,dict))
    status,_,_=c.request('POST','/api/v1/auth/register',{'name':'Test','email':f'{secrets.token_hex(5)}@example.com','password':'SafePass!234'},csrf=False); check('CSRF enforced',status==403)
    email=f"smoke-{secrets.token_hex(6)}@example.com"; password='SafePass!234'
    status,r,_=c.request('POST','/api/v1/auth/register',{'name':'Smoke Tester','email':email,'password':password}); check('register family only',status==201 and r.get('role')=='FAMILY')
    status,l,_=c.request('POST','/api/v1/auth/login',{'email':email,'password':password}); check('login',status==200 and l.get('role')=='FAMILY')
    status,me,_=c.request('GET','/api/v1/auth/me'); check('current session',status==200 and me.get('email')==email)
    status,p,_=c.request('POST','/api/v1/patients',{'name':'Synthetic Smoke Patient','birth_year':1950,'care_notes':'Smoke test','clinical_notes':'Fictional note'}); pid=p.get('id') if isinstance(p,dict) else None; check('create patient',status==201 and p.get('is_synthetic') is True)
    status,li,_=c.request('GET','/api/v1/patients'); check('patient list',status==200 and any(x.get('id')==pid for x in li.get('items',[])))
    status,hi,_=c.request('GET',f'/api/v1/patients/{pid}/history'); check('patient history',status==200 and len(hi.get('items',[]))>=1)
    status,_,_=c.request('POST','/api/v1/auth/logout'); check('logout',status==204)
    status,_,_=c.request('GET','/api/v1/auth/me'); check('session invalid after logout',status==401)
    c2=Client(args.base_url); other_email=f"smoke-other-{secrets.token_hex(6)}@example.com"; c2.request('POST','/api/v1/auth/register',{'name':'Other Smoke User','email':other_email,'password':password}); login_status,_,_=c2.request('POST','/api/v1/auth/login',{'email':other_email,'password':password}); status,_,_=c2.request('GET',f'/api/v1/patients/{pid}'); check(f'cross-user patient access denied (login {login_status}, response {status})',status in (403,404))
    status,_,_=Client(args.base_url).request('POST','/api/v1/auth/register',{'name':'Escalation','email':f'{secrets.token_hex(5)}@example.com','password':'SafePass!234','role':'ADMIN'}); check('role escalation rejected',status==422)
    for name,ok in checks: print(f"{'PASS' if ok else 'FAIL'}  {name}")
    print(f"\n{sum(ok for _,ok in checks)}/{len(checks)} checks passed"); return 0 if all(ok for _,ok in checks) else 1
if __name__=='__main__': raise SystemExit(main())
