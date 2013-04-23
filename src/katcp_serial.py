"""Client for communicating with a the PPCs 2nd Serial Port over KATCP.

   @author Simon Cross <simon.cross@ska.ac.za>
   @modified Jason Manley <jason_manley@hotmail.com>
   @Revised 2010/11/08 to log incomming log informs
   @Revised 2010/06/28 to include qdr stuff
   @Revised 2010/01/07 to include bulkread
   @Revised 2009/12/01 to include print 10gbe core details.
   """

import struct, re, threading, socket, select, traceback, logging, sys, time, os

from katcp import *
log = logging.getLogger("katcp")


#class SerialClient(BlockingClient):
class SerialClient(CallbackClient):
    """Client for communicating with a the PCCs 2nd serial port.

       Notes:
         - All commands are blocking.
         - If there is no response to an issued command, an exception is thrown
           with appropriate message after a timeout waiting for the response.
         - If the TCP connection dies, an exception is thrown with an
           appropriate message.
       """

    def __init__(self, host, port=7148, tb_limit=20, timeout=10.0, logger=log):
        """Create a basic DeviceClient.

           @param self  This object.
           @param host  String: host to connect to.
           @param port  Integer: port to connect to.
           @param tb_limit  Integer: maximum number of stack frames to
                            send in error traceback.
           @param timeout  Float: seconds to wait before timing out on
                           client operations.
           @param logger Object: Logger to log to.
           """
        super(SerialClient, self).__init__(host, port, tb_limit=tb_limit,timeout=timeout, logger=logger)
        self.host = host
        self._timeout = timeout
        self.start(daemon = True)

        # async stuff
        self._nb_request_id = 0
        self._nb_requests = {}
        self._nb_max_requests = 10

    """**********************************************************************************"""
    """**********************************************************************************"""

    def _nb_get_request_by_id(self, request_id):
        try:
            return self._nb_requests[request_id]
        except KeyError:
            return None

    def _nb_pop_request_by_id(self, request_id):
        try:
            return self._nb_requests.pop(request_id)
        except KeyError:
            return None

    def _nb_pop_oldest_request(self):
        req = self._nb_requests[self._nb_requests.keys()[0]]
        for k, v in self._nb_requests.iteritems():
            if v.time_tx < req.time_tx:
                req = v
        return self._nb_pop_request_by_id(req.request_id)

    def _nb_get_request_result(self, request_id):
        req = self._nb_get_request_by_id(request_id)
        return req.reply, req.informs

    def _nb_add_request(self, request_name, request_id, inform_cb, reply_cb):
        if self._nb_requests.has_key(request_id):
            raise RuntimeError('Trying to add request with id(%s) but it already exists.' % request_id)
        self._nb_requests[request_id] = FpgaAsyncRequest(self.host, request_name, request_id, inform_cb, reply_cb)

    def _nb_get_next_request_id(self):
        self._nb_request_id += 1
        return str(self._nb_request_id)

    def _nb_replycb(self, msg, *userdata):
        """The callback for request replies. Check that the ID exists and call that request's got_reply function.
           """
        request_id = ''.join(userdata)
        if not self._nb_requests.has_key(request_id):
            raise RuntimeError('Recieved reply for request_id(%s), but no such stored request.' % request_id)
        self._nb_requests[request_id].got_reply(msg.copy())

    def _nb_informcb(self, msg, *userdata):
        """The callback for request informs. Check that the ID exists and call that request's got_inform function.
           """
        request_id = ''.join(userdata)
        if not self._nb_requests.has_key(request_id):
            raise RuntimeError('Recieved inform for request_id(%s), but no such stored request.' % request_id)
        self._nb_requests[request_id].got_inform(msg.copy())

    def _nb_request(self, request, inform_cb = None, reply_cb = None, *args):
        """Make a non-blocking request.
           @param self      This object.
           @param request   The request string.
           @param inform_cb An optional callback function, called upon receipt of every inform to the request.
           @param inform_cb An optional callback function, called upon receipt of the reply to the request.
           @param args      Arguments to the katcp.Message object.
           """
        if len(self._nb_requests) == self._nb_max_requests:
            oldreq = self._nb_pop_oldest_request()
            self._logger.info("Request list full, removing oldest one(%s,%s)." % (oldreq.request, oldreq.request_id))
            print "Request list full, removing oldest one(%s,%s)." % (oldreq.request, oldreq.request_id)
        request_id = self._nb_get_next_request_id()
        self.request(msg = Message.request(request, *args), reply_cb = self._nb_replycb, inform_cb = self._nb_informcb, user_data = request_id)
        self._nb_add_request(request, request_id, inform_cb, reply_cb)
        return {'host': self.host, 'request': request, 'id': request_id}

    """**********************************************************************************"""
    """**********************************************************************************"""

    def _request(self, name, *args):
        """Make a blocking request and check the result.
        
           Raise an error if the reply indicates a request failure.

           @param self  This object.
           @param name  String: name of the request message to send.
           @param args  List of strings: request arguments.
           @return  Tuple: containing the reply and a list of inform messages.
           """
        request = Message.request(name, *args)
        reply, informs = self.blocking_request(request)
        #reply, informs = self.blocking_request(request,keepalive=True)

        if reply.arguments[0] != Message.OK:
            self._logger.error("Request %s failed.\n  Request: %s\n  Reply: %s."
                    % (request.name, request, reply))

            raise RuntimeError("Request %s failed.\n  Request: %s\n  Reply: %s."
                    % (request.name, request, reply))
        return reply, informs

    def ping(self):
        """Tries to ping the FPGA.
           @param self  This object.
           @return  boolean: ping result.
           """
        reply, informs = self._request("watchdog")
        if reply.arguments[0]=='ok': return True
        else: return False

    def setd(self,pin,state):
        """Sets a boolean value on a digital IO pin."""
        if ((state in [0,1]) or (state in [True,False])):
            reply = self._request("setd",int(pin),int(state))
        else: raise RuntimeError("Invalid state.")

    def seta(self,pin,val):
        """Starts a PWM signal on a digital IO pin. Pins 3, 5, 6, 9, 10 and 11 are supported. Valid range: 0-255."""
        val_pins=[3,5,6,9,10,11]
        assert val in range(255), ("%i is an invalid PWM number. Valid PWM range is 0-255."%int(val))
        assert pin in val_pins, "Invalid pin %i. Valid pins are %s."%(pin,val_pins)
        reply = self._request("seta",int(pin),int(val))

    def geta(self,pin,smoothing=1):
        """Retrieve an ADC value, optionally smoothed over "smoothing" measurements."""
        assert (smoothing in range(1,65)), "Can only smooth between 1 and 64 samples!"
        assert (pin in range(8)), "Invalid analogue pin selected. Choose in range(0,8)!"
        return int(self._request("geta",int(pin),int(smoothing)).arguments[1])
        
    def getd(self,pin):
        """Gets a boolean value on a digital IO pin."""
        return int(self._request("getd",int(pin)).arguments[1])

    def set_atten_db(self,le_pin,data_pin,clk_pin,atten_db=31):
        """Sets the db of a serial minicircuits attenuator with a range of 0-31.5 db of attenuation"""
        atten_db = int(atten_db*2)
        assert atten_db in range(0,63), "Invalid db value %i. Valid range is 0 to 31.5dB."%(atten_db/2.)
        self.setd(le_pin,0)
        self.setd(clk_pin,0)
        for bit in range(5,-1,-1):
            self.setd(data_pin,(atten_db>>bit)&1)
            self.setd(clk_pin,1)
            self.setd(clk_pin,0)
        self.setd(le_pin,1)
        self.setd(le_pin,0)
