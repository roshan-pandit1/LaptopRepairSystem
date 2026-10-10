"""Transparent rules; no failure probabilities or generic thermal thresholds."""
import json
from .db import dumps, settings

def evaluate(db, device_id):
    rows=[dict(json.loads(r['payload']),id=r['id'],scan_id=r['scan_id']) for r in db.execute('SELECT * FROM measurements WHERE device_id=? ORDER BY timestamp,id',(device_id,))]
    # Only evaluate current observations from the latest report, not stale available values.
    latest=db.execute('SELECT id FROM scans WHERE device_id=? AND report IS NOT NULL ORDER BY completed_at DESC LIMIT 1',(device_id,)).fetchone()
    current=[m for m in rows if latest and m['scan_id']==latest[0] and m['status']=='available']
    config=settings(db)['rules']; warnings=[]
    def emit(key,m,title,observed,rule,interpretation,next_check,evidence=None,severity='attention'):
        warnings.append({'id':f'{device_id}-{key}','component':m['component'],'severity':severity,'title':title,'observed':observed,'rule':rule,'interpretation':interpretation,'next_check':next_check,'evidence_ids':[x['id'] for x in (evidence or [m])]})
    for m in current:
        key=m['key'];v=m['value']
        if key.startswith('disk_free_percent') and isinstance(v,(int,float)) and v<config['low_space_percent']:
            emit(key,m,'System storage is running low',f'{v:g}% free space observed at {m["timestamp"]}.',f'Free space < {config["low_space_percent"]}%; critical below {config["critical_space_percent"]}%.','Low free space can disrupt updates and temporary files; it does not establish a failing drive.','Review space usage with the owner before removing anything.',severity='critical' if v<config['critical_space_percent'] else 'attention')
        if key.startswith('full_charge_capacity') and isinstance(v,(int,float)):
            series=[x for x in rows if x['key']==key and x['status']=='available' and isinstance(x['value'],(int,float)) and x['source']==m['source'] and x['unit']==m['unit']]
            # Deduplicate same-day snapshots so retries do not manufacture a trend.
            series=list({x['timestamp'][:10]:x for x in series}.values())[-6:]
            if len(series)>=3 and series[0]['value']-v>=config['battery_drop_points'] and all(a['value']>=b['value'] for a,b in zip(series,series[1:])):
                emit(key,m,'Battery capacity is trending downward',f'Full-charge capacity changed from {series[0]["value"]:g}% to {v:g}% of design across {len(series)} measurement days.',f'At least 3 days, non-increasing capacity, ≥{config["battery_drop_points"]} percentage-point decline.','Future-risk warning: runtime may continue to decline. Firmware estimates, calibration and usage affect this signal; it cannot predict a failure date.','Repeat a battery report and compare real runtime. Inspect for swelling if physical symptoms are reported.',series)
        if key.startswith('storage_health') and str(v).lower() not in ('healthy','ok','0'):
            emit(key,m,'Supported storage health warning',f'{v} reported by {m["source"]} at {m["timestamp"]}.','Provider health status is not Healthy/OK.','A provider reports degraded health; this does not locate the failed component.','Back up important data and run the official read-only storage diagnostic.',severity='critical')
        if key.startswith(('storage_read_errors','storage_write_errors')) and isinstance(v,(int,float)):
            previous=[x for x in rows if x['key']==key and x['id']!=m['id'] and x['status']=='available' and x['source']==m['source'] and isinstance(x['value'],(int,float))]
            if previous and v>previous[-1]['value']:
                emit(key,m,'Storage error counter increased',f'{previous[-1]["value"]:g} → {v:g} reported errors.','Same provider/key counter increased between scans.','Counters may reset or change meaning after device replacement. This observation is not a confirmed drive failure.','Check backup status and correlate with official storage tests.',[previous[-1],m])
        if key=='recent_system_errors' and isinstance(v,(int,float)) and v>=config['event_count']:
            emit(key,m,'Repeated relevant system error events',f'{v:g} selected events in the last 7 days at {m["timestamp"]}.',f'Selected system event count ≥ {config["event_count"]}.','Events may be consequences of power loss or software problems, not their root cause.','Correlate event IDs and timestamps with the reported symptom.')
    db.execute('DELETE FROM warnings WHERE device_id=?',(device_id,))
    for w in warnings:db.execute('INSERT INTO warnings VALUES(?,?,?)',(w['id'],device_id,dumps(w)))
    return sorted(warnings,key=lambda w:w['severity']!='critical')
