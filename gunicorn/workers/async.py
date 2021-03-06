# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

from datetime import datetime
import errno
import socket
import sys

import gunicorn.http as http
import gunicorn.http.wsgi as wsgi
import gunicorn.util as util
import gunicorn.workers.base as base

ALREADY_HANDLED = object()

class AsyncWorker(base.Worker):

    def __init__(self, *args, **kwargs):
        super(AsyncWorker, self).__init__(*args, **kwargs)
        self.worker_connections = self.cfg.worker_connections
    
    def timeout_ctx(self):
        raise NotImplementedError()

    def handle(self, client, addr):
        try:
            try:
                parser = http.RequestParser(client)
                try:
                    while True:
                        timeout = self.timeout_ctx()
                        req = None
                        try:
                            try:
                                req = parser.next()
                            except:
                                if sys.exc_info()[1] is not timeout:
                                    raise
                        finally:
                            timeout.cancel()
                        if not req:
                            break
                        self.handle_request(req, client, addr)
                except StopIteration:
                    pass
            except socket.error, e:
                if e[0] not in (errno.EPIPE, errno.ECONNRESET):
                    self.log.exception("Socket error processing request.")
                else:
                    if e[0] == errno.ECONNRESET:
                        self.log.debug("Ignoring connection reset")
                    else:
                        self.log.debug("Ignoring EPIPE")
            except Exception, e:
                self.handle_error(client, e)
        finally:
            util.close(client)

    def handle_request(self, req, sock, addr):
        try:
            self.cfg.pre_request(self, req)
            request_start = datetime.now()
            resp, environ = wsgi.create(req, sock, addr, self.address, self.cfg)
            self.nr += 1
            if self.alive and self.nr >= self.max_requests:
                self.log.info("Autorestarting worker after current request.")
                resp.force_close()
                self.alive = False
            respiter = self.wsgi(environ, resp.start_response)
            if respiter == ALREADY_HANDLED:
                return False
            try:
                for item in respiter:
                    resp.write(item)
                resp.close()
                request_time = datetime.now() - request_start
                self.log.access(resp, environ, request_time)
            finally:
                if hasattr(respiter, "close"):
                  respiter.close()
            if resp.should_close():
                raise StopIteration()
        finally:
            try:
                self.cfg.post_request(self, req, environ)
            except:
                pass
        return True
