"""Read-only macOS adapters. No sudo, SMC access, drivers, or Apple Diagnostics invocation."""
import json
import os
import plistlib
import re
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from packages.schemas.report import Device
from .collector import CollectionError, failure, m

COMMANDS = {
    'hardware': ['/usr/sbin/system_profiler', 'SPHardwareDataType', '-json'],
    'power': ['/usr/sbin/system_profiler', 'SPPowerDataType', '-json'],
    'battery': ['/usr/sbin/ioreg', '-a', '-r', '-c', 'AppleSmartBattery'],
    'os': ['/usr/bin/sw_vers', '-productVersion'],
    'build': ['/usr/bin/sw_vers', '-buildVersion'],
    'model': ['/usr/sbin/sysctl', '-n', 'hw.model'],
    'cpu_model': ['/usr/sbin/sysctl', '-n', 'machdep.cpu.brand_string'],
    'cpu_count': ['/usr/sbin/sysctl', '-n', 'hw.logicalcpu'],
    'ram': ['/usr/sbin/sysctl', '-n', 'hw.memsize'],
    'vm': ['/usr/bin/vm_stat'],
    'cpu': ['/usr/bin/top', '-l', '2', '-s', '1', '-n', '0'],
    'storage': ['/usr/sbin/diskutil', 'info', '-plist', '/'],
}

def command(key):
    if key not in COMMANDS:
        raise ValueError('Unknown macOS diagnostic command')
    try:
        result = subprocess.run(COMMANDS[key], capture_output=True, timeout=30,
                                shell=False, env={**os.environ, 'LC_ALL':'C', 'LANG':'C'})
    except subprocess.TimeoutExpired:
        raise CollectionError('collection_failed', 'macOS provider exceeded its 30-second timeout.')
    except OSError:
        raise CollectionError('unsupported', 'The built-in macOS provider is not available.')
    if result.returncode:
        error = result.stderr.decode('utf-8', errors='replace').lower()
        denied = 'not permitted' in error or 'permission denied' in error
        raise CollectionError('permission_denied' if denied else 'collection_failed',
                              'macOS provider access was denied; no elevation attempted.' if denied else 'macOS provider failed; other checks continue.')
    return result.stdout

def text(query, key):
    value = query(key)
    return value.decode('utf-8').strip() if isinstance(value, bytes) else str(value).strip()

def hardware(query=command):
    data = json.loads(query('hardware')).get('SPHardwareDataType', [])
    # Do not retain serial numbers, hardware UUIDs, provisioning IDs, or machine names.
    return {key: data[0].get(key) for key in ('machine_name','machine_model','chip_type')} if data else {}

def identity(state_dir=None, query=command):
    directory = Path(state_dir) if state_dir else Path(__file__).resolve().parents[2] / 'data' / 'local' / 'agent'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'macos-device-id'
    if not path.exists():
        path.write_text('mac-' + uuid4().hex, encoding='utf-8')
        path.chmod(0o600)
    try:
        info = hardware(query)
        model = ' '.join(str(info[k]) for k in ('machine_name','machine_model') if info.get(k))
    except (CollectionError, ValueError, TypeError):
        model = ''
    if not model:
        try:model = text(query, 'model')
        except CollectionError:model = 'Mac (model unavailable)'
    try:os_version = 'macOS ' + text(query, 'os')
    except CollectionError:os_version = 'macOS (version unavailable)'
    return Device(id=path.read_text().strip(), manufacturer='Apple', model=model, os=os_version, demo=False)

def numeric(value):
    if isinstance(value, bool):return None
    if isinstance(value, (int, float)):return value
    if isinstance(value, str):
        match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*%?\s*', value)
        if match:return float(match.group(1))
    return None

def battery(query):
    packs = [pack for pack in plistlib.loads(query('battery'))
             if pack.get('BatteryInstalled') is not False and pack.get('IsPresent') is not False]
    if not packs:
        return [m('battery_presence','battery',status='unsupported',source='IORegistry AppleSmartBattery',
                  limitation='No built-in battery is exposed by this Mac. This is expected on desktop Macs such as Mac mini; it is not a battery fault.')]
    output = []
    for index, pack in enumerate(packs):
        suffix = '' if index == 0 else '_' + str(index)
        source = 'IORegistry AppleSmartBattery; pack index ' + str(index)
        output.append(m('cycle_count'+suffix,'battery',numeric(pack.get('CycleCount')),'cycles',source=source,
                        limitation='Firmware-reported cycles; missing data remains unknown.'))
        # MaxCapacity alone may be a normalized 0–100 value on Apple Silicon.
        # Never divide it by a raw mAh design capacity.
        design = numeric(pack.get('DesignCapacity'))
        full = numeric(pack.get('AppleRawMaxCapacity'))
        output.append(m('design_capacity'+suffix,'battery',design,'mAh',source=source,
                        limitation='Firmware estimate in mAh, not mWh; unavailable on some models.'))
        ratio = round(full/design*100,2) if full is not None and design and design > 0 else None
        output.append(m('full_charge_capacity'+suffix,'battery',ratio,' % of design',source=source,
                        limitation='Calculated only from raw AppleRawMaxCapacity and DesignCapacity in matching mAh units. Firmware recalibration or replacement affects trends.'))
        output.append(m('battery_charging'+suffix,'battery',('Charging' if pack['IsCharging'] else 'Not charging') if 'IsCharging' in pack else None,
                        source=source,limitation='Current charging state, not an assessment of battery health.'))
    return output

def collect_category(category, query=command, disk_usage=shutil.disk_usage):
    if category not in ('battery','storage','cooling','ram','system'):
        raise ValueError('Unknown diagnostic category')
    output = []
    def check(key, source, fn):
        try:output.extend(fn())
        except CollectionError as error:output.append(failure(category,key,error,source))
        except (ValueError, TypeError, KeyError, IndexError, OSError, plistlib.InvalidFileException):
            output.append(m(key,category,status='collection_failed',source=source,
                            limitation='The macOS response could not be interpreted safely; other checks continue.'))
    if category == 'battery':
        check('battery_report','IORegistry AppleSmartBattery',lambda:battery(query))
    elif category == 'cooling':
        check('cpu_model','sysctl machdep.cpu.brand_string',lambda:[m('cpu_model',category,text(query,'cpu_model'),source='sysctl machdep.cpu.brand_string')])
        check('cpu_count','sysctl hw.logicalcpu',lambda:[m('logical_cpus',category,int(text(query,'cpu_count')),'cores',source='sysctl hw.logicalcpu')])
        def usage():
            samples = re.findall(r'CPU usage:.*?([\d.]+)% idle',text(query,'cpu'))
            value = round(100-float(samples[-1]),2) if samples else None
            return [m('cpu_usage',category,value,'%',source='top -l 2 -s 1 -n 0; second CPU summary',
                      limitation='Approximately one-second aggregate usage sample; no per-process names collected and no stress test performed.')]
        check('cpu_usage','macOS top aggregate CPU summary',usage)
        output.append(m('cpu_temperature',category,unit='°C',status='unsupported',source='No supported temperature provider configured',
                        limitation='macOS does not expose a stable, unprivileged CPU temperature interface here. No SMC driver, sudo or third-party sensor software is used.'))
    elif category == 'ram':
        check('installed_ram','sysctl hw.memsize',lambda:[m('installed_ram',category,round(int(text(query,'ram'))/1024**3,2),'GiB',source='sysctl hw.memsize',limitation='Installed capacity; this is not a memory-integrity test.')])
        def memory():
            raw = text(query,'vm')
            page_match = re.search(r'page size of (\d+) bytes',raw)
            counters = {key:int(value) for key,value in re.findall(r'^([^:\n]+):\s+(\d+)\.',raw,re.M)}
            names = ('Pages active','Pages wired down','Pages occupied by compressor')
            size = int(page_match.group(1)) if page_match else None
            used = sum(counters[key] for key in names)*size if size and all(key in counters for key in names) else None
            return [m('ram_active_wired_compressed',category,round(used/1024**3,2) if used is not None else None,'GiB',source='vm_stat: active + wired + compressor physical pages',
                      limitation='Explicit page-accounting snapshot, not Activity Monitor Memory Used or memory pressure. Inactive/cache pages excluded; no RAM integrity test.')]
        check('ram_snapshot','vm_stat',memory)
    elif category == 'storage':
        def space():
            path = '/System/Volumes/Data' if Path('/System/Volumes/Data').is_dir() else '/'
            value = disk_usage(path)
            source = 'statvfs via shutil.disk_usage; '+path
            return [m('disk_free_percent',category,round(value.free/value.total*100,2) if value.total else None,'%',source=source,limitation='Filesystem free capacity; APFS shared space and purgeable data can differ from Finder Available.'),
                    m('disk_free_gb',category,round(value.free/1024**3,2),'GiB',source=source),
                    m('volume_capacity',category,round(value.total/1024**3,2),'GiB',source=source)]
        check('volume_space','macOS filesystem capacity',space)
        def storage():
            info = plistlib.loads(query('storage'))
            health = info.get('SMARTStatus')
            value = 'Healthy' if health == 'Verified' else health if health in ('Failing','Failed') else None
            return [m('storage_health',category,value,status='available' if value else 'unsupported',source='diskutil info -plist /; SMARTStatus',
                      limitation='Verified maps to the provider summary Healthy, not guaranteed hardware health. APFS/device controllers may not expose SMART; raw counters are not inferred.')]
        check('storage_health','diskutil info -plist /',storage)
        output.append(m('storage_reliability_counters',category,status='unsupported',source='Built-in macOS storage interfaces',
                        limitation='Detailed NVMe media-error and wear counters are not exposed by this collector. No third-party utilities are installed.'))
    else:
        for key, command_key in [('os_version','os'),('os_build','build')]:
            check(key,'sw_vers',lambda key=key,command_key=command_key:[m(key,category,text(query,command_key),source='sw_vers '+command_key,
                       limitation='Installed OS inventory only; no claim about update availability.')])
        output.append(m('recent_system_errors',category,unit='events',status='unsupported',source='macOS unified logging (not collected)',
                        limitation='Windows event IDs do not apply to macOS. Unified logs may contain sensitive contents and no validated redacted event adapter is configured; no zero-error claim is made.'))
    return output
