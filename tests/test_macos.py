import json
import plistlib
import subprocess
from collections import namedtuple
from unittest.mock import Mock

import pytest
from apps.agent import macos
from apps.agent.collector import CollectionError, collect
from packages.schemas.report import Device, Report

def query(values):
    def read(key):
        value=values[key]
        if isinstance(value,Exception):raise value
        return value
    return read

def test_raw_battery_capacity_and_no_normalized_mixing():
    data={'CycleCount':0,'DesignCapacity':5000,'AppleRawMaxCapacity':4000,'MaxCapacity':100,'IsCharging':False,'Serial':'must-not-leak'}
    values=macos.collect_category('battery',query({'battery':plistlib.dumps([data])}))
    assert next(m for m in values if m.key=='full_charge_capacity').value==80
    assert values[0].value==0 and values[0].status=='available'
    assert 'must-not-leak' not in str(values)
    del data['AppleRawMaxCapacity']
    values=macos.collect_category('battery',query({'battery':plistlib.dumps([data])}))
    assert next(m for m in values if m.key=='full_charge_capacity').status=='unknown'

def test_desktop_no_battery_and_denied_are_not_healthy():
    values=macos.collect_category('battery',query({'battery':plistlib.dumps([])}))
    assert values[0].status=='unsupported' and values[0].value is None
    phantom={'BatteryInstalled':False,'CycleCount':0,'MaxCapacity':0,'IsCharging':False}
    values=macos.collect_category('battery',query({'battery':plistlib.dumps([phantom])}))
    assert len(values)==1 and values[0].key=='battery_presence' and values[0].status=='unsupported'
    values=macos.collect_category('battery',query({'battery':CollectionError('permission_denied','Denied')}))
    assert values[0].status=='permission_denied'

def test_cpu_second_sample_and_unsupported_temperature():
    values=macos.collect_category('cooling',query({'cpu_model':b'Apple test CPU','cpu_count':b'8','cpu':b'CPU usage: 1% user, 1% sys, 98.0% idle\nCPU usage: 12% user, 8% sys, 80.0% idle\n'}))
    assert next(m for m in values if m.key=='cpu_usage').value==20
    assert values[-1].status=='unsupported' and values[-1].value is None

def test_ram_page_accounting_not_fabricated_percent():
    values=macos.collect_category('ram',query({'ram':str(16*1024**3).encode(),'vm':b'Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPages active: 100.\nPages wired down: 50.\nPages occupied by compressor: 10.\n'}))
    assert values[0].value==16 and values[0].unit=='GiB'
    assert values[1].value==round(160*16384/1024**3,2)
    missing=macos.collect_category('ram',query({'ram':b'17179869184','vm':b'unsupported output'}))
    assert missing[1].status=='unknown'

def test_storage_zero_unknown_and_failures_are_independent():
    Usage=namedtuple('Usage','total used free')
    values=macos.collect_category('storage',query({'storage':plistlib.dumps({'SMARTStatus':'Not Supported'})}),disk_usage=lambda _:Usage(100,100,0))
    assert values[0].value==0 and values[0].status=='available'
    assert next(m for m in values if m.key=='storage_health').status=='unsupported'
    values=macos.collect_category('storage',query({'storage':plistlib.dumps({'SMARTStatus':'Verified'})}),disk_usage=lambda _:Usage(100,60,40))
    assert next(m for m in values if m.key=='storage_health').value=='Healthy'

def test_identity_privacy_and_stability(tmp_path):
    read=query({'hardware':json.dumps({'SPHardwareDataType':[{'machine_name':'Mac mini','machine_model':'MacTest,1','serial_number':'PRIVATE','platform_UUID':'PRIVATE'}]}).encode(),'os':b'15.0'})
    first=macos.identity(tmp_path,read);second=macos.identity(tmp_path,read)
    assert first.id==second.id and first.demo is False
    assert first.model=='Mac mini MacTest,1' and first.os=='macOS 15.0'
    assert 'PRIVATE' not in first.model_dump_json()

def test_fixed_commands_timeout_and_no_shell(monkeypatch):
    run=Mock(side_effect=subprocess.TimeoutExpired('sysctl',30));monkeypatch.setattr(macos.subprocess,'run',run)
    with pytest.raises(CollectionError):macos.command('ram')
    assert run.call_args.kwargs['shell'] is False
    assert run.call_args.args[0]==['/usr/sbin/sysctl','-n','hw.memsize']
    with pytest.raises(ValueError):macos.command('sudo injected text')

def test_macos_report_uses_shared_validated_contract():
    device=Device(id='mac-test',manufacturer='Apple',model='Mac test',os='macOS test',demo=False)
    values=query({'os':b'15.0','build':b'24A000'})
    report=collect(device,['system'],category_collector=lambda c:macos.collect_category(c,values))
    assert Report.model_validate_json(report.model_dump_json()).status=='completed'
    assert report.measurements[-1].status=='unsupported'
