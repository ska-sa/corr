"""Client for communicating with an Arduino-based SKA-SA optically-isolated GPIO breakout board over KATCP.

   @author Jason Manley <jason_manley@hotmail.com>
   @Revised 2012/09/13 first release
   """

import serial, logging, sys, time, os

from katcp import *
log = logging.getLogger("katcp_gpio")


class GpioClient():
    """Client for communicating with a GPIO board. Nasty hard-coded KATCP stuff.

       Notes:
         - All commands are blocking.
         - If there is no response to an issued command, an exception is thrown
           with appropriate message after a timeout waiting for the response.
       """
#TODO: migrate to serial-port enabled KATCP library

    def __init__(self, serial_dev, timeout=1.0, logger=log,startup_delay=0):
        """Create a basic DeviceClient.

           @param self  This object.
           @param serial_dev  String: /dev/ttyS0 or similar
           @param timeout  Float: seconds to wait before timing out on
                           client operations.
           @param logger Object: Logger to log to.
           """

        self.strm=serial.Serial(port=serial_dev,baudrate=9600,timeout=timeout)
        self._timeout = timeout
        self._logger = log
        self.mp=MessageParser()
        time.sleep(startup_delay)  #give the device a chance to startup (for USB powered units)
        self.strm.read(1024)

    def _request(self, name, *args):
        """Make a blocking request and check the result.
        
           Raise an error if the reply indicates a request failure.

           @param self  This object.
           @param name  String: name of the request message to send.
           @param args  List of strings: request arguments.
           @return  Tuple: containing the reply and a list of inform messages.
           """
        request = Message.request(name, *args)
    #    reply, informs = self.blocking_request(request,keepalive=True)
        self._write(request)
        reply=self._read()

        if reply.arguments[0] != Message.OK:
            self._logger.error("Request %s failed.\n  Request: %s\n  Reply: %s."
                    % (request.name, request, reply))

            raise RuntimeError("Request %s failed.\n  Request: %s\n  Reply: %s."
                    % (request.name, request, reply))
        return reply

        #reply, informs = self._request("tap-start", tap_dev, device, ip_str, port_str, mac_str)
        #if reply.arguments[0]=='ok': return
        #else: raise RuntimeError("Failure starting tap device %s with mac %s, %s:%s"%(device,mac_str,ip_str,port_str))

    def _write(self,message):
        """Sends a message."""
        self.strm.write(str(message))
        #print 'Sent: %s\r'%str(message)
        self.strm.write('\r')

    def _read(self):
        """Gets a single line from the serial port, handles the reply and returns a message object.""" 
        ln=self.strm.readline().strip()
        #print 'Got: %s'%ln
        if len(ln)>0:
            return self.mp.parse(ln)
        else:
            self._logger.error("Reply timed out.")
            raise RuntimeError("Reply timed out.")
            
    def ping(self):
        """Tries to ping the FPGA.
           @param self  This object.
           @return  boolean: ping result.
           """
        reply = self._request("watchdog")
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

    def set_5b_atten_serial(self,data_pin,clk_pin,le_pin,atten):
        self.setd(le_pin,0)
        for bit in range(5):
            self.setd(clk_pin,0)
            self.setd(data_pin,atten>>bit)
            self.setd(clk_pin,1)
            self.setd(clk_pin,0)
        self.setd(le_pin,1)

