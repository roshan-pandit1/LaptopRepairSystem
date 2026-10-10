import asyncio
import hashlib
import json
import os
import re
import secrets
import shutil
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import Field, ValidationError, model_validator

from packages.schemas.report import CATEGORIES, Device, Measurement, Report, StrictModel, now
from . import db as store
from .db import audit, connection, dumps, get_case, index_case, save_case, settings
from .demo import DEVICE, demo_measurements, seed
from .rules import evaluate

FRONTEND=os.environ.get('FAULTLINE_FRONTEND','http://127.0.0.1:5173')
tasks=set()
agent_seen=None
agent_device=None

def token():
    value=os.environ.get('FAULTLINE_PAIRING_TOKEN')
    if value:return value
    path=store.DATA/'pairing-token'
    if not path.exists():
        store.DATA.mkdir(parents=True,exist_ok=True)
        fd=os.open(str(path),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w') as f:f.write(secrets.token_urlsafe(32))
    return path.read_text().strip()

def ingest(db, report:Report):
    data=report.model_dump(mode='json'); device=data['device']; ident=data['id']
    old=db.execute('SELECT payload FROM devices WHERE id=?',(device['id'],)).fetchone()
    if old and json.loads(old[0])['demo']!=device['demo']:
        raise HTTPException(409,'Demo and real device namespaces cannot be mixed')
    existing=db.execute('SELECT * FROM scans WHERE id=?',(ident,)).fetchone()
    if existing and existing['report']:
        if existing['report']==dumps(data):return False
        raise HTTPException(409,'Report ID already exists with different content')
    if existing and (existing['device_id']!=device['id'] or existing['demo']!=device['demo']):
        raise HTTPException(409,'Report does not match requested scan device')
    db.execute('INSERT INTO devices(id,payload) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(device['id'],dumps(device)))
    db.execute('INSERT INTO scans(id,device_id,started_at,completed_at,status,demo,categories,progress,report) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET completed_at=excluded.completed_at,status=excluded.status,report=excluded.report,progress=excluded.progress',
               (ident,device['id'],data['started_at'],data['completed_at'],data['status'],device['demo'],dumps(data['categories']),dumps(list(dict.fromkeys(m['component'] for m in data['measurements']))),dumps(data)))
    for m in data['measurements']:
        db.execute('INSERT INTO measurements(scan_id,device_id,key,component,timestamp,payload) VALUES(?,?,?,?,?,?)',(ident,device['id'],m['key'],m['component'],m['timestamp'],dumps(m)))
    audit(db,'simulated_scan_'+data['status'] if device['demo'] else 'collector_scan_'+data['status'],ident)
    return True

@asynccontextmanager
async def lifespan(app):
    store.migrate();token()
    with connection() as db:
        db.execute("UPDATE scans SET status='failed' WHERE status IN ('running','queued','cancelling')")
        seed(db,ingest)
    print('FAULTLINE local API. Pairing token file:',store.DATA/'pairing-token')
    yield
    for task in tasks:task.cancel()

app=FastAPI(title='FAULTLINE local API',version='1.0',lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=[FRONTEND],allow_credentials=False,allow_methods=['GET','POST','PUT','DELETE'],allow_headers=['Content-Type','Authorization'])

@app.middleware('http')
async def local_boundary(request:Request,call_next):
    from fastapi.responses import JSONResponse
    host=request.headers.get('host','').split(':')[0]
    origin=request.headers.get('origin')
    if host not in ('127.0.0.1','localhost','testserver'):
        return JSONResponse({'detail':'Loopback host required'},status_code=403)
    if request.client and request.client.host not in ('127.0.0.1','::1','testclient'):
        return JSONResponse({'detail':'Loopback clients only'},status_code=403)
    if origin and origin!=FRONTEND:
        return JSONResponse({'detail':'Untrusted browser origin'},status_code=403)
    if request.headers.get('sec-fetch-site')=='cross-site':
        return JSONResponse({'detail':'Cross-site requests forbidden'},status_code=403)
    if int(request.headers.get('content-length','0'))>25*1024*1024:
        return JSONResponse({'detail':'Request exceeds 25 MB'},status_code=413)
    return await call_next(request)

def paired(authorization:Optional[str]=Header(default=None)):
    if not authorization or not secrets.compare_digest(authorization,'Bearer '+token()):
        raise HTTPException(401,'Valid pairing token required')

def require_device(db,ident):
    row=db.execute('SELECT payload FROM devices WHERE id=?',(ident,)).fetchone()
    if not row:raise HTTPException(404,'Device not found')
    return json.loads(row[0])

def require_case(db,ident):
    case=get_case(db,ident)
    if not case:raise HTTPException(404,'Case not found')
    return case

def scan_json(row):
    if not row:raise HTTPException(404,'Scan not found')
    return {k:json.loads(row[k]) if k in ('categories','progress') else row[k] for k in row.keys() if k!='report'}

@app.get('/api/health')
def health():return {'status':'ok','schema_version':'1.0'}

@app.get('/api/devices')
def devices():
    with connection() as db:return [json.loads(r[0]) for r in db.execute('SELECT payload FROM devices ORDER BY id')]

@app.get('/api/devices/{ident}/evidence')
def evidence(ident:str):
    with connection() as db:
        latest=db.execute('SELECT id FROM scans WHERE device_id=? AND report IS NOT NULL ORDER BY completed_at DESC LIMIT 1',(ident,)).fetchone()
        return measurements_for(db,latest[0]) if latest else []

def measurements_for(db,ident):
    return [dict(json.loads(r['payload']),id=r['id']) for r in db.execute('SELECT id,payload FROM measurements WHERE scan_id=?',(ident,))]

@app.get('/api/scans/{ident}/measurements')
def scan_measurements(ident:str):
    with connection() as db:return measurements_for(db,ident)

@app.get('/api/devices/{ident}/history')
def history(ident:str):
    with connection() as db:return [dict(json.loads(r['payload']),id=r['id']) for r in db.execute('SELECT id,payload FROM measurements WHERE device_id=? ORDER BY timestamp,id',(ident,))]

@app.get('/api/devices/{ident}/scans')
def scans(ident:str):
    with connection() as db:return [scan_json(r) for r in db.execute('SELECT * FROM scans WHERE device_id=? ORDER BY started_at DESC',(ident,))]

@app.get('/api/devices/{ident}/warnings')
def warnings(ident:str):
    with connection() as db:
        result=evaluate(db,ident)
        for w in result:
            w['related_cases']=[get_case(db,r[0]) for r in db.execute('SELECT id FROM cases') if json.loads(db.execute('SELECT payload FROM cases WHERE id=?',(r[0],)).fetchone()[0])['fault_group']==w['component']][:3]
        return result

class ScanRequest(StrictModel):
    device_id:str
    categories:List[Literal['battery','storage','cooling','ram','system']]=Field(min_length=1,max_length=5)
    scenario:Literal['healthy','warning','unavailable']='warning'

async def simulated_scan(ident,device,categories,scenario):
    collected=[]
    with connection() as db:started=db.execute('SELECT started_at FROM scans WHERE id=?',(ident,)).fetchone()[0]
    for category in categories:
        await asyncio.sleep(.65)
        with connection() as db:
            row=db.execute('SELECT * FROM scans WHERE id=?',(ident,)).fetchone()
            if not row:return
            if row['status']=='cancelling':break
            collected.extend(demo_measurements(category,scenario,capacity=97 if scenario=='healthy' else 72))
            progress=json.loads(row['progress'])+[category]
            db.execute("UPDATE scans SET status='running',progress=? WHERE id=?",(dumps(progress),ident))
    with connection() as db:
        row=db.execute('SELECT status FROM scans WHERE id=?',(ident,)).fetchone()
        if not row:return
        report=Report.model_validate({'schema_version':'1.0','id':ident,'device':device,'started_at':started,'completed_at':now(),'status':'cancelled' if row[0]=='cancelling' else 'completed','categories':categories,'measurements':collected})
        ingest(db,report)

@app.post('/api/scans')
async def start_scan(body:ScanRequest):
    ident='scan-'+uuid4().hex
    categories=list(dict.fromkeys(body.categories))
    with connection() as db:
        device=require_device(db,body.device_id)
        if not set(categories)<=set(settings(db)['permissions']):raise HTTPException(403,'A selected category is disabled in collection permissions')
        if db.execute("SELECT 1 FROM scans WHERE device_id=? AND status IN ('queued','running','cancelling')",(device['id'],)).fetchone():raise HTTPException(409,'A scan is already active for this device')
        if not device['demo'] and (not agent_seen or datetime.now(timezone.utc)-agent_seen>timedelta(seconds=20) or agent_device!=device['id']):raise HTTPException(409,'Agent disconnected. Run the paired collector in watch mode or import a JSON report.')
        db.execute('INSERT INTO scans(id,device_id,started_at,status,demo,categories) VALUES(?,?,?,?,?,?)',(ident,device['id'],now(),'queued',device['demo'],dumps(categories)))
        audit(db,'scan_requested',ident)
    if device['demo']:
        task=asyncio.create_task(simulated_scan(ident,device,categories,body.scenario));tasks.add(task);task.add_done_callback(tasks.discard)
    with connection() as db:return scan_json(db.execute('SELECT * FROM scans WHERE id=?',(ident,)).fetchone())

@app.get('/api/scans/{ident}')
def scan_status(ident:str):
    with connection() as db:return scan_json(db.execute('SELECT * FROM scans WHERE id=?',(ident,)).fetchone())

@app.post('/api/scans/{ident}/cancel')
def cancel_scan(ident:str):
    with connection() as db:
        row=db.execute('SELECT * FROM scans WHERE id=?',(ident,)).fetchone();scan_json(row)
        if row['status'] in ('queued','running'):
            db.execute("UPDATE scans SET status='cancelling' WHERE id=?",(ident,));audit(db,'scan_cancel_requested',ident)
        return scan_json(db.execute('SELECT * FROM scans WHERE id=?',(ident,)).fetchone())

@app.get('/api/agent/status')
def agent_status():return {'connected':bool(agent_seen and datetime.now(timezone.utc)-agent_seen<timedelta(seconds=20)),'last_seen':agent_seen,'device_id':agent_device}

@app.post('/api/agent/poll',dependencies=[Depends(paired)])
def agent_poll(device:Device):
    global agent_seen,agent_device
    if device.demo:raise HTTPException(422,'Agent cannot register a demo device')
    agent_seen=datetime.now(timezone.utc);agent_device=device.id
    with connection() as db:
        old=db.execute('SELECT payload FROM devices WHERE id=?',(device.id,)).fetchone()
        if old and json.loads(old[0])['demo']:raise HTTPException(409,'Reserved demo identity')
        db.execute('INSERT INTO devices VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(device.id,device.model_dump_json()))
        row=db.execute("SELECT * FROM scans WHERE device_id=? AND status IN ('queued','running','cancelling') ORDER BY started_at LIMIT 1",(device.id,)).fetchone()
        config=settings(db)
        if not row and config['scheduled_monitoring'] and config['permissions']:
            latest=db.execute('SELECT started_at FROM scans WHERE device_id=? ORDER BY started_at DESC LIMIT 1',(device.id,)).fetchone()
            if not latest or datetime.now(timezone.utc)-datetime.fromisoformat(latest[0])>=timedelta(days=1):
                ident='scheduled-'+uuid4().hex
                db.execute('INSERT INTO scans(id,device_id,started_at,status,demo,categories) VALUES(?,?,?,?,?,?)',(ident,device.id,now(),'queued',False,dumps(config['permissions'])))
                audit(db,'scheduled_scan_requested',ident)
                row=db.execute('SELECT * FROM scans WHERE id=?',(ident,)).fetchone()
        return {'job':scan_json(row) if row else None,'permissions':config['permissions']}

class Progress(StrictModel):
    completed_categories:List[Literal['battery','storage','cooling','ram','system']]

@app.post('/api/agent/scans/{ident}/progress',dependencies=[Depends(paired)])
def progress(ident:str,body:Progress):
    global agent_seen
    agent_seen=datetime.now(timezone.utc)
    with connection() as db:
        row=db.execute('SELECT * FROM scans WHERE id=?',(ident,)).fetchone();scan_json(row)
        if not set(body.completed_categories)<=set(json.loads(row['categories'])):raise HTTPException(422,'Progress outside selected categories')
        if row['status'] in ('completed','cancelled','failed'):raise HTTPException(409,'Scan is terminal')
        db.execute("UPDATE scans SET progress=?,status=CASE WHEN status='cancelling' THEN status ELSE 'running' END WHERE id=?",(dumps(body.completed_categories),ident))
        return {'cancel_requested':row['status']=='cancelling'}

@app.post('/api/agent/reports',dependencies=[Depends(paired)])
def agent_report(report:Report):
    if report.device.demo:raise HTTPException(422,'Real collector reports cannot be demo data')
    with connection() as db:
        if not set(report.categories)<=set(settings(db)['permissions']):raise HTTPException(403,'Report contains disabled collection categories')
        inserted=ingest(db,report)
        return {'id':report.id,'inserted':inserted}

class CaseCreate(StrictModel):
    title:str=Field(min_length=1,max_length=300)
    brand:Optional[str]=Field(default=None,min_length=1,max_length=200)
    model:Optional[str]=Field(default=None,min_length=1,max_length=200)
    category:str=Field(default='Laptop',min_length=1,max_length=100)
    symptom:str=Field(min_length=1,max_length=4000)
    fault_group:str=Field(min_length=1,max_length=100)
    record_type:Literal['technician','public aggregate']='technician'

    @model_validator(mode='after')
    def known_technician_device(self):
        if self.record_type!='public aggregate' and (not self.brand or not self.model):
            raise ValueError('Technician records require a brand and model; use public aggregate for incomplete source records')
        return self

@app.post('/api/cases')
def create_case(body:CaseCreate):
    case=dict(body.model_dump(),id='FL-'+uuid4().hex[:8].upper(),state='reported',outcome='outcome unknown',review_status='pending',follow_up='pending',parent_id=None,created_at=now())
    with connection() as db:
        save_case(db,case)
        db.execute('INSERT INTO case_events(case_id,kind,notes,timestamp,data) VALUES(?,?,?,?,?)',(case['id'],'reported',case['symptom'],now(),'{}'))
        index_case(db,case['id']);audit(db,'case_created',case['id'])
        return get_case(db,case['id'])

def terms(text):return set(re.findall(r'[\w-]+',text.lower()))-{'the','and','with','a','of','to','in','on','for'}

@app.get('/api/cases')
def search_cases(request:Request,q:str=''):
    allowed={'category','brand','model','symptom','fault_group','tests','suspected','confirmed','parts','review_status','outcome','follow_up','record_type'}
    with connection() as db:
        if q.strip():
            words=re.findall(r'\w+',q)[:20]
            if not words:return []
            expression=' AND '.join('"'+word+'"*' for word in words)
            ids=[r[0] for r in db.execute('SELECT case_id FROM case_search WHERE case_search MATCH ? ORDER BY rank',(expression,))]
        else:ids=[r[0] for r in db.execute('SELECT id FROM cases ORDER BY id')]
        results=[]
        event_filters={'tests':['test','post_test'],'suspected':['suspected_cause'],'confirmed':['confirmed_cause'],'parts':['repair']}
        for ident in ids:
            case=get_case(db,ident);matched=True
            for key,value in request.query_params.items():
                if key not in allowed or not value:continue
                haystack=dumps([e for e in case['events'] if e['kind'] in event_filters[key]]) if key in event_filters else str(case.get(key,''))
                if value.lower() not in haystack.lower():matched=False;break
            if matched:
                case['match_reasons']=['Full-text terms matched case evidence'] if q else ['Structured filters matched'] if any(v for k,v in request.query_params.items() if k in allowed) else None
                results.append(case)
        return results

@app.get('/api/cases/{ident}')
def case_detail(ident:str):
    with connection() as db:return require_case(db,ident)

@app.get('/api/cases/{ident}/similar')
def similar(ident:str):
    with connection() as db:
        source=require_case(db,ident);results=[]
        for row in db.execute('SELECT id FROM cases WHERE id!=?',(ident,)):
            c=get_case(db,row[0]);score=0;reasons=[];differences=[]
            overlap=terms(source['symptom'])&terms(c['symptom'])
            if overlap:score+=min(len(overlap)*2,10);reasons.append('Symptom overlap: '+', '.join(sorted(overlap)))
            if source.get('model') and c.get('model') and source.get('brand') and c.get('brand') and source['model'].lower()==c['model'].lower() and source['brand'].lower()==c['brand'].lower():score+=5;reasons.append('Exact manufacturer and model match')
            else:differences.append(f'Different or missing model: {c.get("brand") or "Not recorded"} {c.get("model") or "Not recorded"}')
            if source['fault_group']==c['fault_group']:score+=4;reasons.append('Same fault group: '+c['fault_group'])
            source_tests=terms(' '.join(e['notes'] for e in source['events'] if e['kind']=='test'))
            matched_tests=source_tests&terms(' '.join(e['notes'] for e in c['events'] if e['kind']=='test'))
            if len(matched_tests)>=2:score+=2;reasons.append('Recorded test terminology overlaps')
            if c['outcome']=='confirmed working at follow-up' and c['review_status']=='approved':score+=2;reasons.append('Reviewed outcome confirmed at follow-up')
            if not any(e['kind']=='measurement' for e in c['events']):differences.append('No structured numeric test measurements recorded')
            if source['record_type']!=c['record_type']:differences.append('Different provenance / review class: '+c['record_type'])
            if score>2:results.append(dict(c,score=score,match_reasons=reasons,differences=differences))
        return sorted(results,key=lambda c:c['score'],reverse=True)[:5]

class Event(StrictModel):
    kind:Literal['test','measurement','note','suspected_cause','confirmed_cause','repair','post_test','review','handover','follow_up','repeat_failure']
    notes:str=Field(min_length=1,max_length=10000)
    data:Dict[str,Any]=Field(default_factory=dict)

def append_event(db,ident,body):
    c=require_case(db,ident);kind=body.kind;data=body.data;state=c['state'];result=data.get('result')
    if c['record_type']=='public aggregate' and kind not in ('note','measurement'):
        raise HTTPException(409,'Public aggregate source records are not technician-reviewed repairs. Create a technician case to investigate.')
    allowed={'test':{'reported','investigation','diagnosed','repaired','post_tested'},'suspected_cause':{'reported','investigation'},'confirmed_cause':{'investigation'},'repair':{'diagnosed'},'post_test':{'repaired','post_tested'},'review':{'post_tested'},'handover':{'approved'},'follow_up':{'handover','follow_up'},'repeat_failure':{'handover','follow_up'}}
    if kind in allowed and state not in allowed[kind]:raise HTTPException(409,f'{kind} is not allowed from {state}')
    if kind in ('test','post_test'):
        if result not in ('pass','fail','inconclusive'):raise HTTPException(422,'Test result must be pass, fail, or inconclusive')
        if kind=='test' or result!='pass':c.update(state='investigation',review_status='pending')
        else:c['state']='post_tested'
    elif kind=='suspected_cause':c['state']='investigation'
    elif kind=='confirmed_cause':
        try:ids=[int(x.strip()) for x in str(data.get('evidence','')).split(',') if x.strip()]
        except ValueError:raise HTTPException(422,'Evidence must reference numeric event IDs')
        supporting=[e for e in c['events'] if e['id'] in ids and e['kind'] in ('test','measurement')]
        if not ids or len(supporting)!=len(set(ids)):raise HTTPException(422,'Confirmed cause requires existing test or measurement IDs from this case')
        last_repair=max((e['id'] for e in c['events'] if e['kind']=='repair'),default=0)
        if last_repair and not any(e['id']>last_repair for e in supporting):raise HTTPException(409,'Re-investigation requires new supporting test evidence')
        data['evidence_ids']=ids;c['state']='diagnosed'
    elif kind=='repair':c.update(state='repaired',review_status='pending')
    elif kind=='review':
        if result not in ('approved','rejected') or not str(data.get('reviewer','')).strip():raise HTTPException(422,'Reviewer and approved/rejected decision required')
        c.update(state='approved' if result=='approved' else 'investigation',review_status=result)
    elif kind=='handover':c.update(state='handover',outcome='working at handover',follow_up='pending')
    elif kind=='follow_up':
        if result not in ('working','repeat_failure','unknown'):raise HTTPException(422,'Invalid follow-up result')
        c.update(state='follow_up',outcome={'working':'confirmed working at follow-up','repeat_failure':'repeat failure reported','unknown':'outcome unknown'}[result],follow_up={'working':'confirmed working','repeat_failure':'repeat failure','unknown':'unknown'}[result])
    elif kind=='measurement':
        try:
            value=float(data.get('value'))
            if not __import__('math').isfinite(value):raise ValueError()
        except (ValueError,TypeError):raise HTTPException(422,'A finite numeric value is required')
        if not data.get('unit'):raise HTTPException(422,'Measurement unit is required')
        data['value']=value
    if kind=='repeat_failure' or (kind=='follow_up' and result=='repeat_failure'):
        c.update(state='follow_up',outcome='repeat failure reported',follow_up='repeat failure')
        child={k:v for k,v in c.items() if k!='events'}
        child.update(id='FL-'+uuid4().hex[:8].upper(),title='Repeat attempt: '+c['title'],parent_id=ident,state='investigation',outcome='outcome unknown',follow_up='pending',review_status='pending',created_at=now())
        save_case(db,child)
        db.execute('INSERT INTO case_events(case_id,kind,notes,timestamp,data) VALUES(?,?,?,?,?)',(child['id'],'reported',body.notes,now(),dumps({'prior_attempt':ident})))
        index_case(db,child['id']);data['linked_case_id']=child['id']
    save_case(db,c)
    db.execute('INSERT INTO case_events(case_id,kind,notes,timestamp,data) VALUES(?,?,?,?,?)',(ident,kind,body.notes,now(),dumps(data)))
    index_case(db,ident);audit(db,'case_'+kind,ident)
    return get_case(db,ident)

@app.post('/api/cases/{ident}/events')
def add_event(ident:str,body:Event):
    with connection() as db:return append_event(db,ident,body)

@app.post('/api/cases/{ident}/attachments')
async def attachment(ident:str,file:UploadFile=File(...)):
    with connection() as db:require_case(db,ident)
    payload=await file.read(10*1024*1024+1)
    if len(payload)>10*1024*1024:raise HTTPException(413,'Evidence attachment limit is 10 MB')
    aid=uuid4().hex;directory=store.DATA/'evidence';directory.mkdir(parents=True,exist_ok=True)
    filename=Path((file.filename or 'evidence').replace('\\','/')).name[:200]
    path=directory/aid;path.write_bytes(payload);path.chmod(0o600)
    with connection() as db:
        db.execute('INSERT INTO attachments VALUES(?,?,?,?,?)',(aid,ident,filename,aid,len(payload)))
        db.execute('INSERT INTO case_events(case_id,kind,notes,timestamp,data) VALUES(?,?,?,?,?)',(ident,'attachment','Evidence attached: '+filename,now(),dumps({'attachment_id':aid,'sha256':hashlib.sha256(payload).hexdigest(),'size':len(payload)})))
        index_case(db,ident);audit(db,'evidence_attached',ident)
    return {'id':aid}

@app.get('/api/attachments/{ident}')
def download_attachment(ident:str):
    with connection() as db:row=db.execute('SELECT * FROM attachments WHERE id=?',(ident,)).fetchone()
    if not row:raise HTTPException(404,'Attachment not found')
    path=store.DATA/'evidence'/row['storage_name']
    if not path.is_file():raise HTTPException(404,'Attachment bytes are not present in this workspace')
    return FileResponse(path,filename=row['filename'],media_type='application/octet-stream',headers={'X-Content-Type-Options':'nosniff'})

class RuleSettings(StrictModel):
    low_space_percent:float=Field(default=10,gt=0,le=50)
    critical_space_percent:float=Field(default=3,ge=0,le=50)
    battery_drop_points:float=Field(default=8,gt=0,le=100)
    event_count:int=Field(default=5,ge=1,le=10000)
    @model_validator(mode='after')
    def valid_order(self):
        if self.critical_space_percent>self.low_space_percent:raise ValueError('critical threshold exceeds attention threshold')
        return self

class Settings(StrictModel):
    permissions:List[Literal['battery','storage','cooling','ram','system']]=Field(default_factory=lambda:CATEGORIES.copy(),max_length=5)
    retention_days:int=Field(default=365,ge=1,le=3650)
    scheduled_monitoring:bool=False
    rules:RuleSettings=Field(default_factory=RuleSettings)
    ai_enabled:Literal[False]=False

@app.get('/api/settings')
def get_settings():
    with connection() as db:return settings(db)

@app.put('/api/settings')
def put_settings(body:Settings):
    with connection() as db:
        db.execute('INSERT INTO settings VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(body.model_dump_json(),));audit(db,'settings_updated','workspace')
    return body

class Advisory(StrictModel):
    device_id:str
    title:str=Field(min_length=1,max_length=300)
    url:str=Field(max_length=2000)
    applicability:str=Field(min_length=1,max_length=3000)

@app.get('/api/advisories')
def advisories(device_id:str):
    with connection() as db:return [json.loads(r[0]) for r in db.execute('SELECT payload FROM advisories WHERE device_id=?',(device_id,))]

@app.post('/api/advisories')
def add_advisory(body:Advisory):
    url=urlparse(body.url)
    if url.scheme!='https' or not url.hostname or url.username or url.password:raise HTTPException(422,'Use a public official HTTPS source URL without embedded credentials')
    with connection() as db:
        device=require_device(db,body.device_id)
        domains={'lenovo':['lenovo.com'],'dell':['dell.com'],'hp':['hp.com'],'asus':['asus.com'],'acer':['acer.com'],'microsoft':['microsoft.com'],'apple':['apple.com'],'msi':['msi.com']}
        allowed=domains.get(device['manufacturer'].lower(),[])+['microsoft.com','msrc.microsoft.com']
        if not any(url.hostname==domain or url.hostname.endswith('.'+domain) for domain in allowed):raise HTTPException(422,'Source domain is not allowlisted for this manufacturer or Microsoft. See docs to extend the official-source map.')
        a=dict(body.model_dump(),id=uuid4().hex,manufacturer=device['manufacturer'],model=device['model'],published_at=None,retrieved_at=None,created_at=now(),status='unverified official-domain bookmark')
        db.execute('INSERT INTO advisories VALUES(?,?,?)',(a['id'],body.device_id,dumps(a)));audit(db,'official_source_added',body.device_id)
        return a

@app.get('/api/activity')
def activity():
    with connection() as db:return [dict(r) for r in db.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 500')]

class ExportEvent(StrictModel):
    id:int
    kind:str=Field(max_length=100)
    notes:str=Field(max_length=10000)
    timestamp:datetime
    data:Dict[str,Any]
    case_id:str

class ExportCase(CaseCreate):
    id:str=Field(pattern=r'^[A-Za-z0-9_-]{1,80}$')
    record_type:Literal['technician','public aggregate','fictional technician-reviewed']
    state:Literal['reported','investigation','diagnosed','repaired','post_tested','approved','handover','follow_up']
    outcome:Literal['outcome unknown','working at handover','confirmed working at follow-up','repeat failure reported']
    review_status:Literal['pending','approved','rejected']
    follow_up:Literal['pending','unknown','confirmed working','repeat failure']
    parent_id:Optional[str]
    created_at:datetime
    events:List[ExportEvent]=Field(max_length=10000)

class ExportAdvisory(Advisory):
    id:str=Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    manufacturer:str
    model:str
    published_at:Optional[datetime]
    retrieved_at:Optional[datetime]
    created_at:datetime
    status:Literal['unverified official-domain bookmark']

class Workspace(StrictModel):
    schema_version:Literal['1.0']
    kind:Literal['faultline-workspace']
    exported_at:datetime
    reports:List[Report]=Field(max_length=10000)
    cases:List[ExportCase]=Field(max_length=10000)
    advisories:List[ExportAdvisory]=Field(default_factory=list,max_length=10000)
    settings:Settings
    limitations:str

@app.get('/api/export')
def export():
    with connection() as db:
        data={'schema_version':'1.0','kind':'faultline-workspace','exported_at':now(),'reports':[json.loads(r[0]) for r in db.execute('SELECT report FROM scans WHERE report IS NOT NULL')],'cases':[get_case(db,r[0]) for r in db.execute('SELECT id FROM cases')],'advisories':[json.loads(r[0]) for r in db.execute('SELECT payload FROM advisories')],'settings':settings(db),'limitations':'Attachment bytes and audit logs are excluded. Notes and attachments may contain user-entered sensitive data; review before sharing. Hardware serial numbers and machine names are not collected. Pairing token is never exported.'}
        return Workspace.model_validate(data).model_dump(mode='json')

@app.post('/api/import')
def import_data(body:Dict[str,Any]):
    try:
        if body.get('kind')=='faultline-workspace':bundle=Workspace.model_validate(body);reports=bundle.reports
        else:bundle=None;reports=[Report.model_validate(body)]
    except ValidationError as exc:raise HTTPException(422,str(exc))
    with connection() as db:
        count=0
        for report in reports:
            existing=db.execute('SELECT report FROM scans WHERE id=?',(report.id,)).fetchone()
            if existing and existing[0]:continue
            count+=int(ingest(db,report))
        if bundle:
            new_cases=[]
            for case in bundle.cases:
                if db.execute('SELECT 1 FROM cases WHERE id=?',(case.id,)).fetchone():continue
                payload=case.model_dump(mode='json');save_case(db,payload);new_cases.append(payload)
            for c in new_cases:
                if c['parent_id'] and not db.execute('SELECT 1 FROM cases WHERE id=?',(c['parent_id'],)).fetchone():raise HTTPException(422,'Missing linked parent case')
                mapping={}
                for event in c['events']:
                    if event['case_id']!=c['id']:raise HTTPException(422,'Event references a different case')
                    data=event['data'].copy()
                    if 'evidence_ids' in data:
                        if not all(i in mapping for i in data['evidence_ids']):raise HTTPException(422,'Missing referenced evidence event')
                        data['evidence_ids']=[mapping[i] for i in data['evidence_ids']];data['evidence']=','.join(map(str,data['evidence_ids']))
                    cursor=db.execute('INSERT INTO case_events(case_id,kind,notes,timestamp,data) VALUES(?,?,?,?,?)',(c['id'],event['kind'],event['notes'],event['timestamp'],dumps(data)))
                    mapping[event['id']]=cursor.lastrowid
                index_case(db,c['id'])
            for advisory in bundle.advisories:
                require_device(db,advisory.device_id)
                parsed=urlparse(advisory.url)
                if parsed.scheme!='https' or not parsed.hostname:raise HTTPException(422,'Invalid advisory URL')
                db.execute('INSERT OR IGNORE INTO advisories VALUES(?,?,?)',(advisory.id,advisory.device_id,advisory.model_dump_json()))
            # Importing a bundle must never silently opt a machine into monitoring.
            imported_settings=bundle.settings.model_dump();imported_settings['scheduled_monitoring']=False
            db.execute('INSERT INTO settings VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(dumps(imported_settings),))
        audit(db,'data_imported',str(count))
    return {'reports_imported':count,'cases_imported':len(new_cases) if bundle else 0}

class Confirmation(StrictModel):confirmation:str

@app.post('/api/retention')
def retention(body:Confirmation):
    if body.confirmation!='DELETE OLD SCANS':raise HTTPException(400,'Explicit confirmation required')
    with connection() as db:
        cutoff=(datetime.now(timezone.utc)-timedelta(days=settings(db)['retention_days'])).isoformat()
        deleted=db.execute('DELETE FROM scans WHERE completed_at<?',(cutoff,)).rowcount
        db.execute('DELETE FROM warnings');audit(db,'retention_applied',str(deleted))
    return {'deleted':deleted}

@app.delete('/api/workspace')
def delete_workspace(body:Confirmation):
    if body.confirmation!='DELETE ALL DATA':raise HTTPException(400,'Explicit confirmation required')
    with connection() as db:
        for table in ('warnings','measurements','scans','advisories','devices','attachments','case_events','case_search','cases','settings','audit'):db.execute('DELETE FROM '+table)
        audit(db,'workspace_deleted','local')
    shutil.rmtree(store.DATA/'evidence',ignore_errors=True)
    return {'deleted':True}

if __name__=='__main__':
    import uvicorn
    uvicorn.run('apps.api.main:app',host='127.0.0.1',port=8000,log_level='info')
