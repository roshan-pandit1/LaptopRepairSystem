"""Read-only Windows collector. All PowerShell scripts are fixed allowlisted strings.

No remote command execution, elevation, stress test, driver install, or remediation.
"""
import argparse
import base64
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from packages.schemas.report import CATEGORIES, Device, Measurement, Report, now

SCRIPTS={
 'inventory':"$c=Get-CimInstance Win32_ComputerSystem; $o=Get-CimInstance Win32_OperatingSystem; [pscustomobject]@{Manufacturer=$c.Manufacturer;Model=$c.Model;OS=$o.Caption;Version=$o.Version} | ConvertTo-Json -Compress",
 'cooling':"Get-CimInstance Win32_Processor | Select-Object Name,LoadPercentage | ConvertTo-Json -Compress",
 'ram':"$c=Get-CimInstance Win32_ComputerSystem; $o=Get-CimInstance Win32_OperatingSystem; [pscustomobject]@{Installed=$c.TotalPhysicalMemory;TotalKB=$o.TotalVisibleMemorySize;FreeKB=$o.FreePhysicalMemory} | ConvertTo-Json -Compress",
 'volumes':"Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | Select-Object DeviceID,Size,FreeSpace | ConvertTo-Json -Compress",
 'storage':"if (-not (Get-Command Get-PhysicalDisk -ErrorAction SilentlyContinue)) { throw 'FAULTLINE_UNSUPPORTED' }; @(Get-PhysicalDisk | Sort-Object DeviceId | Select-Object DeviceId,FriendlyName,MediaType,Size,@{N='HealthStatus';E={$_.HealthStatus.ToString()}}) | ConvertTo-Json -Compress",
 'reliability':"if (-not (Get-Command Get-StorageReliabilityCounter -ErrorAction SilentlyContinue)) { throw 'FAULTLINE_UNSUPPORTED' }; $items=@(); foreach($d in (Get-PhysicalDisk | Sort-Object DeviceId)){try{$r=$d | Get-StorageReliabilityCounter -ErrorAction Stop;$items += [pscustomobject]@{DeviceId=$d.DeviceId;ReadErrors=$r.ReadErrorsTotal;WriteErrors=$r.WriteErrorsTotal;Temperature=$r.Temperature;Status='available'}}catch{$status='collection_failed';if($_.Exception.Message -match 'denied|privilege|0x80070005'){$status='permission_denied'}elseif($_.Exception.Message -match 'not supported|unsupported'){$status='unsupported'};$items += [pscustomobject]@{DeviceId=$d.DeviceId;Status=$status}}}; $items | ConvertTo-Json -Compress",
 'system':"$events=@(Get-WinEvent -FilterHashtable @{LogName='System';StartTime=(Get-Date).AddDays(-7);Level=1,2;Id=7,11,15,41,51,55,129,153,6008} -MaxEvents 1000 -ErrorAction SilentlyContinue); if($Error.Count -gt 0 -and $Error[0].FullyQualifiedErrorId -notmatch 'NoMatchingEventsFound'){throw $Error[0]}; [pscustomobject]@{Count=$events.Count;Events=@($events | Select-Object Id,ProviderName,@{N='Time';E={$_.TimeCreated.ToUniversalTime().ToString('o')}})} | ConvertTo-Json -Depth 4 -Compress"
}

class CollectionError(Exception):
    def __init__(self,status,reason):super().__init__(reason);self.status=status

def run_process(args,timeout=30):
    try:
        result=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),shell=False)
    except subprocess.TimeoutExpired:raise CollectionError('collection_failed',f'Collector command exceeded {timeout}s timeout')
    except (OSError,PermissionError):raise CollectionError('collection_failed','Supported Windows command could not be started')
    if result.returncode:
        error=result.stderr.lower()
        status='permission_denied' if any(x in error for x in ('access is denied','access denied','privilege','0x80070005')) else 'unsupported' if any(x in error for x in ('faultline_unsupported','not supported','not recognized','no batteries')) else 'collection_failed'
        # Never expose raw stderr, usernames, machine names or paths in report/logs.
        raise CollectionError(status,'Windows provider returned '+status.replace('_',' ')+'. Other categories continue.')
    return result.stdout.lstrip('\ufeff').strip()

def powershell(key):
    if key not in SCRIPTS:raise ValueError('Unknown fixed collector command')
    script="$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "+SCRIPTS[key]
    encoded=base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    executable=str(Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32'/'WindowsPowerShell'/'v1.0'/'powershell.exe')
    raw=run_process([executable,'-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',encoded])
    try:return json.loads(raw) if raw else None
    except (ValueError,TypeError):raise CollectionError('collection_failed','Windows provider output was not valid JSON')

def rows(value):return value if isinstance(value,list) else [value] if isinstance(value,dict) else []

def m(key,component,value=None,unit=None,status='available',source='',limitation='Snapshot only; not a comprehensive hardware test.'):
    if value is None and status=='available':status='unknown'
    return Measurement(key=key,component=component,value=value,unit=unit,status=status,source=source,timestamp=now(),limitation=limitation)

def failure(category,key,error,source):
    return m(key,category,status=error.status,source=source,limitation=str(error))

def battery_report():
    with tempfile.TemporaryDirectory(prefix='faultline-battery-') as temp:
        target=Path(temp)/'battery.xml'
        exe=str(Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32'/'powercfg.exe')
        run_process([exe,'/batteryreport','/xml','/output',str(target)],timeout=45)
        if not target.exists():raise CollectionError('unsupported','Windows did not produce a battery report; a battery may not be present.')
        return parse_battery_xml(target.read_bytes())

def parse_battery_xml(text):
    try:root=ET.fromstring(text)
    except ET.ParseError:raise CollectionError('collection_failed','Windows battery report XML could not be parsed')
    for element in root.iter():element.tag=element.tag.split('}')[-1]
    batteries=root.findall('.//Batteries/Battery')
    if not batteries:raise CollectionError('unsupported','No battery is exposed by the Windows battery report provider')
    output=[]
    for index,battery in enumerate(batteries):
        suffix='' if index==0 else '_'+str(index)
        source=f'powercfg /batteryreport XML; battery index {index}'
        def number(name):
            value=battery.findtext(name)
            try:return float(value) if value and value.strip() not in ('-','') else None
            except ValueError:return None
        design=number('DesignCapacity');full=number('FullChargeCapacity');cycles=number('CycleCount')
        output.extend([m('design_capacity'+suffix,'battery',design,'mWh',source=source,limitation='Firmware-reported design capacity; multiple packs are reported separately.'),m('full_charge_capacity'+suffix,'battery',round(full/design*100,2) if design and full is not None else None,' % of design',source=source,limitation='Firmware estimate; calibration and battery replacement affect trends.'),m('cycle_count'+suffix,'battery',cycles,'cycles',source=source,limitation='Not all battery firmware reports cycle count. Unknown is not zero.')])
    return output

def collect_category(category,query=powershell,battery=battery_report):
    if category not in CATEGORIES:raise ValueError('Unknown diagnostic category')
    if category=='battery':
        try:return battery()
        except CollectionError as error:return [failure(category,'battery_report',error,'Windows powercfg /batteryreport')]
    output=[]
    if category=='cooling':
        try:
            cpus=rows(query('cooling'))
            if not cpus:raise CollectionError('unsupported','No Win32_Processor instances exposed')
            for i,cpu in enumerate(cpus):
                output.extend([m('cpu_model' if i==0 else 'cpu_model_'+str(i),category,cpu.get('Name'),source='CIM Win32_Processor'),m('cpu_usage' if i==0 else 'cpu_usage_'+str(i),category,cpu.get('LoadPercentage'),'%',source='CIM Win32_Processor.LoadPercentage',limitation='Single provider snapshot, not sustained load evidence.')])
        except CollectionError as error:output.append(failure(category,'cpu_inventory',error,'CIM Win32_Processor'))
        output.append(m('cpu_temperature',category,unit='°C',status='unsupported',source='No trustworthy CPU package sensor provider configured',limitation='ACPI thermal zones do not reliably identify CPU temperature. No optional sensor software or kernel driver is installed.'))
    if category=='ram':
        try:
            data=query('ram') or {};total=data.get('TotalKB');free=data.get('FreeKB')
            output.extend([m('installed_ram',category,round(data['Installed']/1024**3,2) if data.get('Installed') is not None else None,'GB',source='CIM Win32_ComputerSystem.TotalPhysicalMemory'),m('ram_usage',category,round((1-free/total)*100,2) if total and free is not None else None,'%',source='CIM Win32_OperatingSystem',limitation='Usage snapshot; does not test memory integrity.')])
        except CollectionError as error:output.append(failure(category,'ram_inventory',error,'CIM Win32_ComputerSystem / Win32_OperatingSystem'))
    if category=='storage':
        for capability in ('volumes','storage','reliability'):
            try:
                data=rows(query(capability))
                if not data:raise CollectionError('unsupported','Storage provider returned no supported devices or counters')
                for i,item in enumerate(data):
                    suffix='' if i==0 else '_'+str(i)
                    if capability=='volumes':
                        volume=item.get('DeviceID','unknown volume');size=item.get('Size');free=item.get('FreeSpace');source='CIM Win32_LogicalDisk '+volume
                        output.extend([m('disk_free_percent'+suffix,category,round(free/size*100,2) if size and free is not None else None,'%',source=source,limitation='Free capacity is not a drive health test.'),m('disk_free_gb'+suffix,category,round(free/1024**3,2) if free is not None else None,'GB',source=source)])
                    elif capability=='storage':
                        source='Get-PhysicalDisk; device index '+str(item.get('DeviceId',i))
                        output.extend([m('storage_model'+suffix,category,item.get('FriendlyName'),source=source,limitation='Provider model name; hardware serial identifiers are omitted.'),m('storage_size'+suffix,category,round(item['Size']/1024**3,2) if item.get('Size') is not None else None,'GB',source=source),m('storage_health'+suffix,category,item.get('HealthStatus'),source=source,limitation='Provider health summary; Healthy does not exclude a physical defect.')])
                    else:
                        source='Get-StorageReliabilityCounter; device index '+str(item.get('DeviceId',i));status=item.get('Status','unknown')
                        if status!='available':output.append(m('storage_reliability'+suffix,category,status=status,source=source,limitation='Driver may not support counters or access may require elevation; other checks continue.'));continue
                        for name,key,unit in [('ReadErrors','storage_read_errors','errors'),('WriteErrors','storage_write_errors','errors'),('Temperature','storage_temperature','°C')]:
                            value=item.get(name)
                            if name=='Temperature' and (value is None or value<=0 or value>150):value=None
                            output.append(m(key+suffix,category,value,unit,source=source,limitation='Driver-provided counter. Device indices can change; do not compare across disk replacement. Temperature is storage temperature, not CPU temperature.'))
            except CollectionError as error:output.append(failure(category,capability+'_availability',error,'Windows storage provider / '+capability))
    if category=='system':
        try:
            data=query('system') or {}
            output.append(m('recent_system_errors',category,data.get('Count'),'events / 7 days',source='Get-WinEvent System; IDs 7,11,15,41,51,55,129,153,6008; level 1/2',limitation='Maximum 1000 selected events. Event messages and personal identifiers are omitted. Counts are not a root-cause diagnosis.'))
            for i,event in enumerate(rows(data.get('Events'))[:25]):
                output.append(m('system_event_'+str(i),category,f'ID {event.get("Id")} · {event.get("ProviderName")} · {event.get("Time")}',source='Get-WinEvent System (selected metadata only)',limitation='Event time is embedded; collection timestamp is separate. Correlation is not causation.'))
        except CollectionError as error:output.append(failure(category,'recent_system_errors',error,'Get-WinEvent System'))
    return output

def identity(state_dir=None,query=powershell):
    directory=Path(state_dir or os.environ.get('LOCALAPPDATA',str(Path.home()))) / 'FAULTLINE'
    directory.mkdir(parents=True,exist_ok=True);path=directory/'device-id'
    if not path.exists():path.write_text('device-'+uuid4().hex)
    try:data=query('inventory') or {}
    except CollectionError:data={}
    return Device(id=path.read_text().strip(),manufacturer=data.get('Manufacturer') or 'Unknown manufacturer',model=data.get('Model') or 'Unknown model',os=' '.join(str(data.get(k,'')) for k in ('OS','Version')).strip() or 'Windows (version unavailable)',demo=False)

def collect(device,categories,ident=None,progress=None,category_collector=collect_category):
    if not categories or not set(categories)<=set(CATEGORIES):raise ValueError('Choose supported collection categories')
    started=now();measurements=[];completed=[];status='completed'
    for category in categories:
        try:
            if progress and progress(completed):status='cancelled';break
        except Exception:status='failed';break
        try:measurements.extend(category_collector(category))
        except KeyboardInterrupt:status='cancelled';break
        except Exception:
            # Preserve independent categories; do not leak raw provider exceptions.
            measurements.append(m('category_error',category,status='collection_failed',source='FAULTLINE collector boundary',limitation='Unexpected provider failure; remaining categories continue.'))
        completed.append(category)
        try:
            if progress and progress(completed):status='cancelled';break
        except Exception:status='failed';break
    return Report(schema_version='1.0',id=ident or 'report-'+uuid4().hex,device=device,started_at=started,completed_at=now(),status=status,categories=categories,measurements=measurements)

def loopback_url(value):
    parsed=urlparse(value)
    if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment:
        raise argparse.ArgumentTypeError('Backend must be an HTTP loopback URL, e.g. http://127.0.0.1:8000')
    return value.rstrip('/')

def main():
    parser=argparse.ArgumentParser(description='FAULTLINE read-only Windows / macOS diagnostic collector')
    parser.add_argument('--categories',nargs='+',choices=CATEGORIES,default=CATEGORIES)
    parser.add_argument('--output',type=Path,default=Path('faultline-report.json'))
    parser.add_argument('--backend',type=loopback_url,default='http://127.0.0.1:8000')
    parser.add_argument('--token-file',type=Path,help='Pairing token file; avoids tokens in shell history')
    parser.add_argument('--send',action='store_true');parser.add_argument('--watch',action='store_true')
    args=parser.parse_args()
    if platform.system() not in ('Windows','Darwin'):parser.error('Real collection supports Windows and macOS only.')
    if platform.system()=='Darwin':
        from .macos import identity as device_identity, collect_category as collect_local
    else:
        device_identity=identity;collect_local=collect_category
    if (args.send or args.watch) and not args.token_file:parser.error('--token-file is required for authenticated ingestion')
    device=device_identity();categories=list(dict.fromkeys(args.categories))
    token_value=args.token_file.read_text().strip() if args.token_file else ''
    with httpx.Client(base_url=args.backend,headers={'Authorization':'Bearer '+token_value},timeout=15,follow_redirects=False,trust_env=False) as client:
        def request(path,body):
            response=client.post(path,json=body);response.raise_for_status();return response.json()
        if args.watch:
            print('Paired loopback watcher. Manual scans unless scheduled monitoring is explicitly enabled. Ctrl+C stops.')
            while True:
                try:
                    response=request('/api/agent/poll',device.model_dump(mode='json'));job=response['job']
                    if job:
                        def progress(completed):return request(f'/api/agent/scans/{job["id"]}/progress',{'completed_categories':completed})['cancel_requested']
                        requested=[c for c in job['categories'] if c in response['permissions'] and c in categories]
                        # Report explicit unavailable results for locally denied categories.
                        def permitted(c):
                            return collect_local(c) if c in requested else [m('collection_permission',c,status='permission_denied',source='FAULTLINE collection permissions',limitation='Category disabled in local agent or backend permissions.')]
                        report=collect(device,job['categories'],job['id'],progress,permitted)
                        args.output.write_text(report.model_dump_json(indent=2),encoding='utf-8')
                        request('/api/agent/reports',report.model_dump(mode='json'))
                        print('Report stored:',report.id,report.status)
                except KeyboardInterrupt:return
                except (httpx.HTTPError,OSError):print('Local connection or report delivery failed; retrying. Any completed report remains at the output path.')
                time.sleep(3)
        else:
            report=collect(device,categories,category_collector=collect_local)
            args.output.write_text(report.model_dump_json(indent=2),encoding='utf-8')
            print('Validated read-only report written:',args.output)
            if args.send:
                try:request('/api/agent/reports',report.model_dump(mode='json'))
                except httpx.HTTPError:
                    print('Report saved locally, but delivery failed. Check the loopback API and pairing token, or import the JSON report.',file=sys.stderr)
                    raise SystemExit(1)
                print('Report delivered to paired loopback API.')

if __name__=='__main__':main()
