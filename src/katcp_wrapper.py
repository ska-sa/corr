"""Client for communicating with a ROACH board over KATCP.

   @author Simon Cross <simon.cross@ska.ac.za>
   @modified Jason Manley <jason_manley@hotmail.com>
   @Revised 2010/11/08 to log incomming log informs
   @Revised 2010/06/28 to include qdr stuff
   @Revised 2010/01/07 to include bulkread
   @Revised 2009/12/01 to include print 10gbe core details.
   """

import struct, threading, socket, logging, time, os

from katcp import *
log = logging.getLogger("katcp")

class FpgaAsyncRequest:
    """A class to hold information about a specific KATCP request made by a Fpga.
       """
    def __init__(self, host, request, request_id, inform_cb = None, reply_cb = None):
        self.host = host
        self.request = request
        self.request_id = request_id
        self.time_tx = time.time()
        self.informs = []
        self.inform_times = []
        self.reply = None
        self.reply_time = -1
        self.reply_cb = reply_cb
        self.inform_cb = inform_cb
    def __str__(self):
        return '%s(%s)@(%10.5f) - reply%s - informs(%i)' % (self.request, self.request_id, self.time_tx, str(self.reply), len(self.informs))
    def got_reply(self, reply_message):
        if not (reply_message.name == self.request):
            error_string = 'rx reply(%s) does not match request(%s)' % (reply_message.name, self.request)
            print error_string
            raise RuntimeError(error_string)
        self.reply = reply_message
        self.reply_time = time.time()
        if self.reply_cb != None:
            self.reply_cb(self.host, self.request_id)
    def got_inform(self, inform_message):
        if self.reply != None:
            raise RuntimeError('Received inform for message(%s,%s) after reply. Invalid?' % (self.request, self.request_id))
        if not (inform_message.name == self.request):
            error_string = 'rx inform(%s) does not match request(%s)' % (inform_message.name, self.request)
            print error_string
            raise RuntimeError(error_string)
        self.informs.append(inform_message)
        self.inform_times.append(time.time())
        if self.inform_cb != None:
            self.inform_cb(self.host, self.request_id)
    def complete_ok(self):
        '''Has this request completed successfully?
        '''
        if self.reply == None:
            return False
        return self.reply.arguments[0] == Message.OK

#class FpgaClient(BlockingClient):
class FpgaClient(CallbackClient):
    """Client for communicating with a ROACH board.

       Notes:
         - All commands are blocking.
         - If there is no response to an issued command, an exception is thrown
           with appropriate message after a timeout waiting for the response.
         - If the TCP connection dies, an exception is thrown with an
           appropriate message.
       """

    def __init__(self, host, port=7147, tb_limit=20, timeout=10.0, logger=log):
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
        super(FpgaClient, self).__init__(host, port, tb_limit = tb_limit, timeout = timeout, logger = logger)
        self.host = host
        self._timeout = timeout
        self.start(daemon = True)

        # async stuff
        self._nb_request_id_lock = threading.Lock()
        self._nb_request_id = 0
        self._nb_requests_lock = threading.Lock()
        self._nb_requests = {}
        self._nb_max_requests = 100

    """**********************************************************************************"""
    """**********************************************************************************"""

    def _nb_get_request_by_id(self, request_id):
        try:
            return self._nb_requests[request_id]
        except KeyError:
            return None

    def _nb_pop_request_by_id(self, request_id):
        try:
            self._nb_requests_lock.acquire()
            r = self._nb_requests.pop(request_id)
            self._nb_requests_lock.release()
            return r
        except KeyError:
            return None

    def _nb_pop_oldest_request(self):
        req = self._nb_requests[self._nb_requests.keys()[0]]
        for k, v in self._nb_requests.iteritems():
            if v.time_tx < req.time_tx:
                req = v
        self._nb_requests_lock.acquire()
        r = self._nb_pop_request_by_id(req.request_id)
        self._nb_requests_lock.release()
        return r

    def _nb_get_request_result(self, request_id):
        req = self._nb_get_request_by_id(request_id)
        return req.reply, req.informs

    def _nb_add_request(self, request_name, request_id, inform_cb, reply_cb):
        if self._nb_requests.has_key(request_id):
            raise RuntimeError('Trying to add request with id(%s) but it already exists.' % request_id)
        self._nb_requests_lock.acquire()
        self._nb_requests[request_id] = FpgaAsyncRequest(self.host, request_name, request_id, inform_cb, reply_cb)
        self._nb_requests_lock.release()

    def _nb_get_next_request_id(self):
        self._nb_request_id_lock.acquire()
        self._nb_request_id += 1
        reqid = self._nb_request_id
        self._nb_request_id_lock.release()
        return str(reqid)

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
        self._nb_add_request(request, request_id, inform_cb, reply_cb)
        self.callback_request(msg = Message.request(request, *args), reply_cb = self._nb_replycb, inform_cb = self._nb_informcb, user_data = request_id)
        return {'host': self.host, 'request': request, 'id': request_id}

    """**********************************************************************************"""
    """**********************************************************************************"""

    def _request(self, name, request_timeout, *args):
        """Make a blocking request and check the result.

           Raise an error if the reply indicates a request failure.

           @param self  This object.
           @param name  String: name of the request message to send.
           @param args  List of strings: request arguments.
           @return  Tuple: containing the reply and a list of inform messages.
           """
        request = Message.request(name, *args)
        reply, informs = self.blocking_request(request, timeout = request_timeout)
        #reply, informs = self.blocking_request(request,keepalive=True)

        if reply.arguments[0] != Message.OK:
            self._logger.error("Request %s failed.\n  Request: %s\n  Reply: %s."
                    % (request.name, request, reply))

            raise RuntimeError("Request %s failed.\n  Request: %s\n  Reply: %s."
                    % (request.name, request, reply))
        return reply, informs

    def listdev(self):
        """Return a list of register / device names.

           @param self  This object.
           @return  A list of register names.
           """
        reply, informs = self._request("listdev", self._timeout)
        return [i.arguments[0] for i in informs]

    def listbof(self):
        """Return a list of executable files.

           @param self  This object.
           @return  List of strings: list of executable files.
           """
        reply, informs = self._request("listbof", self._timeout)
        return [i.arguments[0] for i in informs]

    def listcmd(self):
        """Return a list of available commands. this should not be made
           available to the user, but can be used internally to query if a
           command is supported.

           @todo  Implement or remove.
           @param self  This object.
           """
        raise NotImplementedError("LISTCMD not implemented by client.")

    def progdev(self, boffile):
        """Program the FPGA with the specified boffile.

           @param self  This object.
           @param boffile  String: name of the BOF file.
           @return  String: device status.
           """
        if boffile=='' or boffile==None:
            reply, informs = self._request("progdev", self._timeout)
            self._logger.info("Deprogramming FPGA... %s."%(reply.arguments[0]))
        else:
            reply, informs = self._request("progdev", self._timeout, boffile)
            self._logger.info("Programming FPGA with %s... %s."%(boffile,reply.arguments[0]))
        return reply.arguments[0]

    def config_10gbe_core(self,device_name,mac,ip,port,arp_table,gateway=1,subnet_mask=0xffffff00):
        """Hard-codes a 10GbE core with the provided params. It does a blindwrite, so there is no verifcation that configuration was successful (this is necessary since some of these registers are set by the fabric depending on traffic received).

           @param self  This object.
           @param device_name  String: name of the device.
           @param mac   integer: MAC address, 48 bits.
           @param ip    integer: IP address, 32 bits.
           @param port  integer: port of fabric interface (16 bits).
           @param subnet_mask  integer: Subnet mask (32 bits).
           @param arp_table  list of integers: MAC addresses (48 bits ea).
           """
        #assemble struct for header stuff...
        #0x00 - 0x07: My MAC address
        #0x08 - 0x0b: Not used
        #0x0c - 0x0f: Gateway addr
        #0x10 - 0x13: my IP addr
        #0x14 - 0x17: Not assigned
        #0x18 - 0x1b: Buffer sizes
        #0x1c - 0x1f: Not assigned
        #0x20       : soft reset (bit 0)
        #0x21       : fabric enable (bit 0)
        #0x22 - 0x23: fabric port

        #0x24 - 0x27: XAUI status (bit 2,3,4,5=lane sync, bit6=chan_bond)
        #0x28 - 0x2b: PHY config

        #0x28       : RX_eq_mix
        #0x29       : RX_eq_pol
        #0x2a       : TX_preemph
        #0x2b       : TX_diff_ctrl

        #0x38 - 0x3b: subnet mask

        #0x1000     : CPU TX buffer
        #0x2000     : CPU RX buffer
        #0x3000     : ARP tables start

        ctrl_pack=struct.pack('>QLLLLLLBBH',mac, 0, gateway, ip, 0, 0, 0, 0, 1, port)
        subnet_mask_pack=struct.pack('>L',subnet_mask)
        arp_pack=struct.pack('>256Q',*arp_table)
        self.blindwrite(device_name,ctrl_pack,offset=0)
        self.blindwrite(device_name,subnet_mask_pack,offset=0x38)
        self.write(device_name,arp_pack,offset=0x3000)

    def tap_start(self, tap_dev, device, mac, ip, port):
        """Program a 10GbE device and start the TAP driver.

            @param self  This object.
            @param device  String: name of the device (as in simulink name).
            @param tap_dev  String: name of the tap device (a Linux identifier). If you want to destroy a device later, you need to use this name.
            @param mac   integer: MAC address, 48 bits.
            @param ip    integer: IP address, 32 bits.
            @param port  integer: port of fabric interface (16 bits).

            Please note that the function definition changed from corr-0.4.0 to corr-0.4.1 to include the tap_dev identifier.
           """
        if len(tap_dev) > 8:
            raise RuntimeError("Tap device identifier must be shorter than 9 characters. You specified %s for device %s." % (tap_dev, device))

        ip_1 = (ip/(2**24))
        ip_2 = (ip%(2**24))/(2**16)
        ip_3 = (ip%(2**16))/(2**8)
        ip_4 = (ip%(2**8))
        mac0 = (mac & ((1<<48)-(1<<40))) >> 40
        mac1 = (mac & ((1<<40)-(1<<32))) >> 32
        mac2 = (mac & ((1<<32)-(1<<24))) >> 24
        mac3 = (mac & ((1<<24)-(1<<16))) >> 16
        mac4 = (mac & ((1<<16)-(1<<8))) >> 8
        mac5 = (mac & ((1<<8)-(1<<0))) >> 0

        mac_str = "%02X:%02X:%02X:%02X:%02X:%02X"%(mac0,mac1,mac2,mac3,mac4,mac5)
        ip_str = "%i.%i.%i.%i"%(ip_1,ip_2,ip_3,ip_4)
        port_str = "%i"%port

        self._logger.info("Starting tgtap driver instance for %s: %s %s %s %s %s"%("tap-start", tap_dev, device, ip_str, port_str, mac_str))
        reply, informs = self._request("tap-start", self._timeout, tap_dev, device, ip_str, port_str, mac_str)
        if reply.arguments[0]=='ok': return
        else: raise RuntimeError("Failure starting tap device %s with mac %s, %s:%s"%(device,mac_str,ip_str,port_str))

    def tap_stop(self, device):
        """Stop a TAP driver.
           @param self  This object.
           @param device  String: name of the device you want to stop.
        """
        reply, informs = self._request("tap-stop", self._timeout, device)
        if reply.arguments[0]=='ok': return
        else: raise RuntimeError("Failure stopping tap device %s."%(device))

    def tap_multicast_add_send(self, tap_dev, ip, n_addresses=1):
        """Adds a range of address to which the ROACH must send to (this is only needed if you plan to send multicast packets from the PPC; the FPGA fabric doesn't need anything here). Note that subsequent calls to this function will overwrite previous calls (you can only subscribe to one set of addresses).
            @param self    This object.
            @param tap_dev String: name of the tap device (a Linux identifier). If you want to destroy a device later, you need to use this name.
            @param ip      integer: IP address, 32 bits. This should be 2^N bounded (ie if you're subscribing to 4 addresses, this address should have zeros in its lowest two bits).
            @param n_addresses integer: Adjacent number of addresses to subscribe to. Note that this needs to be a power of 2 due to HW restrictions.
           """
        if len(tap_dev) > 8:
            raise RuntimeError("Tap device identifier must be shorter than 9 characters. You specified %s." % (tap_dev))
        if n_addresses<1:
            raise RuntimeError("You need to subscribe to at least 1 address!")
        if n_addresses&(n_addresses-1) != 0:
            raise RuntimeError("The number of addresses needs to be a power of 2. You specified %s for device %s." % (n_addresses, tap_dev))

        first_ip=ip&(0xffffffff-n_addresses+1)
        last_ip=first_ip+ n_addresses

        ip_str_first=ip_to_a(first_ip)
        ip_str_last=ip_to_a(last_ip)

        self._logger.info("Joining the multicast groups %s - %s." %(ip_str_first, ip_str_last))
        if n_addresses==1:
            reply, informs = self._request("tap-multicast-add", self._timeout, tap_dev, 'send', str(ip_str_first))
        else:
            reply, informs = self._request("tap-multicast-add", self._timeout, tap_dev, 'send', str(ip_str_first) + '+' + str(n_addresses-1))
        if reply.arguments[0]=='ok': return
        else: raise RuntimeError("Failure adding multicast addresses %s-%s to tap device %s." %(ip_str_first,ip_str_last, tap_dev))

    def tap_multicast_add_recv(self, tap_dev, ip, n_addresses=1):
        """Adds a range of address to which the ROACH must receive from. Note that subsequent calls to this function will overwrite previous calls (you can only subscribe to one set of addresses).
            @param self    This object.
            @param tap_dev String: name of the tap device (a Linux identifier). If you want to destroy a device later, you need to use this name.
            @param ip      integer: IP address, 32 bits. This should be 2^N bounded (ie if you're subscribing to 4 addresses, this address should have zeros in its lowest two bits).
            @param n_addresses integer: Adjacent number of addresses to subscribe to. Note that this needs to be a power of 2 due to HW restrictions. Default of 1 means only this address.
           """
        if len(tap_dev) > 8:
            raise RuntimeError("Tap device identifier must be shorter than 9 characters. You specified %s." % (tap_dev))
        if n_addresses<1:
            raise RuntimeError("You need to subscribe to at least 1 address!")
        if n_addresses&(n_addresses-1) != 0:
            raise RuntimeError("The number of addresses needs to be a power of 2. You specified %s for device %s." % (n_addresses, tap_dev))

        first_ip=ip&(0xffffffff-n_addresses+1)
        last_ip=first_ip+ n_addresses-1

        ip_str_first=ip_to_a(first_ip)
        ip_str_last=ip_to_a(last_ip)

        self._logger.info("Subscribing to the multicast groups %s - %s." %(ip_str_first, ip_str_last))
        #work around initial interface bug with '+x' off-by-one error:
        if n_addresses==1:
            reply, informs = self._request("tap-multicast-add", self._timeout, tap_dev, 'recv', str(ip_str_first))
        else:
            reply, informs = self._request("tap-multicast-add", self._timeout, tap_dev, 'recv', str(ip_str_first) + '+' + str(n_addresses-1))
        if reply.arguments[0]=='ok': return
        else: raise RuntimeError("Failure subscribing to multicast addresses %s-%s to tap device %s." %(ip_str_first,ip_str_last, tap_dev))

    def tap_multicast_remove(self, tap_dev):
        """Stop subscribing to all multicast addresses on specified TAP device.

           @param self  This object.
           @param tap_dev  String: name of the device you want to stop.
        """

        reply, informs = self._request("tap-multicast_remove", self._timeout, tap_dev)
        if reply.arguments[0]=='ok': return
        else: raise RuntimeError("Failure stopping tap device %s." % (tap_dev))

    def upload_program_bof(self, bof_file, port, timeout = 30):
        """Upload a BORPH file to the ROACH board for execution.
           @param self  This object.
           @param bof_file  The path and/or filename of the bof file to upload.
           @param port  The port to use for uploading.
           @param timeout  The timeout to use for uploading.
           @return
        """
        # does the bof file exist on the local filesystem?
        try:
            os.path.getsize(bof_file)
        except:
            raise IOError('BOF file not found.')
        import time, Queue
        def makerequest(result_queue):
            try:
                result = self._request('upload', timeout, port)
                if(result[0].arguments[0] == Message.OK):
                    result_queue.put('OK')
                else:
                    result_queue.put('Request to client returned, but not Message.OK.')
            except:
                result_queue.put('Request to client failed.')
        def uploadbof(filename, result_queue):
            upload_socket = socket.socket()
            stime = time.time()
            connected = False
            while (not connected) and (time.time() < (stime + 2)):
                try:
                    upload_socket = socket.socket()
                    upload_socket.connect((self.host, port))
                    connected = True
                except:
                    time.sleep(0.1)
            if not connected:
                result_queue.put('Could not connect to upload port.')
            try:
                upload_socket.send(open(filename).read())
            except:
                result_queue.put('Could not send file to upload port.')
            result_queue.put('OK')
        # request thread
        request_queue = Queue.Queue()
        request_thread = threading.Thread(target = makerequest, args = (request_queue,))
        # upload thread
        upload_queue = Queue.Queue()
        upload_thread = threading.Thread(target = uploadbof, args = (bof_file, upload_queue,))
        # start the threads and join
        old_timeout = self._timeout
        self._timeout = timeout
        request_thread.start()
        upload_thread.start()
        request_thread.join()
        self._timeout = old_timeout
        request_result = request_queue.get()
        upload_result = upload_queue.get()
        if (request_result != 'OK') or (upload_result != 'OK'):
            raise Exception('Error: request(%s), upload(%s)' %(request_result, upload_result))
        debugstr = "Bof file upload for '%s': request (%s), upload (%s)" % (bof_file, request_result, upload_result)
        self._logger.info(debugstr)
        stime = time.time()
        done = False
        while (not done) and (time.time() < stime + 15):
            try:
                self.listdev()
                done = True
                #print "Got a successful listdev from %s!"%self.host
            except:
                time.sleep(0.1)
        if not done:
            raise RuntimeError('BOF file seemed to upload, but is not running?')

    def status(self):
        """Return the status of the FPGA.
           @param self  This object.
           @return  String: FPGA status.
           """
        reply, informs = self._request("status", self._timeout)
        return reply.arguments[1]

    def ping(self):
        """Tries to ping the FPGA.
           @param self  This object.
           @return  boolean: ping result.
           """
        reply, informs = self._request("watchdog", self._timeout)
        if reply.arguments[0]=='ok': return True
        else: return False

    def execcmd(self, string):
        """Not yet supported.

           @todo  Implement or remove.
           @param self  This object.
           """
        raise NotImplementedError(
            "EXEC not implemented by client.")

    def bulkread(self, device_name, size, offset=0):
        """Return size_bytes of binary data with carriage-return escape-sequenced.
           Uses much fast bulkread katcp command which returns data in pages
           using informs rather than one read reply, which has significant buffering
           overhead on the ROACH.

           @param self  This object.
           @param device_name  String: name of device / register to read from.
           @param size  Integer: amount of data to read (in bytes).
           @param offset  Integer: offset to read data from (in bytes).
           @return  Bindary string: data read.
           """
        reply, informs = self._request("bulkread", self._timeout, device_name, str(offset), str(size))
        return ''.join([i.arguments[0] for i in informs])

    def read(self, device_name, size, offset=0):
        """Return size_bytes of binary data with carriage-return
           escape-sequenced.

           @param self  This object.
           @param device_name  String: name of device / register to read from.
           @param size  Integer: amount of data to read (in bytes).
           @param offset  Integer: offset to read data from (in bytes).
           @return  Bindary string: data read.
           """
        reply, informs = self._request("read", self._timeout, device_name, str(offset),
            str(size))
        return reply.arguments[1]

    def read_dram(self, size, offset=0,verbose=False):
        """Reads data from a ROACH's DRAM. Reads are done up to 1MB at a time.
           The 64MB indirect address register is automatically incremented as necessary.
           It returns a string, as per the normal 'read' function.
           ROACH has a fixed device name for the DRAM (dram memory).
           Uses bulkread internally.

           @param self    This object.
           @param size    Integer: amount of data to read (in bytes).
           @param offset  Integer: offset to read data from (in bytes).
           @return  Binary string: data read.
        """
        #Modified 2010-01-07 to use bulkread.
        data=[]
        n_reads=0
        last_dram_page = -1

        dram_indirect_page_size=(64*1024*1024)
        #read_chunk_size=(1024*1024)
        if verbose: print 'Reading a total of %8i bytes from offset %8i...'%(size,offset)

        while n_reads < size:
            dram_page=(offset+n_reads)/dram_indirect_page_size
            local_offset = (offset+n_reads)%(dram_indirect_page_size)
            #local_reads = min(read_chunk_size,size-n_reads,dram_indirect_page_size-(offset%dram_indirect_page_size))
            local_reads = min(size-n_reads,dram_indirect_page_size-(offset%dram_indirect_page_size))
            if verbose: print 'Reading %8i bytes from indirect address %4i at local offset %8i...'%(local_reads,dram_page,local_offset)
            if last_dram_page != dram_page:
                self.write_int('dram_controller',dram_page)
                last_dram_page = dram_page
            local_data=(self.bulkread('dram_memory',local_reads,local_offset))
            data.append(local_data)
            #print 'done'
            n_reads += local_reads
        return ''.join(data)

    def write_dram(self, data, offset=0,verbose=False):
        """Writes data to a ROACH's DRAM. Writes are done up to 512KiB at a time.
           The 64MB indirect address register is automatically incremented as necessary.
           ROACH has a fixed device name for the DRAM (dram memory) and so the user does not need to specify the write register.

           @param self    This object.
           @param data    Binary packed string to write.
           @param offset  Integer: offset to read data from (in bytes).
           @return  Binary string: data read.
        """
        size=len(data)
        n_writes=0
        last_dram_page = -1

        dram_indirect_page_size=(64*1024*1024)
        write_chunk_size=(1024*512)
        if verbose: print 'writing a total of %8i bytes from offset %8i...'%(size,offset)

        while n_writes < size:
            dram_page=(offset+n_writes)/dram_indirect_page_size
            local_offset = (offset+n_writes)%(dram_indirect_page_size)
            local_writes = min(write_chunk_size,size-n_writes,dram_indirect_page_size-(offset%dram_indirect_page_size))
            if verbose: print 'Writing %8i bytes from indirect address %4i at local offset %8i...'%(local_writes,dram_page,local_offset)
            if last_dram_page != dram_page:
                self.write_int('dram_controller',dram_page)
                last_dram_page = dram_page

            self.blindwrite('dram_memory',data[n_writes:n_writes+local_writes],local_offset)
            n_writes += local_writes

    def write(self, device_name, data, offset=0):
        """Should issue a read command after the write and compare return to
           the string argument to confirm that data was successfully written.

           Throw exception if not match. (alternative command 'blindwrite' does
           not perform this confirmation).

           @see blindwrite
           @param self  This object.
           @param device_name  String: name of device / register to write to.
           @param data  Byte string: data to write.
           @param offset  Integer: offset to write data to (in bytes)
           """
        self.blindwrite(device_name, data, offset)
        new_data = self.read(device_name, len(data), offset)
        if new_data != data:

            unpacked_wrdata=struct.unpack('>L',data[0:4])[0]
            unpacked_rddata=struct.unpack('>L',new_data[0:4])[0]

            self._logger.error("Verification of write to %s at offset %d failed. Wrote 0x%08x... but got back 0x%08x..."
                % (device_name, offset, unpacked_wrdata, unpacked_rddata))
            raise RuntimeError("Verification of write to %s at offset %d failed. Wrote 0x%08x... but got back 0x%08x..."
                % (device_name, offset, unpacked_wrdata, unpacked_rddata))

    def blindwrite(self, device_name, data, offset=0):
        """Unchecked data write.

           @see write
           @param self  This object.
           @param device_name  String: name of device / register to write to.
           @param data  Byte string: data to write.
           @param offset  Integer: offset to write data to (in bytes)
           """
        assert (type(data)==str) , 'You need to supply binary packed string data!'
        assert (len(data)%4) ==0 , 'You must write 32bit-bounded words!'
        assert ((offset%4) ==0) , 'You must write 32bit-bounded words!'
        self._request("write", self._timeout, device_name, str(offset), data)

    def read_int(self, device_name, offset=0):
        """Calls .read() command with size=4, offset=0 and
           unpacks returned four bytes into signed 32bit integer.

           @see read
           @param self  This object.
           @param device_name  String: name of device / register to read.
           @param offset int: The offset (in 32bit words) at which to read; default is zero.
           @return  Integer: value read.
           """
        data = self.read(device_name, 4, offset*4)
        return struct.unpack(">i", data)[0]

    def write_int(self, device_name, integer, blindwrite=False, offset=0):
        """Calls .write() with optional offset and integer packed into 4 bytes.

           @see write
           @param self  This object.
           @param device_name  String: name of device / register to write to.
           @param integer  Integer: value to write.
           @param blindwrite  Boolean: if true, don't verify the write (calls blindwrite instead of write function).
           @param offset  Integer: position in 32-bit words where to write data.
           """
        # careful of packing input data into 32 bit - check range: if
        # negative, must be signed int; if positive over 2^16, must be unsigned
        # int.
        if integer < 0:
            data = struct.pack(">i", integer)
        else:
            data = struct.pack(">I", integer)
        if blindwrite:
            self.blindwrite(device_name,data,offset*4)
            self._logger.debug("Blindwrite %8x to register %s at offset %d done."
                % (integer, device_name, offset))
        else:
            self.write(device_name, data, offset*4)
            self._logger.debug("Write %8x to register %s at offset %d ok."
                % (integer, device_name, offset))

    def read_uint(self, device_name,offset=0):
        """As in .read_int(), but unpack into 32 bit unsigned int. Optionally read at an offset 32-bit register.

           @see read_int
           @param self  This object.
           @param device_name  String: name of device / register to read from.
           @param offset int: The offset (in 32bit words) at which to read; default is zero.
           @return  Integer: value read.
           """
        data = self.read(device_name, 4, offset*4)
        return struct.unpack(">I", data)[0]

    def stop(self):
        """Stop the client.

           @param self  This object.
           """
        super(FpgaClient,self).stop()
        self.join(timeout=self._timeout)

    def get_10gbe_core_details(self, dev_name):
        """Prints 10GbE core details.
           @param dev_name string: Name of the core.
        """
        #assemble struct for header stuff...
        #0x00 - 0x07: My MAC address
        #0x08 - 0x0b: Not used
        #0x0c - 0x0f: Gateway addr
        #0x10 - 0x13: my IP addr
        #0x14 - 0x17: Not assigned
        #0x18 - 0x1b: Buffer sizes
        #0x1c - 0x1f: Not assigned
        #0x20       : soft reset (bit 0)
        #0x21       : fabric enable (bit 0)
        #0x22 - 0x23: fabric port
        #0x24 - 0x27: XAUI status (bit 2,3,4,5=lane sync, bit6=chan_bond)
        #0x28 - 0x2b: PHY config
        #0x28       : RX_eq_mix
        #0x29       : RX_eq_pol
        #0x30 - 0x33: Multicast IP RX base address
        #0x34       : Multicast IP RX IP mask
        #0x38 - 0x3b: Subnet mask
        #0x2a       : TX_preemph
        #0x2b       : TX_diff_ctrl
        #0x1000     : CPU TX buffer
        #0x2000     : CPU RX buffer
        #0x3000     : ARP tables start

        port_dump=list(struct.unpack('>16384B',self.read(dev_name,16384)))
        #ip_prefix = '%3d.%3d.%3d.'%(port_dump[0x10],port_dump[0x11],port_dump[0x12])

        rv={}
        mymac=((port_dump[02]<<40) + (port_dump[03]<<32) + (port_dump[04]<<24) + (port_dump[05]<<16) + (port_dump[06]<<8) + port_dump[07])
        rv['mymac']=mymac

        gateway=((port_dump[0x0c]<<24) + (port_dump[0x0d]<<16) + (port_dump[0x0e]<<8) + (port_dump[0x0f]))
        rv['gateway_ip']=gateway

        my_ip=((port_dump[0x10]<<24) + (port_dump[0x11]<<16) + (port_dump[0x12]<<8) + (port_dump[0x13]))
        rv['my_ip']=my_ip

        rv['multicast_rx_base_ip']=((port_dump[0x30]<<24) + (port_dump[0x31]<<16) + (port_dump[0x32]<<8) + (port_dump[0x33]))
        rv['multicast_rx_mask'] = ((port_dump[0x34]<<24) + (port_dump[0x35]<<16) + (port_dump[0x36]<<8) + (port_dump[0x37]))
        rv['subnet_mask'] = ((port_dump[0x38]<<24) + (port_dump[0x39]<<16) + (port_dump[0x3a]<<8) + (port_dump[0x3b]))
        possible_addresses=[rv['multicast_rx_base_ip']]
        for i in range(32):
            if not ((rv['multicast_rx_mask']>>i)&1):
                #print "Found a zero!"
                new_ips=[]
                for ip in possible_addresses:
                    new_ips.append(ip&(~(1<<i)))
                    new_ips.append(new_ips[-1]|(1<<i))
                    #print new_ips
                possible_addresses.extend(new_ips)
        rv['multicast_rx_addresses']=list(set(possible_addresses))

        fabric_port=((port_dump[0x22]<<8) + (port_dump[0x23]))
        rv['fabric_port']=fabric_port

        fabric_enabled=bool(port_dump[0x21]&1)
        rv['fabric_en']=fabric_enabled

        xaui_lane0_sync=bool(port_dump[0x27]&4)
        xaui_lane1_sync=bool(port_dump[0x27]&8)
        xaui_lane2_sync=bool(port_dump[0x27]&16)
        xaui_lane3_sync=bool(port_dump[0x27]&32)
        xaui_chan_bond=bool(port_dump[0x27]&64)
        xaui_status=((port_dump[0x24]<<24) + (port_dump[0x25]<<16) + (port_dump[0x26]<<8) + (port_dump[0x27]))
        rv['xaui_lane_sync']=[xaui_lane0_sync, xaui_lane1_sync, xaui_lane2_sync, xaui_lane3_sync]
        rv['xaui_status']=xaui_status
        rv['xaui_chan_bond']=xaui_chan_bond

        xaui_phy_rx_eq_mix=port_dump[0x28]
        xaui_phy_rx_eq_pol=port_dump[0x29]
        xaui_phy_tx_preemph=port_dump[0x2a]
        xaui_phy_tx_swing=port_dump[0x2b]
        rv['xaui_phy_rx_eq_mix']=xaui_phy_rx_eq_mix
        rv['xaui_phy_rx_eq_pol']=xaui_phy_rx_eq_pol
        rv['xaui_phy_tx_preemph']=xaui_phy_tx_preemph
        rv['xaui_phy_tx_swing']=xaui_phy_tx_swing

        arp=[]
        for i in range(256):
            arp.append(((port_dump[0x3000+i*8+2]<<40) + (port_dump[0x3000+i*8+3]<<32) + (port_dump[0x3000+i*8+4]<<24) + (port_dump[0x3000+i*8+5]<<16) + (port_dump[0x3000+i*8+6]<<8) + port_dump[0x3000+i*8+7]))
        rv['arp']=arp

        return rv

    def print_10gbe_core_details(self,dev_name,arp=False, cpu=False):
        """Prints 10GbE core details.
           @param dev_name string: Name of the core.
           @param arp boolean: Include the ARP table
           @param cpu boolean: Include the cpu packet buffers
        """
        port_dump=list(struct.unpack('>16384B',self.read(dev_name,16384)))
        ip_prefix= '%3d.%3d.%3d.'%(port_dump[0x10],port_dump[0x11],port_dump[0x12])

        print '------------------------'
        print 'GBE0 Configuration...'
        print 'My MAC: ',
        for m in port_dump[02:02+6]:
            print '%02X'%m,
        print ''

        print 'Gateway: ',
        for g in port_dump[0x0c:0x0c+4]:
            print '%3d'%g,
        print ''

        print 'This IP: ',
        for i in port_dump[0x10:0x10+4]:
            print '%3d'%i,
        print ''

        print 'Subnet Mask: ',
        for i in port_dump[0x38:0x38+4]:
            print '%3d'%i,
        print ''

        print 'Gateware Port: ',
        print '%5d'%(port_dump[0x22]*(2**8)+port_dump[0x23])

        print 'Fabric interface is currently: ',
        if port_dump[0x21]&1: print 'Enabled'
        else: print 'Disabled'


        print 'XAUI Status: ',
        print '%02X%02X%02X%02X'%(port_dump[0x24],port_dump[0x25],port_dump[0x26],port_dump[0x27])
        print '\t lane sync 0: %i'%bool(port_dump[0x27]&4)
        print '\t lane sync 1: %i'%bool(port_dump[0x27]&8)
        print '\t lane sync 2: %i'%bool(port_dump[0x27]&16)
        print '\t lane sync 3: %i'%bool(port_dump[0x27]&32)
        print '\t Channel bond: %i'%bool(port_dump[0x27]&64)

        print 'XAUI PHY config: '
        print '\tRX_eq_mix: %2X'%port_dump[0x28]
        print '\tRX_eq_pol: %2X'%port_dump[0x29]
        print '\tTX_pre-emph: %2X'%port_dump[0x2a]
        print '\tTX_diff_ctrl: %2X'%port_dump[0x2b]

        if arp:
            print 'ARP Table: '
            for i in range(256):
                print 'IP: %s%3d: MAC:'%(ip_prefix,i),
                for m in port_dump[0x3000+i*8+2:0x3000+i*8+8]:
                    print '%02X'%m,
                print ''

        if cpu:
            print 'CPU TX Interface (at offset 4096bytes):'
            print 'Byte offset:  Contents (Hex)'
            for i in range(4096/8):
                print '%04i:        '%(i*8),
                for l in range(8): print '%02x'%port_dump[4096+8*i+l],
                print ''
            print '------------------------'

            print 'CPU RX Interface (at offset 8192bytes):'
            print 'CPU packet RX buffer unacknowledged data: %i'%port_dump[6*4+3]
            print 'Byte offset:  Contents (Hex)'
            for i in range(port_dump[6*4+3]+8):
                print '%04i:        '%(i*8),
                for l in range(8): print '%02x'%port_dump[8192+8*i+l],
                print ''
        print '------------------------'

    def est_brd_clk(self):
        """Returns the approximate clock rate of the FPGA in MHz."""
        firstpass=self.read_uint('sys_clkcounter')
        time.sleep(2)
        secondpass=self.read_uint('sys_clkcounter')
        if firstpass>secondpass: secondpass=secondpass+(2**32)
        return (secondpass-firstpass)/2000000.

    def qdr_status(self,qdr):
         """Checks QDR status (PHY ready and Calibration). NOT TESTED.
            \n@param qdr integer QDR controller to query.
            \n@return dictionary of calfail and phyrdy boolean responses."""
         #offset 0 is reset (write 0x111111... to reset). offset 4, bit 0 is phyrdy. bit 8 is calfail.
         assert((type(qdr)==int))
         qdr_ctrl = struct.unpack(">I",self.read('qdr%i_ctrl'%qdr, 4, 4))[0]
         return {'phyrdy':bool(qdr_ctrl&0x01),'calfail':bool(qdr_ctrl&(1<<8))}

    def qdr_rst(self,qdr):
         """Performs a reset of the given QDR controller (tries to re-calibrate). NOT TESTED.
            \n@param qdr integer QDR controller to query.
            \n@returns nothing."""
         assert((type(qdr)==int))
         self.write_int('qdr%i_ctrl'%qdr,0xffffffff,blindwrite=True)

    def get_snap(self, dev_name, brams, man_trig=False, man_valid=False, wait_period=1, offset=-1, circular_capture=False,word_mult=1):
        """Grabs all brams from a single snap block on this FPGA device.\n
            \tdev_name: string, name of the snap block.\n
            \tman_trig: boolean, Trigger the snap block manually.\n
            \toffset: integer, wait this number of valids before beginning capture. Set to negative value if    your hardware doesn't support this or the circular capture function.\n
            \tcircular_capture: boolean, Enable the circular capture function.\n
            \twait_period: integer, wait this number of seconds between triggering and trying to read-back the data. Make it negative to wait forever.\n
            \tbrams: list, names of the bram components.\n
            \tword_mult: The snap block reports how many words were captured. Here we can specify how wide a word is (in 32-bit multiples) in order to retrieve the correct number of bytes. set to 2 for 64b snap blocks, 4 for 128b etc. Else we assume a 32-bit wide bram and pull addr*4 bytes.\n
            \tRETURNS: dictionary with keywords: \n
            \t\tlengths: list of integers matching number of valids captured off each fpga.\n
            \t\toffset: optional (depending on snap block version) list of number of valids elapsed since last  trigger on each fpga.
            \t\t{brams}: list of data from each fpga for corresponding bram.\n"""
        #print "Deprecation warning: get_snap is to be deprecated. Please replace your design's %s block with a 'snapshot' block and use the snapshot_get function instead."%dev_name
        self._logger.warn("Deprecation warning: get_snap is to be deprecated. Please replace your design's %s block with a 'snapshot' block and use the snapshot_get function instead."%dev_name)
        #2011-02-03 JRM added circular capture to trigger statement.
        #               Invert logic for end detect.
        #               Added wait forever option.
        #               copy-paste errors from corr_functions :( really need to consolodate these snap functions.
        #2010-02-19 JRM Updated to match snap_x.
        #WORKING OK 2009-07-01
        if offset >= 0:
            self.write_int(dev_name+'_trig_offset',offset)
            #print 'Capturing from snap offset %i'%offset

        #print 'Triggering Capture...',
        self.write_int(dev_name+'_ctrl',(0 + (man_trig<<1) + (man_valid<<2) + (circular_capture<<3)))
        self.write_int(dev_name+'_ctrl',(1 + (man_trig<<1) + (man_valid<<2) + (circular_capture<<3)))

        done=False
        start_time=time.time()
        while not (done and (offset>=0 or circular_capture)) and ((time.time()-start_time)<wait_period or (wait_period < 0)):
            addr = self.read_uint(dev_name+'_addr')
            done = not bool(addr & 0x80000000)

        bram_size= self.read_uint(dev_name+'_addr')&0x7fffffff
        bram_dmp=dict()
        bram_dmp={'length':bram_size+1}
        bram_dmp['offset']=0
        if (bram_size != self.read_uint(dev_name+'_addr')&0x7fffffff) or bram_size==0:
            #if address is still changing, then the snap block didn't finish capturing. we return empty.
            raise RuntimeError("Looks like snap block didn't finish.")
            bram_dmp['length']=0
            bram_dmp['offset']=0
            bram_size=0

        if circular_capture or (offset>=0):
            #print 'offset: %i,tr_en_cnt: %i'%(offset,self.read_uint(dev_name+'_tr_en_cnt'))
            bram_dmp['offset']=self.read_uint(dev_name+'_tr_en_cnt') + offset - bram_size
        else: bram_dmp['offset']=0

        if (bram_dmp['offset'] < 0):
            #you got a trigger and then a stop before the bram could even fill.
            bram_dmp['offset']=0

        for b,bram in enumerate(brams):
            bram_path = dev_name+'_'+bram
            if (bram_size == 0):
                bram_dmp[bram]=[]
            else:
                bram_dmp[bram]=(self.read(bram_path,(bram_size+1)*4*word_mult))
        return bram_dmp

    def get_rcs(self,rcs_block_name='rcs'):
        """Retrieves and decodes a revision control block."""
        rv={}
        rv['user']=self.read_uint(rcs_block_name+'_user')
        app=self.read_uint(rcs_block_name+'_app')
        lib=self.read_uint(rcs_block_name+'_lib')
        if lib&(1<<31):
            rv['compile_timestamp']=lib&((2**31)-1)
        else:
            if lib&(1<<30):
                #type is svn
                rv['lib_rcs_type']='svn'
            else:
                #type is git
                rv['lib_rcs_type']='git'
            if lib&(1<<28):
                #dirty bit
                rv['lib_dirty']=True
            else:
                rv['lib_dirty']=False
            rv['lib_rev']=lib&((2**28)-1)
        if app&(1<<31):
            rv['app_last_modified']=app&((2**31)-1)
        else:
            if app&(1<<30):
                #type is svn
                rv['app_rcs_type']='svn'
            else:
                #type is git
                rv['app_rcs_type']='git'
            if app&(1<<28):
                #dirty bit
                rv['app_dirty']=True
            else:
                rv['lib_dirty']=False
            rv['app_rev']=app&((2**28)-1)
        return rv

    def snapshot_arm(self, dev_name, man_trig=False, man_valid=False, offset=-1, circular_capture=False):
        if offset >=0:
            self.write_int(dev_name+'_trig_offset', offset)
            #print 'Capturing from snap offset %i'%offset
        #print 'Triggering Capture...',
        self.write_int(dev_name + '_ctrl', (0 + (man_trig<<1) + (man_valid<<2) + (circular_capture<<3)))
        self.write_int(dev_name + '_ctrl', (1 + (man_trig<<1) + (man_valid<<2) + (circular_capture<<3)))

    def snapshot_get(self, dev_name, man_trig=False, man_valid=False, wait_period=1, offset=-1, circular_capture=False, get_extra_val=False, arm=True):
        """Grabs all brams from a single snap block on this FPGA device.\n
            \tdev_name: string, name of the snap block.\n
            \tman_trig: boolean, Trigger the snap block manually.\n
            \toffset: integer, wait this number of bytes before beginning capture. Set to negative to ignore.\n
            \tcircular_capture: boolean, Enable the circular capture function.\n
            \twait_period: integer, wait this number of seconds between triggering and trying to read-back the data. Make it negative to wait forever.\n
            \tRETURNS: dictionary with keywords: \n
            \t\tlengths: number of bytes captured.\n
            \t\toffset: number of bytes since last trigger.\n
            \t\tdata: list of data from each fpga for corresponding bram.\n"""
        # new snapshot block support (bytes instead of words) with hardware-configurable datawidth and user-selectable features.
        #TODO Test offset, get_extra_val and circular capture modes.
        if arm:
            self.snapshot_arm(dev_name=dev_name, man_trig=man_trig, man_valid=man_valid, offset=offset, circular_capture=circular_capture)
        done=False
        start_time=time.time()
        while not done and ((time.time()-start_time)<wait_period or (wait_period < 0)):
            addr = self.read_uint(dev_name+'_status')
            done = not bool(addr & 0x80000000)
            time.sleep(0.05)

        bram_size= addr&0x7fffffff
        bram_dmp=dict()
        bram_dmp['length']=bram_size
        if (bram_size != self.read_uint(dev_name+'_status')&0x7fffffff) or bram_size==0:
            #if address is still changing, then the snap block didn't finish capturing. we return empty.
            raise RuntimeError("A snap block logic error occurred or it didn't finish capturing in the allotted %2.2f seconds. Reported %i bytes captured."%(wait_period,bram_size))
            bram_dmp['length']=0
            bram_dmp['offset']=0
            bram_size=0

        if circular_capture:
            #print 'offset: %i,tr_en_cnt: %i'%(offset,self.read_uint(dev_name+'_tr_en_cnt'))
            # Snap block only starts incrementing tr_en_cnt after it has started writing into memory. Must thus add requested offset. Done later anyway.
            bram_dmp['offset']=self.read_uint(dev_name+'_tr_en_cnt') - bram_size
        else:
            bram_dmp['offset']=0

        bram_dmp['offset']+=offset

        if (bram_dmp['offset'] < 0):
            #you got a trigger and then a stop before the bram could even fill.
            bram_dmp['offset']=0

        if (bram_size == 0):
            bram_dmp['data']=[]
        else:
            bram_dmp['data']=(self.read(dev_name+'_bram',(bram_size)))

        if get_extra_val==True:
            bram_dmp['val']=self.read_uint(dev_name+'_val')

        return bram_dmp

    def arp_announce_adj(self,dev_name, announce_start=130, announce_stop=10000, announce_step=500):
        """Adjust the issuing of unsolicited ARP announcements' algorithm parameters. Requires ROACH2 romfs 2014-12-11 or later.
          @param announce_start A
          @param announce_stop A
          @param announce_step A
          @return katcp response. 
        """
        reply, informs = self._request("tap-arp-config", self._timeout, dev_name, 'announce-start',announce_start/10)
        reply, informs = self._request("tap-arp-config", self._timeout, dev_name, 'announce-step',announce_step/10)
        reply, informs = self._request("tap-arp-config", self._timeout, dev_name, 'announce-stop',announce_stop/10)
        self._logger.info("Adjusting ARP algorithm on interface %s: announce period initially %i ms, incrementing by %i ms to %i ms... %s"%(dev_name,announce_start,announce_step,announce_stop,reply.arguments[0]))
        return reply.arguments[0]

    def arp_timeout_adj(self,dev_name, valid_timeout=500000):
        """Adjusts the ARP valid timeout (cache time). 
          @param self  This object.
          @param dev_name The name of the GbE device.
          @param valid_timout Time in ms since last receiving an ARP response before an address will be re-queried. Ie don't send a query for an address that responded in the last valid_timeout ms.
          @return katcp response. 
        """
        reply, informs = self._request("tap-arp-config", self._timeout, dev_name, 'valid_timeout',valid_timeout/10)
        self._logger.info("Adjusting ARP algorithm on interface %s: cache timeout set to %i ms... %s"%(dev_name,valid_timeout,reply.arguments[0]))
        return reply.arguments[0]
    
    def arp_query_adj(self,dev_name, query_start=250, query_stop=50000, query_step=500):
        """Adjust the ARP query algorithm parameters. Requires ROACH2 romfs 2014-12-11 or later.
          @param self  This object.
          @param dev_name The name of the GbE device.
          @param query_start   Rate at which to start issuing ARP requests (ms between packets). Nominally ~100ms.
          @param query_stop    Final, minimum rate at which to issue ARP requests (ms between packets). Nominally ~10000ms.
          @param query_step    Adjusts the slope steepness between query_start and query_stop. Higher values move to query_stop steady-state more quickly.
          @return katcp response. 
        """
        reply, informs = self._request("tap-arp-config", self._timeout, dev_name, 'query-start',query_start/10)
        reply, informs = self._request("tap-arp-config", self._timeout, dev_name, 'query-step',query_step/10)
        reply, informs = self._request("tap-arp-config", self._timeout, dev_name, 'query-stop',query_stop/10)
        self._logger.info("Adjusting ARP algorithm on interface %s: query period initially %i ms, incrementing by %i ms to %i ms... %s"%(dev_name,query_start,query_step,query_stop,reply.arguments[0]))
        return reply.arguments[0]
        
    def arp_reload(self, dev_name):
        """Force an ARP update on 'dev_name' interface.
          @param self  This object.
          @param dev_name The name of the GbE device.
          @return  Nothing, just the KATCP response.
        """
        reply, informs = self._request("tap-arp-reload", self._timeout, dev_name)
        self._logger.info("Reloading ARP table on interface %s... %s."%(dev_name,reply.arguments[0]))
        return reply.arguments[0]

def ip_to_a(ip):
    return '%i.%i.%i.%i'%((ip>>24),((ip&(0xff<<16))>>16),((ip&(0xff<<8))>>8),(ip&(0xff)))
