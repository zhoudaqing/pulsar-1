'''Classes for the pulsar Key-Value store server
'''
from functools import partial

import pulsar
from pulsar.apps.socket import SocketServer
from .parser import RedisParser


class BadCommandInput(Exception):

    def __init__(self, command, message, *args):
        msg = 'ERR: %s %s' % (command.upper(), message % args)
        super(BadCommandInput, self).__init__(msg)


class PulsarStoreConnection(pulsar.Connection):
    '''Used both by client and server'''
    def __init__(self, parser_class, consumer_factory, **kw):
        super(PulsarStoreConnection, self).__init__(consumer_factory, **kw)
        self.parser = parser_class()


class PulsarStoreProtocol(pulsar.ProtocolConsumer):

    def data_received(self, data):
        conn = self._connection
        transport = conn._transport
        parser = conn.parser
        store = conn._producer._key_value_store
        parser.feed(data)
        request = parser.get()
        while request is not False:
            command = request[0].decode('utf-8').lower()
            handle = getattr(store, command)
            handle(transport, request)
            request = parser.get()


class TcpServer(pulsar.TcpServer):

    def __init__(self, *args, **kwargs):
        super(TcpServer, self).__init__(*args, **kwargs)
        self._key_value_store = Storage(self, self._loop)

    def info(self):
        info = super(TcpServer, self).info()
        info['store'] = self._key_value_store._info()
        return info


class KeyValueStore(SocketServer):
    server_class = TcpServer

    def protocol_factory(self):
        consumer_factory = partial(PulsarStoreProtocol, self.cfg)
        return partial(PulsarStoreConnection, RedisParser, consumer_factory)

    def monitor_start(self, monitor):
        cfg = self.cfg
        workers = min(1, cfg.workers)
        cfg.set('workers', workers)
        return super(KeyValueStore, self).monitor_start(monitor)


class Storage(object):

    def __init__(self, server):
        self._server = server
        self._loop = server._loop
        self._data = {}
        self._timeouts = {}

    def ping(self, transport, request):
        if len(request) != 1:
            raise BadCommandInput('ping', 'expect no arguments')
        transport.write(b'+PONG\r\n')

    def set(self, transport, request):
        N = len(request) - 1
        if N < 2 or N > 3:
            raise BadCommandInput('set',
                                  'expect 2 or 3 arguments, %s given', N)
        key, value = request[1], request[2]
        if N == 3:
            timeout = float(request[3])
            self._expire(key, timeout)
            self._data[key] = value
        else:
            if key in self._timeouts:
                self._timeouts.pop(key).cancel()
            self._data[key] = value
        transport.write(b'+OK\r\n')

    def get(self, transport, request):
        N = len(request) - 1
        if N < 2:
            raise BadCommandInput('set',
                                  'expect 1 or more arguments, %s given', N)
        get = self._data.get
        values = [get(k, b'nil') for k in requests[1:]]
        transport.write(pack_command(values))

    def info(self, transport, request):
        if len(request) != 1:
            raise BadCommandInput('ping', 'expect no arguments')
        info = self._server.info()
        transport.write(pack_command(info))

    ##    INTERNALS
    def _info(self):
        info = {'keys': len(self._data),
                'timeouts': len(self._timeouts)}
        return info
