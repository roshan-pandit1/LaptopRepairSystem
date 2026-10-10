"""Explicitly fictional fixtures. This module is never used by the Windows collector."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from packages.schemas.report import Report, now
from .db import dumps, save_case, index_case, audit

DEVICE={'id':'demo-thinkpad','manufacturer':'Lenovo','model':'ThinkPad T14 Gen 2','os':'Windows 11 Pro · 23H2','demo':True}

def demo_measurements(category, scenario='warning', timestamp=None, capacity=72):
    timestamp=timestamp or now()
    values={
        'battery':[('full_charge_capacity',capacity,' % of design'),('cycle_count',486,'cycles'),('design_capacity',50000,'mWh')],
        'storage':[('disk_free_percent',6.8 if scenario=='warning' else 38.4,'%'),('disk_free_gb',34.8 if scenario=='warning' else 196.6,'GB'),('storage_health','Healthy',None)],
        'cooling':[('cpu_usage',12,'%'),('cpu_model','Intel Core i5-1135G7',None)],
        'ram':[('installed_ram',16,'GB'),('ram_usage',43,'%')],
        'system':[('recent_system_errors',0,'events / 7 days'),('os_version','Windows 11 Pro 23H2',None)]}
    result=[]
    for key,value,unit in values[category]:
        unsupported=scenario=='unavailable'
        result.append({'key':key,'component':category,'value':None if unsupported else value,'unit':unit,'timestamp':timestamp,'source':'Fictional demo fixture / not a hardware measurement','status':'unsupported' if unsupported else 'available','limitation':'Simulated evidence for interface exploration only.'})
    if category=='cooling':
        result.append({'key':'cpu_temperature','component':'cooling','value':None,'unit':'°C','timestamp':timestamp,'source':'No trustworthy temperature provider configured','status':'unsupported','limitation':'ACPI thermal zones are not assumed to represent CPU package temperature.'})
    return result

def seed(db, ingest):
    if db.execute('SELECT 1 FROM devices').fetchone() or db.execute("SELECT 1 FROM audit WHERE action='workspace_deleted'").fetchone():
        return
    for days,capacity in [(90,88),(60,84),(30,79),(0,72)]:
        stamp=(datetime.now(timezone.utc)-timedelta(days=days, seconds=1)).isoformat()
        ingest(db, Report.model_validate({'schema_version':'1.0','id':f'demo-scan-{days}','device':DEVICE,'started_at':stamp,'completed_at':stamp,'status':'completed','categories':['battery','storage','cooling','ram','system'],'measurements':[m for c in ['battery','storage','cooling','ram','system'] for m in demo_measurements(c,timestamp=stamp,capacity=capacity)]}))
    fixtures=[
        ('FL-001','Fan obstruction under sustained load','Lenovo','ThinkPad T14 Gen 2','Fan runs loudly; shutdown during long compilation.','cooling','Airflow inspection found lint blocking fins.','Cleaned cooling assembly; no parts replaced.','working at handover'),
        ('FL-002','Short runtime with declining battery capacity','Lenovo','ThinkPad T14 Gen 2','Battery runtime declined over three months.','battery','Repeated capacity reports and controlled runtime test support pack deterioration.','Replaced battery pack.','confirmed working at follow-up'),
        ('FL-003','Low free space causing update failures','Dell','Latitude 5420','System updates fail; disk free space is 4%.','storage','Free-space measurement confirmed insufficient system volume capacity.','Owner-approved cleanup; no hardware replaced.','confirmed working at follow-up'),
        ('FL-004','Storage reliability warning and intermittent stalls','HP','EliteBook 840 G8','Storage warning; intermittent read stalls.','storage','Supported counters and read-only vendor test identified media errors.','Replaced SSD after owner-managed backup.','working at handover'),
        ('FL-005','No power with a known-good adapter','Dell','Latitude 5420','No power indicator; does not start on battery or AC.','power','Bench inspection found an open input fuse.','Board-level fuse replacement and short-circuit investigation.','outcome unknown'),
        ('FL-006','Repeat shutdown after initial fan service','Lenovo','ThinkPad T14 Gen 2','Overheating returned after initial repair and handover.','cooling','Initial dust removal restored airflow but did not resolve intermittent fan operation.','Initial fan service; linked attempt replaces fan.','repeat failure reported')]
    for ident,title,brand,model,symptom,fault,cause,repair,outcome in fixtures:
        case={'id':ident,'title':title,'brand':brand,'model':model,'category':'Laptop','symptom':symptom,'fault_group':fault,'state':'follow_up' if 'follow-up' in outcome else 'handover','outcome':outcome,'review_status':'approved','follow_up':'confirmed working' if 'follow-up' in outcome else 'pending','record_type':'fictional technician-reviewed','parent_id':None,'created_at':now()}
        if ident=='FL-005':
            case.update(state='investigation',review_status='pending',follow_up='unknown')
        save_case(db,case)
        events=[('reported',symptom,{}),('test','Fictional bench test: '+cause,{'result':'pass'}),('suspected_cause',cause,{})]
        if ident!='FL-005':
            events += [('confirmed_cause',cause,{'evidence':'fictional test record above'}),('repair',repair,{'part':'battery' if ident=='FL-002' else 'SSD' if ident=='FL-004' else ''}),('post_test','Fictional post-repair verification passed.',{'result':'pass'}),('review','Fictional technician review accepted.',{'result':'approved','reviewer':'Demo reviewer'}),('handover','Working at handover.',{})]
        if 'follow-up' in outcome: events.append(('follow_up','Owner confirmed operation at 30 days.',{'result':'working'}))
        for kind,notes,data in events:
            db.execute('INSERT INTO case_events(case_id,kind,notes,timestamp,data) VALUES(?,?,?,?,?)',(ident,kind,notes,now(),dumps(data)))
        index_case(db,ident)
    repeat={'id':'FL-006-R2','title':'Repeat investigation: intermittent fan','brand':'Lenovo','model':'ThinkPad T14 Gen 2','category':'Laptop','symptom':'Repeat shutdown; fan occasionally fails to start.','fault_group':'cooling','state':'investigation','outcome':'outcome unknown','review_status':'pending','follow_up':'pending','record_type':'fictional technician-reviewed','parent_id':'FL-006','created_at':now()}
    save_case(db,repeat)
    db.execute('INSERT INTO case_events(case_id,kind,notes,timestamp,data) VALUES(?,?,?,?,?)',('FL-006','repeat_failure','Repeat failure preserved; new investigation FL-006-R2.',now(),dumps({'linked_case_id':'FL-006-R2'})))
    index_case(db,'FL-006');index_case(db,'FL-006-R2')
    audit(db,'fictional_demo_seeded','demo-thinkpad')
