import copy
import json
import socket
import struct
from urllib.request import urlopen,Request
from urllib.error import HTTPError
import pytest
from communication.client import WebSocketClient
from communication.protocol import StateOrder,dumps,loads,validate_state
from simulation.engine import Engine


def until(client,kind,limit=30):
    for _ in range(limit):
        message=client.receive()
        if message['type']==kind:return message
    raise AssertionError(f'No {kind} received')


def test_roundtrip_validation_order_and_reset():
    e=Engine(session_id='first');state=e.snapshot()
    assert validate_state(loads(dumps(state)))==state
    order=StateOrder();assert order.accept(state);assert not order.accept(state)
    e.command('start');e.step();old=e.snapshot();assert order.accept(old)
    e.command('reset');assert order.accept(e.snapshot());assert not order.accept(old)
    assert order.accept(Engine(session_id='second').snapshot());assert not order.accept(e.snapshot())


@pytest.mark.parametrize('raw',[b'[]',b'{bad',b'{"a":NaN}',b'{"a":1,"a":2}',b'x'*524289])
def test_invalid_json(raw):
    with pytest.raises(ValueError):loads(raw)


def test_invalid_snapshot_does_not_poison_order():
    state=Engine().snapshot();broken=copy.deepcopy(state);broken['signals']['groups']['E']='GREEN'
    order=StateOrder()
    with pytest.raises(ValueError):order.accept(broken)
    assert order.accept(state)


def test_actual_websocket_commands_and_error_recovery(server):
    base,ws,_=server;client=WebSocketClient(ws)
    try:
        first=until(client,'state');validate_state(first['state'])
        client.send({'type':'command','request_id':'one','action':'parameters','parameters':{'green_ns':7}})
        assert until(client,'ack')['request_id']=='one'
        assert until(client,'state')['state']['parameters']['green_ns']==7
        client.send({'type':'command','request_id':'two','action':'start'});until(client,'ack')
        client.send({'type':'command','request_id':'bad','action':'parameters','parameters':{'green_ns':0}})
        assert 'range' in until(client,'error')['error']
        client._send(1,b'{broken');assert until(client,'error')['type']=='error'
        client.send({'type':'command','request_id':'pause','action':'pause'});until(client,'ack')
        packet=until(client,'state');assert packet['state']['mode']=='paused'
        seq=packet['state']['sequence']
        client.send({'type':'blender_ack','session_id':packet['state']['session_id'],'sequence':seq,'vehicle_count':len(packet['state']['vehicles'])})
        until(client,'state')
        with urlopen(base+'/api/health') as response:assert json.load(response)['blender_connected']
    finally:client.close()


def test_disconnect_and_reconnect(server):
    _,url,process=server
    client=WebSocketClient(url);until(client,'state');client.close()
    client=WebSocketClient(url);assert until(client,'state')['type']=='state'
    process.terminate();process.wait(timeout=8)
    with pytest.raises((ConnectionError,OSError)):
        # Already-buffered snapshots can precede the close frame.
        for _ in range(30):client.receive()
    client.close()


def test_cross_origin_rejected(server):
    base,_,_=server
    with pytest.raises(HTTPError) as caught:
        urlopen(Request(base+'/api/state',headers={'Origin':'https://example.com'}))
    assert caught.value.code==403;caught.value.close()


def test_fragmentation_ping_and_extended_frames():
    a,b=socket.socketpair();a.settimeout(1)
    client=WebSocketClient.__new__(WebSocketClient);client.socket=a;client.buffer=bytearray();client.fragments=bytearray();client.fragmented=False
    try:
        b.sendall(b'\x89\x01?' + b'\x01\x05{"a":' + b'\x80\x02' + b'1}')
        assert client.receive()=={'a':1}
        pong=b.recv(100);assert pong[0]==0x8a and pong[1]&128
        payload=dumps({'message':'x'*200}).encode();b.sendall(b'\x81\x7e'+struct.pack('!H',len(payload))+payload)
        assert client.receive()['message']=='x'*200
        payload=dumps({'message':'x'*70000}).encode()
        b.sendall(b'\x81\x7f'+struct.pack('!Q',len(payload))+payload)
        assert len(client.receive()['message'])==70000
        b.sendall(b'\x81\x7f'+struct.pack('!Q',524289))
        with pytest.raises(ValueError):client.receive()
    finally:client.close();b.close()
