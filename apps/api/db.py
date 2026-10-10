"""Repository boundary: SQL stays here or in API services, not in wire contracts."""
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get('FAULTLINE_DATA_DIR', str(ROOT / 'data' / 'local')))

@contextmanager
def connection():
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DATA / 'faultline.sqlite3'), timeout=20)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA journal_mode=WAL')
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def migrate():
    with connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY)')
        versions = {r[0] for r in db.execute('SELECT version FROM schema_migrations')}
        for path in sorted((Path(__file__).parent / 'migrations').glob('*.sql')):
            if int(path.name.split('_')[0]) not in versions:
                db.executescript(path.read_text())

def dumps(value):
    return json.dumps(value, separators=(',', ':'), ensure_ascii=False)

def audit(db, action, entity_id):
    from packages.schemas.report import now
    db.execute('INSERT INTO audit(action,entity_id,timestamp) VALUES(?,?,?)', (action, entity_id, now()))

def get_case(db, case_id):
    row = db.execute('SELECT payload FROM cases WHERE id=?', (case_id,)).fetchone()
    if not row:
        return None
    case = json.loads(row[0])
    case['events'] = [dict(r, data=json.loads(r['data'])) for r in db.execute('SELECT * FROM case_events WHERE case_id=? ORDER BY id', (case_id,))]
    return case

def index_case(db, case_id):
    case = get_case(db, case_id)
    db.execute('DELETE FROM case_search WHERE case_id=?', (case_id,))
    db.execute('INSERT INTO case_search(case_id,content) VALUES(?,?)', (case_id, dumps(case)))

def save_case(db, case):
    payload = {k:v for k,v in case.items() if k not in ('events','match_reasons','differences','score')}
    db.execute('INSERT INTO cases(id,payload) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload', (case['id'], dumps(payload)))

DEFAULT_SETTINGS = {'permissions':['battery','storage','cooling','ram','system'], 'retention_days':365, 'scheduled_monitoring':False, 'rules':{'low_space_percent':10, 'critical_space_percent':3, 'battery_drop_points':8, 'event_count':5}, 'ai_enabled':False}

def settings(db):
    row = db.execute('SELECT payload FROM settings WHERE id=1').fetchone()
    return json.loads(row[0]) if row else DEFAULT_SETTINGS.copy()
