import json
import subprocess
from unittest.mock import Mock

import pytest
from apps.agent import collector as c
from packages.schemas.report import Device, Report

def test_battery_real_xml_shape_and_missing_cycles():
    xml='''<BatteryReport xmlns="http://schemas.microsoft.com/battery/2012"><Batteries><Battery><DesignCapacity>50000</DesignCapacity><FullChargeCapacity>37500</FullChargeCapacity><CycleCount>-</CycleCount></Battery></Batteries></BatteryReport>'''
    data=c.parse_battery_xml(xml)
    assert data[1].value==75
    assert data[2].status=='unknown' and data[2].value is None
    with pytest.raises(c.CollectionError):c.parse_battery_xml('<BatteryReport/>')

def test_mocked_storage_supported_zero_and_denied():
    def query(key):return {'volumes':[{'DeviceID':'C:','Size':100,'FreeSpace':0}],'storage':[{'DeviceId':'0','FriendlyName':'Test SSD','HealthStatus':'Healthy','Size':1024**3}],'reliability':[{'DeviceId':'0','Status':'permission_denied'}]}[key]
    data=c.collect_category('storage',query=query)
    assert data[0].value==0 and data[0].status=='available'
    assert data[-1].status=='permission_denied' and data[-1].value is None

def test_mocked_cpu_temperature_unavailable():
    data=c.collect_category('cooling',query=lambda _: {'Name':'CPU','LoadPercentage':0})
    assert data[1].value==0
    assert data[-1].key=='cpu_temperature' and data[-1].status=='unsupported'

def test_category_failure_does_not_stop_report_and_cancellation():
    device=Device(id='test',manufacturer='Test',model='Model',os='Windows')
    def category(key):
        if key=='battery':raise RuntimeError('private identifier should not leak')
        return [c.m('usage',key,0,'%',source='mock supported API')]
    report=c.collect(device,['battery','ram'],category_collector=category)
    assert report.status=='completed' and len(report.measurements)==2
    assert 'private identifier' not in report.model_dump_json()
    cancelled=c.collect(device,['battery','ram'],progress=lambda done:len(done)==1,category_collector=category)
    assert cancelled.status=='cancelled' and len(cancelled.measurements)==1
    Report.model_validate_json(cancelled.model_dump_json())

def test_subprocess_timeout_and_no_shell(monkeypatch):
    run=Mock(side_effect=subprocess.TimeoutExpired('powershell',30));monkeypatch.setattr(c.subprocess,'run',run)
    with pytest.raises(c.CollectionError,match='timeout'):c.powershell('ram')
    assert run.call_args.kwargs['shell'] is False
    assert '-EncodedCommand' in run.call_args.args[0]
    with pytest.raises(ValueError):c.powershell('arbitrary user command')

def test_loopback_and_system_event_privacy():
    assert c.loopback_url('http://127.0.0.1:8000')=='http://127.0.0.1:8000'
    for url in ['https://evil.example','http://127.0.0.1.evil.example','http://user:password@127.0.0.1','http://127.0.0.1/execute']:
        with pytest.raises(Exception):c.loopback_url(url)
    assert 'Message' not in c.SCRIPTS['system'].split('Select-Object')[-1]

def test_progress_connection_loss_preserves_partial_and_utf16_battery():
    device=Device(id='test',manufacturer='Test',model='Model',os='Windows')
    def progress(done):
        if done:raise OSError('connection lost')
        return False
    report=c.collect(device,['ram','system'],progress=progress,category_collector=lambda key:[c.m('usage',key,1,'%',source='mock API')])
    assert report.status=='failed' and len(report.measurements)==1
    xml='<?xml version="1.0" encoding="utf-16"?><BatteryReport><Batteries><Battery><DesignCapacity>100</DesignCapacity><FullChargeCapacity>80</FullChargeCapacity></Battery></Batteries></BatteryReport>'
    assert c.parse_battery_xml(xml.encode('utf-16'))[1].value==80
