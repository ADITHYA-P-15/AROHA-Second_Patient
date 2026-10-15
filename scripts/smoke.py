#!/usr/bin/env python3
"""End-to-end smoke checks using only Python's standard library."""
import argparse, json, secrets, urllib.error, urllib.request, os
from datetime import datetime, timedelta, timezone
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
    status,m,_=c.request('GET','/api/v1/meta'); check('public UI metadata',status==200 and isinstance(m.get('features'),list) and 'demo_mode' in m)
    status,_,headers=c.request('GET','/'); check('SPA entry point',status==200 and 'text/html' in headers.get('Content-Type',''))
    status,u,_=c.request('GET','/api/no-such-route'); check('unknown API is JSON 404',status==404 and isinstance(u,dict))
    status,_,_=c.request('POST','/api/v1/auth/register',{'name':'Test','email':f'{secrets.token_hex(5)}@example.com','password':'SafePass!234'},csrf=False); check('CSRF enforced',status==403)
    email=f"smoke-{secrets.token_hex(6)}@example.com"; password='SafePass!234'
    status,r,_=c.request('POST','/api/v1/auth/register',{'name':'Smoke Tester','email':email,'password':password}); check('register primary contact',status==201 and r.get('role')=='PRIMARY_CONTACT')
    status,l,_=c.request('POST','/api/v1/auth/login',{'email':email,'password':password}); check('login',status==200 and l.get('role')=='PRIMARY_CONTACT')
    status,me,_=c.request('GET','/api/v1/auth/me'); check('current session',status==200 and me.get('email')==email)
    status,p,_=c.request('POST','/api/v1/patients',{'name':'Synthetic Smoke Patient','birth_year':1950,'care_notes':'Smoke test','clinical_notes':'Fictional note'}); pid=p.get('id') if isinstance(p,dict) else None; check('create patient',status==201 and p.get('is_synthetic') is True)
    status,msg,_=c.request('POST',f'/api/v1/patients/{pid}/messages',{'body':'I need water','channel':'TEXT','on_behalf':True}); iid=msg.get('id') if isinstance(msg,dict) else None; check('daily help creates L1/L2 safe incident',status==201 and msg.get('current_level') in (1,2) and bool(iid) and 'I need water' not in str(msg))
    status,ack,_=c.request('POST',f'/api/v1/incidents/{iid}/acknowledge',{}); check('incident acknowledgement',status==200 and ack.get('status')=='ACKNOWLEDGED')
    status,resolved,_=c.request('POST',f'/api/v1/incidents/{iid}/resolve',{'code':'HANDLED'}); check('incident resolution',status==200 and resolved.get('status')=='RESOLVED')
    status,sos,_=c.request('POST',f'/api/v1/patients/{pid}/sos',{'on_behalf':True}); sos_id=sos.get('id') if isinstance(sos,dict) else None; check('SOS creates L5 incident',status==201 and sos.get('current_level')==5 and bool(sos_id))
    status,detail,_=c.request('GET',f'/api/v1/incidents/{sos_id}'); check('patient-safe incident detail omits raw text',status==200 and 'SOS emergency report' not in str(detail))
    status,notifications,_=c.request('GET','/api/v1/notifications'); check('notifications list',status==200 and any(x.get('incident_id')==sos_id for x in notifications.get('items',[])))
    status,li,_=c.request('GET','/api/v1/patients'); check('patient list',status==200 and any(x.get('id')==pid for x in li.get('items',[])))
    status,hi,_=c.request('GET',f'/api/v1/patients/{pid}/history'); check('patient history',status==200 and len(hi.get('items',[]))>=1)
    ct=Client(args.base_url); ct_email=f"smoke-ct-{secrets.token_hex(6)}@example.com"; status,_,_=ct.request('POST','/api/v1/auth/register',{'name':'Smoke Caretaker','email':ct_email,'password':password,'role':'CARETAKER'}); check('register caretaker',status==201)
    status,_,_=c.request('POST',f'/api/v1/patients/{pid}/care-team',{'email':ct_email,'team_role':'CARETAKER'}); check('invite caretaker creates care profile',status==201)
    status,cgs,_=c.request('GET',f'/api/v1/patients/{pid}/caregivers'); cid=next((x['id'] for x in cgs.get('items',[]) if x.get('name')=='Smoke Caretaker'),None); check('caretaker profile listed',status==200 and bool(cid))
    status,_,_=c.request('PATCH',f'/api/v1/caregivers/{cid}',{'capabilities':['TRANSPORT','MEDICATION_ASSIST','APPOINTMENT_ESCORT']}); check('caretaker capabilities updated',status==200)
    app_tz=timezone(timedelta(hours=5,minutes=30))
    day=(datetime.now(app_tz)+timedelta(days=1)).date()
    scheduled_start=datetime.combine(day,datetime.min.time().replace(hour=10),app_tz)
    scheduled_end=scheduled_start+timedelta(hours=1)
    status,sch,_=c.request('PUT',f'/api/v1/caregivers/{cid}/schedule',{'windows':[{'weekday':day.weekday(),'start_min':540,'end_min':720}]}); check('set weekly schedule',status==200 and len(sch.get('windows',[]))==1)
    status,activity,_=c.request('POST',f'/api/v1/patients/{pid}/activities',{'title':'Smoke transport activity','category':'TRANSPORT','scheduled_start':scheduled_start.isoformat(),'scheduled_end':scheduled_end.isoformat(),'required_support':['TRANSPORT'],'requires_caregiver':True}); aid=activity.get('id') if isinstance(activity,dict) else None; check('create activity',status==201 and bool(aid))
    status,assignment,_=c.request('POST',f'/api/v1/activities/{aid}/assignments',{'caregiver_id':cid,'role':'PRIMARY'}); asid=assignment.get('id') if isinstance(assignment,dict) else None; check('assign caregiver with warnings field',status==201 and 'warnings' in assignment)
    status,_,_=c.request('POST',f'/api/v1/assignments/{asid}/request-confirmation',{}); check('request assignment confirmation',status==200)
    status,confirmed,_=c.request('POST',f'/api/v1/assignments/{asid}/confirm',{}); check('confirm assignment',status==200 and confirmed.get('status')=='CONFIRMED')
    app_day=datetime.now(app_tz).date().isoformat()
    status,center,_=c.request('GET',f'/api/v1/command-center?patient_id={pid}&date={app_day}'); check('command center uses honest basis + summary',status==200 and center.get('basis_note','').startswith('Based on confirmed assignments') and isinstance(center.get('summary'),dict))
    status,balance,_=c.request('GET',f'/api/v1/patients/{pid}/workload-balance?days=7'); check('workload balancer review',status==200 and balance.get('permissions',{}).get('can_apply') is True and isinstance(balance.get('recommendations'),list))
    status,cover,_=c.request('POST',f'/api/v1/activities/{aid}/cover-requests',{'note':'Smoke cover check'}); cover_id=cover.get('id') if isinstance(cover,dict) else None; check('backup matcher ranks replacements',status==201 and isinstance(cover.get('ranking',{}).get('candidates'),list) and bool(cover.get('ranking',{}).get('summary')))
    status,closed,_=c.request('POST',f'/api/v1/cover-requests/{cover_id}/cancel',{'reason':'Smoke cleanup'}); check('cover request can be closed',status==200 and closed.get('status')=='CANCELLED')
    status,fc,_=c.request('GET',f'/api/v1/patients/{pid}/coverage-forecast'); check('coverage forecast covers 24h/3d/7d',status==200 and set(fc.get('horizons',{}))=={'24h','3d','7d'} and isinstance(fc.get('findings'),list))
    status,pat,_=c.request('GET',f'/api/v1/patients/{pid}'); care_code=pat.get('care_code') if isinstance(pat,dict) else None; check('patient has CareCircle ID',status==200 and str(care_code).startswith('CC-'))
    pro=Client(args.base_url); pro_email=f"smoke-pro-{secrets.token_hex(6)}@example.com"; pro.request('POST','/api/v1/auth/register',{'name':'Smoke Doctor','email':pro_email,'password':password,'role':'PROFESSIONAL'})
    status,_,_=pro.request('POST','/api/v1/patients/join',{'care_code':care_code,'birth_year':1951}); check('wrong birth year cannot join',status==404)
    status,_,_=pro.request('POST','/api/v1/patients/join',{'care_code':care_code,'birth_year':1950}); check('professional joins with CareCircle ID',status==201)
    status,_,_=c.request('PUT',f'/api/v1/patients/{pid}/main-caretaker',{'caregiver_id':cid}); check('main caretaker set',status==200)
    status,_,_=c.request('PUT',f'/api/v1/caregivers/{cid}/schedule',{'windows':[{'weekday':d,'start_min':0,'end_min':1440} for d in range(7)]})
    soon=datetime.now(app_tz)+timedelta(minutes=60)  # within the two-hour window in which a dose can be recorded as done
    status,rx,_=pro.request('POST',f'/api/v1/patients/{pid}/prescriptions',{'medicine':'Smoke medicine','dose':'1 tab','times':[soon.strftime('%H:%M')],'start_date':soon.date().isoformat(),'end_date':soon.date().isoformat()}); check('professional prescribes (dose feed)',status==201 and rx.get('doses_created')==1)
    status,appt,_=pro.request('POST',f'/api/v1/patients/{pid}/appointments',{'title':'Smoke appointment','start':(scheduled_start+timedelta(hours=6)).isoformat(),'duration_minutes':30}); check('professional schedules appointment',status==201 and appt.get('status')=='PENDING')
    status,acts,_=ct.request('GET',f'/api/v1/patients/{pid}/activities?limit=100'); dose=next((a for a in acts.get('items',[]) if a.get('source')=='PRESCRIPTION'),None); check('caretaker sees assigned dose as PENDING',status==200 and dose and dose.get('care_status')=='PENDING')
    status,donej,_=ct.request('POST',f"/api/v1/activities/{dose['id'] if dose else 'x'}/complete",{}); check('caretaker records dose as done',status==200 and donej.get('care_status')=='COMPLETED')
    status,adh,_=pro.request('GET',f'/api/v1/patients/{pid}/adherence?days=7'); check('adherence report',status==200 and 'totals' in adh)
    status,manual,_=c.request('POST',f'/api/v1/action-items?patient_id={pid}',{'title':'Call the pharmacy'}); action_id=manual.get('id') if isinstance(manual,dict) else None; check('manual reminder persists',status==201 and bool(action_id))
    status,snoozed,_=c.request('POST',f'/api/v1/action-items/{action_id}/snooze',{'until':(datetime.now(timezone.utc)+timedelta(minutes=20)).isoformat()}); check('manual reminder snooze',status==200 and snoozed.get('status')=='SNOOZED')
    status,done,_=c.request('POST',f'/api/v1/action-items/{action_id}/done',{}); check('manual reminder done',status==200 and done.get('status')=='DONE')
    unavailable_start=scheduled_start+timedelta(hours=3); unavailable_end=unavailable_start+timedelta(hours=1)
    status,override,_=c.request('POST',f'/api/v1/caregivers/{cid}/availability-overrides',{'start_at':unavailable_start.isoformat(),'end_at':unavailable_end.isoformat(),'status':'UNAVAILABLE','reason':'WORK','note':'Smoke test'}); oid=override.get('id') if isinstance(override,dict) else None; check('mark caregiver unavailable',status==201 and bool(oid))
    status,cancelled,_=c.request('POST',f'/api/v1/caregivers/{cid}/availability-overrides/{oid}/cancel',{}); check('cancel availability override',status==200 and cancelled.get('status')=='cancelled')
    status,history,_=c.request('GET',f'/api/v1/patients/{pid}/history'); check('domain mutations recorded in history',status==200 and len(history.get('items',[]))>=5)
    status,_,_=c.request('POST','/api/v1/auth/logout'); check('logout',status==204)
    status,_,_=c.request('GET','/api/v1/auth/me'); check('session invalid after logout',status==401)
    c2=Client(args.base_url); other_email=f"smoke-other-{secrets.token_hex(6)}@example.com"; c2.request('POST','/api/v1/auth/register',{'name':'Other Smoke User','email':other_email,'password':password}); login_status,_,_=c2.request('POST','/api/v1/auth/login',{'email':other_email,'password':password}); status,_,_=c2.request('GET',f'/api/v1/patients/{pid}'); check(f'cross-user patient access denied (login {login_status}, response {status})',status in (403,404))
    status,_,_=Client(args.base_url).request('POST','/api/v1/auth/register',{'name':'Escalation','email':f'{secrets.token_hex(5)}@example.com','password':'SafePass!234','role':'ADMIN'}); check('role escalation rejected',status==422)
    if m.get('demo_mode'):
        demo=Client(args.base_url); pw=os.environ.get('DEMO_PASSWORD','Demo@1234')
        login_status,_,_=demo.request('POST','/api/v1/auth/login',{'email':'anita.iyer@secondpatient.demo','password':pw})
        demo_status,demo_patients,_=demo.request('GET','/api/v1/patients')
        check('seeded demo patients exist (read-only)',login_status==200 and demo_status==200 and len(demo_patients.get('items',[]))>=1)
    for name,ok in checks: print(f"{'PASS' if ok else 'FAIL'}  {name}")
    print(f"\n{sum(ok for _,ok in checks)}/{len(checks)} checks passed"); return 0 if all(ok for _,ok in checks) else 1
if __name__=='__main__': raise SystemExit(main())
