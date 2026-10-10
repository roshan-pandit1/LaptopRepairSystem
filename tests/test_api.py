import copy
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from apps.api import db, main
from apps.api.demo import DEVICE, demo_measurements
from packages.schemas.report import Measurement, Report, now

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path)
    monkeypatch.setenv('FAULTLINE_PAIRING_TOKEN','test-pairing-secret')
    main.agent_seen=None;main.agent_device=None
    with TestClient(main.app) as client:yield client

def report(ident='real-report',days=0,capacity=90,scenario='healthy'):
    stamp=(datetime.now(timezone.utc)-timedelta(days=days,seconds=1)).isoformat()
    return {'schema_version':'1.0','id':ident,'device':dict(DEVICE,id='real-test',demo=False),'started_at':stamp,'completed_at':stamp,'status':'completed','categories':['battery','storage','cooling','ram','system'],'measurements':[m for c in ['battery','storage','cooling','ram','system'] for m in demo_measurements(c,scenario,stamp,capacity)]}

def new_case(client):
    response=client.post('/api/cases',json={'title':'Intermittent power loss','brand':'Lenovo','model':'T14','symptom':'Shutdown under load','fault_group':'power'})
    assert response.status_code==200,response.text
    return response.json()['id']

def event(client,ident,kind,data=None,status=200):
    response=client.post(f'/api/cases/{ident}/events',json={'kind':kind,'notes':'Evidence for '+kind,'data':data or {}})
    assert response.status_code==status,response.text
    return response.json()

def test_report_contract_zero_missing_unsupported():
    data=report();data['measurements'][0]['value']=0
    assert Report.model_validate(data).measurements[0].value==0
    data['measurements'][0]['status']='unsupported'
    with pytest.raises(ValidationError):Report.model_validate(data)
    data['measurements'][0]['value']=None
    assert Report.model_validate(data).measurements[0].value is None
    data['schema_version']='2.0'
    with pytest.raises(ValidationError):Report.model_validate(data)

def test_report_rejects_times_missing_category_and_nan():
    data=report();data['measurements']=[m for m in data['measurements'] if m['component']!='battery']
    with pytest.raises(ValidationError):Report.model_validate(data)
    data['status']='cancelled';Report.model_validate(data)
    data['measurements'][0]['value']=float('nan')
    with pytest.raises(ValidationError):Report.model_validate(data)

def test_pairing_origin_and_demo_isolation(client):
    assert client.post('/api/agent/reports',json=report()).status_code==401
    assert client.post('/api/agent/reports',json=report(),headers={'Authorization':'Bearer wrong'}).status_code==401
    assert client.post('/api/agent/reports',json=report(),headers={'Authorization':'Bearer test-pairing-secret'}).status_code==200
    forged=report('forged');forged['device']['id']='demo-thinkpad'
    assert client.post('/api/agent/reports',json=forged,headers={'Authorization':'Bearer test-pairing-secret'}).status_code==409
    assert client.post('/api/cases',json={},headers={'Origin':'https://evil.example'}).status_code==403
    assert client.get('/api/devices',headers={'Host':'evil.example'}).status_code==403

def test_trends_warning_evidence_and_unavailable(client):
    for i,(days,value) in enumerate([(60,94),(30,86),(0,74)]):
        assert client.post('/api/import',json=report('trend-'+str(i),days,value)).status_code==200
    warnings=client.get('/api/devices/real-test/warnings').json()
    battery=[w for w in warnings if w['component']=='battery'][0]
    assert len(battery['evidence_ids'])==3
    history=client.get('/api/devices/real-test/history').json()
    assert set(battery['evidence_ids'])<={m['id'] for m in history}
    unavailable=report('unavailable',scenario='unavailable')
    assert client.post('/api/import',json=unavailable).status_code==200
    assert client.get('/api/devices/real-test/warnings').json()==[]

def test_no_same_day_manufactured_trend(client):
    for i in range(3):client.post('/api/import',json=report('same-day-'+str(i),capacity=90-i*10))
    assert not any(w['component']=='battery' for w in client.get('/api/devices/real-test/warnings').json())

def test_full_repair_workflow_failed_tests_and_repeat(client):
    ident=new_case(client)
    event(client,ident,'repair',status=409)
    case=event(client,ident,'test',{'result':'fail'})
    evidence_id=case['events'][-1]['id']
    event(client,ident,'confirmed_cause',{'evidence':'999999'},422)
    event(client,ident,'suspected_cause')
    event(client,ident,'confirmed_cause',{'evidence':str(evidence_id)})
    event(client,ident,'repair',{'part':'DC jack'})
    assert event(client,ident,'post_test',{'result':'fail'})['state']=='investigation'
    event(client,ident,'confirmed_cause',{'evidence':str(evidence_id)},409)
    case=event(client,ident,'test',{'result':'pass'})
    event(client,ident,'confirmed_cause',{'evidence':str(case['events'][-1]['id'])})
    event(client,ident,'repair',{'part':'Input board'})
    event(client,ident,'post_test',{'result':'pass'})
    event(client,ident,'review',{'result':'approved'},422)
    event(client,ident,'review',{'result':'approved','reviewer':'A technician'})
    event(client,ident,'handover')
    assert event(client,ident,'follow_up',{'result':'working'})['outcome']=='confirmed working at follow-up'
    case=event(client,ident,'repeat_failure')
    child=client.get('/api/cases/'+case['events'][-1]['data']['linked_case_id']).json()
    assert child['parent_id']==ident and child['state']=='investigation'
    assert any(e['kind']=='review' for e in case['events'])

def test_search_fts_filters_and_similarity(client):
    assert client.get('/api/cases?q=battery&brand=Lenovo').json()
    assert client.get('/api/cases?q=battery&brand=HP').json()==[]
    ident=new_case(client);event(client,ident,'test',{'result':'pass'})
    assert any(c['id']==ident for c in client.get('/api/cases?q=intermittent&tests=Evidence').json())
    assert client.get('/api/cases?q=%22%20OR%20*').status_code==200
    similar=client.get('/api/cases/FL-001/similar').json()
    assert similar and all('match_reasons' in c and 'differences' in c for c in similar)

def test_export_import_transaction_persistence(client):
    ident=new_case(client)
    exported=client.get('/api/export');assert exported.status_code==200,exported.text
    bundle=exported.json();count=len(client.get('/api/cases').json())
    assert client.post('/api/import',json=bundle).status_code==200
    assert len(client.get('/api/cases').json())==count
    with TestClient(main.app) as restarted:assert restarted.get('/api/cases/'+ident).status_code==200
    invalid=copy.deepcopy(bundle);invalid['reports'][0]['measurements'][0]['status']='pretend'
    assert client.post('/api/import',json=invalid).status_code==422
    assert client.request('DELETE','/api/workspace',json={'confirmation':'no'}).status_code==400
    assert client.request('DELETE','/api/workspace',json={'confirmation':'DELETE ALL DATA'}).status_code==200
    assert client.post('/api/import',json=bundle).status_code==200
    assert client.get('/api/cases/'+ident).status_code==200
    assert client.get('/api/devices/demo-thinkpad/history').json()

def test_advisory_exact_model_and_upload(client):
    assert client.post('/api/advisories',json={'device_id':'demo-thinkpad','title':'Support','url':'https://evil.example','applicability':'T14'}).status_code==422
    a=client.post('/api/advisories',json={'device_id':'demo-thinkpad','title':'Support','url':'https://support.lenovo.com/','applicability':'Verify exact T14 generation on official site'}).json()
    assert a['published_at'] is None and a['retrieved_at'] is None
    ident=new_case(client)
    attachment=client.post(f'/api/cases/{ident}/attachments',files={'file':('evidence.txt',b'bench evidence')})
    assert attachment.status_code==200
    response=client.get('/api/attachments/'+attachment.json()['id'])
    assert response.content==b'bench evidence' and 'attachment' in response.headers['content-disposition']

def test_agent_progress_cancel_and_permissions(client):
    auth={'Authorization':'Bearer test-pairing-secret'};device=report()['device']
    assert client.post('/api/agent/poll',json=device,headers=auth).status_code==200
    job=client.post('/api/scans',json={'device_id':device['id'],'categories':['battery']}).json()
    assert client.post(f'/api/agent/scans/{job["id"]}/progress',json={'completed_categories':['ram']},headers=auth).status_code==422
    client.post(f'/api/scans/{job["id"]}/cancel')
    assert client.post(f'/api/agent/scans/{job["id"]}/progress',json={'completed_categories':[]},headers=auth).json()['cancel_requested']
    config=client.get('/api/settings').json();config['permissions']=['battery'];client.put('/api/settings',json=config)
    assert client.post('/api/scans',json={'device_id':'demo-thinkpad','categories':['storage']}).status_code==403

def test_retention_preserves_repairs_and_deletion_stays_empty(client):
    config=client.get('/api/settings').json();config['retention_days']=1
    client.put('/api/settings',json=config)
    assert client.post('/api/retention',json={'confirmation':'DELETE OLD SCANS'}).json()['deleted']==3
    assert len(client.get('/api/cases').json())==7
    client.request('DELETE','/api/workspace',json={'confirmation':'DELETE ALL DATA'})
    with TestClient(main.app) as restarted:assert restarted.get('/api/devices').json()==[]

def test_public_aggregate_missing_fields_stay_missing(client):
    case=client.post('/api/cases',json={'title':'External aggregate: no power','symptom':'No power','fault_group':'power','record_type':'public aggregate'}).json()
    assert case['brand'] is None and case['model'] is None
    assert case['outcome']=='outcome unknown' and case['review_status']=='pending'
    event(client,case['id'],'confirmed_cause',{'evidence':'1'},409)
    assert client.get('/api/cases/'+case['id']+'/similar').status_code==200
    assert client.get('/api/export').status_code==200

def test_configured_threshold_storage_counter_and_error_rules(client):
    first=report('counters-old',days=1)
    first['measurements'].append(dict(first['measurements'][3],key='storage_read_errors',value=2,unit='errors'))
    second=report('counters-new')
    second['measurements'].append(dict(second['measurements'][3],key='storage_read_errors',value=8,unit='errors'))
    for m in second['measurements']:
        if m['key']=='storage_health':m['value']='Warning'
        if m['key']=='recent_system_errors':m['value']=8
    for value in (first,second):assert client.post('/api/import',json=value).status_code==200
    findings=client.get('/api/devices/real-test/warnings').json()
    assert findings[0]['severity']=='critical'
    assert any(w['title']=='Storage error counter increased' and len(w['evidence_ids'])==2 for w in findings)
    assert any(w['component']=='system' for w in findings)
    config=client.get('/api/settings').json();config['rules']['event_count']=10
    client.put('/api/settings',json=config)
    assert not any(w['component']=='system' for w in client.get('/api/devices/real-test/warnings').json())

def test_import_transaction_rollback_and_monitoring_opt_in(client):
    bundle=client.get('/api/export').json()
    bundle['reports'].append(report('should-rollback'))
    new=copy.deepcopy(bundle['cases'][0]);new['id']='import-broken';new['parent_id']='missing-parent';bundle['cases'].append(new)
    assert client.post('/api/import',json=bundle).status_code==422
    assert client.get('/api/scans/should-rollback').status_code==404
    assert client.get('/api/cases/import-broken').status_code==404
    good=client.get('/api/export').json();good['settings']['scheduled_monitoring']=True
    assert client.post('/api/import',json=good).status_code==200
    assert not client.get('/api/settings').json()['scheduled_monitoring']
