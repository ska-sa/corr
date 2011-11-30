#!/usr/bin/env python

"""
Transmits correlator vacc data by reading out a snap block on the roach. This script was originally written for PAPER and has been hard coded to use SPEAD-64-40 for interleaved Xengine frequency output.

It is designed to run on the ROACH boards without access to any other config info or libraries. Apart from some basic command line config options, all required info is pulled from the FPGAs themselves. This means that we expect certain registers to be in place. 

Author: Jason Manley

Revisions:
2010-07-27  JRM Port to SPEAD
                Fixed hard-coded heap size

2010-02-24  JRM Added support for multiple X engines per FPGA.
                Now prints time difference between integration dumps.

2010-01-20  JRM Mangled new script together from other bits of code.

historic version info:
2008-09-10  JRM Bugfix "pack"

2008-02-13  JRM Further cleanups
                Additional sanity checks

2008-02-08  JRM New packet format
                Removed Rawpacket class - unified with CasperN_Packet
                Neatened CasperN_RX_correlator

2007-08-29  JRM Changed some endian-ness handling for packet decoding
"""

import time, os, socket, struct, sys

class spead_packet:
    """Pack and unpack the binary correlation data in a SPEAD packet,
    assuming the data is stored as signed (4 byte) integers."""

    def __init__(self, endian='>'):
        self.data_fmt = 'i'
        self.word_size = struct.calcsize(self.data_fmt)
        self.endian = endian
        self.header_fmt = '%sBBBBHHQQQQQQ' % (endian)
        self.header_size = struct.calcsize(self.header_fmt)

    def get_hdr_size(self):
        return self.header_size

    def pack_from_prms(self, timestamp, xeng, offset, heap_len, data):
        """Create a packet."""
        if type(data) is str: 
            str_data = data
        else:
            fmt = '%s%d%s' % (self.endian, len(d['data'])*self.word_size,self.data_fmt)
            str_data = struct.pack(fmt, 'data')
        
        spead_magic=0x53
        spead_ver=4
        spead_item_pointer_width=3 #in bytes
        spead_heap_addr_width=5    #in bytes
        spead_rsvd=0
        n_options=6
       
        #req'd SPEAD items: 
        option1 = (1<<63) + (1<<40) + timestamp+xeng    #heap counter, unique to each engine
        option2 = (1<<63) + (2<<40) + heap_len          #heap size
        option3 = (1<<63) + (3<<40) + offset            #heap offset
        option4 = (1<<63) + (4<<40) + len(str_data)     #packet payload length
        #add timestamp and data:
        option5 = (1<<63) + ((0x1600+xeng)<<40) + timestamp
        option6 = (0<<63) + ((0x1800+xeng)<<40) + 0

        #print "PKT sending at timestamp %i for xeng %i at offset %i."%(timestamp,xeng,offset)

        return struct.pack(self.header_fmt,
                            spead_magic,spead_ver,spead_item_pointer_width,spead_heap_addr_width,spead_rsvd,n_options,
                            option1, option2, option3, option4, option5, option6) + str_data


#  _______  __    ____             _        _
# \_   _\ \/ /   / ___|  ___   ___| | _____| |_
#   | |  \  /    \___ \ / _ \ / __| |/ / _ \ __|
#   | |  /  \     ___) | (_) | (__|   <  __/ |_
#   |_| /_/\_\___|____/ \___/ \___|_|\_\___|\__|
#           |_____|

class UDP_TX_Socket(socket.socket):
    """Implements a UDP socket which transmits at a given ip, port."""
    def __init__(self, ip, port):
        self.ip = ip
        #print 'Set ip to %s' %self.ip
        self.port = port
        socket.socket.__init__(self, type=socket.SOCK_DGRAM)
        self.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        #self.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 20)
        #self.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        #req = struct.pack('4sl', socket.inet_aton(ip), socket.INADDR_ANY)
        #self.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, req)
    def tx(self, data):
        """Send a UDP packet containing binary 'data'."""
        #print 'Sending to ip %s on port %i' %(self.ip,self.port)
        return self.sendto(data, (self.ip, self.port))

class spead_tx_socket(UDP_TX_Socket, spead_packet):
    """Combines a UDP_TX_Socket with the casper_n packet format."""
    def __init__(self, ip, port, endian='>'):
        UDP_TX_Socket.__init__(self, ip, port)
        spead_packet.__init__(self, endian=endian)
    def send_packet(self, timestamp, xeng, offset, heap_len, data):
        """Send a UDP packet using the SPEAD packet format."""
        return self.tx(self.pack_from_prms(timestamp, xeng, offset, heap_len, data))


class CorrTX:
    def __init__(self, pid, endian='>',ip='10.0.0.1', x_per_fpga=2, port=7147, payload_len=4096, verbose=False, timestamp_rnd=1024*1024):
        self.pid=pid
        self.endian = endian
        self.casper_sock=spead_tx_socket(ip,port,endian)
        self.ip=ip
        self.port=port
        self.payload_len=payload_len
        self.verbose=verbose
        self.x_per_fpga = x_per_fpga
        self.snap_addr=[]
        self.snap_bram=[]
        self.snap_en=[]
        self.xeng=[]
        self.vacc_mcnt_l=[]
        self.vacc_mcnt_h=[]
        for x in range(x_per_fpga):
            self.snap_addr.append(open('/proc/%i/hw/ioreg/snap_vacc%i_addr'%(pid,x),'r'))
            self.snap_bram.append(open('/proc/%i/hw/ioreg/snap_vacc%i_bram'%(pid,x),'r'))
            self.snap_en.append(open('/proc/%i/hw/ioreg/snap_vacc%i_ctrl'%(pid,x),'w'))
            self.vacc_mcnt_l.append(open('/proc/%i/hw/ioreg/vacc_mcnt_l%i'%(pid,x),'r'))
            self.vacc_mcnt_h.append(open('/proc/%i/hw/ioreg/vacc_mcnt_h%i'%(pid,x),'r'))
            #self.vacc_mcnt=(open('/proc/%i/hw/ioreg/vacc_mcnt%i'%(pid,x),'r'))

            xeng_file=(open('/proc/%i/hw/ioreg/inst_xeng_id%i'%(pid,x),'r'))
            xeng_file.seek(2)
            self.xeng.append(struct.unpack('>H',xeng_file.read(2))[0])
            xeng_file.close()
            print ('Ready to send output data from Xeng %i to IP %s on port %i.' %(self.xeng[x],ip,port))
    

        self.timestamp_rnd=timestamp_rnd
        self._tx()

    def read_addr(self,xeng):
        self.snap_addr[xeng].flush()
        self.snap_addr[xeng].seek(0)
        self.snap_addr[xeng].flush()
        return struct.unpack('L',self.snap_addr[xeng].read(4))[0]

    def get_hw_timestamp(self,xeng):
        #self.vacc_mcnt.flush()
        #self.vacc_mcnt.seek(0)
        #self.vacc_mcnt.flush()
        self.vacc_mcnt_l[xeng].flush()
        self.vacc_mcnt_l[xeng].seek(0)
        self.vacc_mcnt_l[xeng].flush()
        self.vacc_mcnt_h[xeng].flush()
        self.vacc_mcnt_h[xeng].seek(0)
        self.vacc_mcnt_h[xeng].flush()
        #return struct.unpack('>L',self.vacc_mcnt.read(4))[0]
        return struct.unpack('>Q',self.vacc_mcnt_h[xeng].read(4)+self.vacc_mcnt_l[xeng].read(4))[0]

    def read_bram(self,xeng,size):
        """Reads "size" bytes from bram for xengine number xeng"""
        self.snap_bram[xeng].flush()
        self.snap_bram[xeng].seek(0)
        return self.snap_bram[xeng].read(size*4)

    def get_acc_len(self):
        a_l=open('/proc/%i/hw/ioreg/acc_len'%(self.pids[0]),'r')
        acc_len=struct.unpack('L',a_l.read(4))[0]
        a_l.close()
        return acc_len

    def snap_get_new(self,xeng):
        self.snap_en[xeng].seek(0)
        self.snap_en[xeng].flush()
        self.snap_en[xeng].write(struct.pack('L',0))
        self.snap_en[xeng].flush()
        self.snap_en[xeng].seek(0)
        self.snap_en[xeng].flush()
        self.snap_en[xeng].write(struct.pack('L',1))
        self.snap_en[xeng].flush()
        self.snap_en[xeng].seek(0)
        self.snap_en[xeng].flush()
        self.snap_en[xeng].write(struct.pack('L',0))
        self.snap_en[xeng].flush()
        
    def empty_buffers(self):
        print 'Flushing buffers...'
        complete=[]
        total_xeng_vectors=[]

        for xnum in range(self.x_per_fpga):
            complete.append(0)
            total_xeng_vectors.append(0)
            self.snap_get_new(xnum)
            #print 'Requested first snap grab for xeng %i'%xnum

        # Wait for data to become available
        num = 0
        while num == 0:
            time.sleep(.005)
            num = self.read_addr(0)

        while sum(complete) < self.x_per_fpga:
            for xnum in range(self.x_per_fpga):
                time.sleep(.005)
                addr = self.read_addr(xnum)
                #print 'Got addr %i on xeng %i.'%(addr,xnum)
                if addr == 0:
                    complete[xnum]=1
                    #print '\t: %i/%i complete.'%(sum(complete),self.x_per_fpga*len(self.pids)),complete
                else:
                    complete[xnum]=0
                    total_xeng_vectors[xnum] += (addr+1)
                self.snap_get_new(xnum)

        for xnum in range(self.x_per_fpga):
            print '\t: Flushed %i vectors for X engine %i. %i/%i complete.'%(total_xeng_vectors[xnum], self.xeng[xnum], sum(complete),self.x_per_fpga)


    def _tx(self):
        """Continuously transmit correlator data over udp packets."""
        target_pkt_size=(self.payload_len+self.casper_sock.header_size)

        self.empty_buffers()
        self.empty_buffers()
        self.empty_buffers()

        n_integrations = 0

        complete=[]
        timestamp=[]
        #rounded_timestamp=[]
        realtime_diff=[]
        realtime_last=[]
        int_xeng_vectors=[]

        for x in range(self.x_per_fpga):
            timestamp.append(self.get_hw_timestamp(x))
            #rounded_timestamp.append( (timestamp[x]/self.timestamp_rnd) * self.timestamp_rnd)
            realtime_diff.append(0)
            realtime_last.append(time.time())

        data = []
        for xnum in range(self.x_per_fpga):
            complete.append(0)
            int_xeng_vectors.append(0)
            data.append([])
            self.snap_get_new(xnum)
            #print 'Requested first snap grab for xeng %i'%xnum

        while True:
            # Wait for data to become available
            num = 0
            while num == 0:
                time.sleep(.1)
                num = self.read_addr(0)

            while sum(complete)<self.x_per_fpga:
                for xnum in range(self.x_per_fpga):
                    addr = self.read_addr(xnum)
                    if addr == 0:
                        complete[xnum]=1
                    else:
                        complete[xnum]=0
                        int_xeng_vectors[xnum] += (addr+1)
                        data[xnum].append(self.read_bram(xnum,addr+1))
                    self.snap_get_new(xnum)

            for x in range(self.x_per_fpga):
                timestamp[x] = self.get_hw_timestamp(x)
                realtime_diff[x]=time.time() - realtime_last[x]
                #rounded_timestamp[x] = (timestamp[x]/self.timestamp_rnd) * self.timestamp_rnd
                realtime_last[x]=time.time()

            #Now that we have collected all this integration's data, send the packets:
            for xnum in range(self.x_per_fpga):
                print '[%6i] Grabbed %i vectors for X engine %i with timestamp %i (diff ~%4.2fs).'%(n_integrations,int_xeng_vectors[xnum], self.xeng[xnum], timestamp[xnum],realtime_diff[xnum])
                data[xnum] = ''.join(data[xnum])

                #n_bls=16*17/2
                #bls=2
                #for chan in range(20):
                #    index=(chan*n_bls+bls)*2*4*4
                #    print 'Chan %4i (%4i): '%(chan,index),struct.unpack('>ii',data[xnum][index:index+8])

                for cnt in range((len(data[xnum])/self.payload_len)):
                    if self.casper_sock.send_packet(
                        timestamp=timestamp[xnum], 
                        xeng=self.xeng[xnum], 
                        offset=cnt*self.payload_len,
                        heap_len=len(data[xnum]), 
                        data=data[xnum][cnt*self.payload_len:(cnt+1)*self.payload_len]
                        ) != target_pkt_size: print 'TX fail!' 
                    #time.sleep(0.000001)
                    #print '.',
                #print ''
                data[xnum]=[]
                complete[xnum]=0
                int_xeng_vectors[xnum]=0
            n_integrations += 1

if __name__ == '__main__':
    from optparse import OptionParser

    p = OptionParser()
    p.set_usage('cn_tx.py [options] pid')
    p.set_description(__doc__)
    p.add_option('-i', '--udp_ip', dest='udp_ip', default='192.168.100.1',
        help='IP address to use for UDP transmission of correlator data.  Default is 192.168.100.1')
    p.add_option('-k', '--udp_port', dest='udp_port', type='int', default=7148,
        help='Port to use for UDP correlator data transmission.  Default is 7148')
    p.add_option('-x', '--x_per_fpga', dest='x_per_fpga', type='int', default=2,
        help='Number of X engines per FPGA.  Default is 2')
    p.add_option('-v', '--verbose', dest='verbose', action='store_true',
        help='Be verbose')
    p.add_option('-l', '--payload_len', dest='payload_len', type='int',default=4096,
        help='The length in bytes of each packet (data or payload only). Default 4096')
    p.add_option('-t', '--timestamp_rounding', dest='timestamp_rounding', type='int', default=1024*1024,
        help='Round-off the timestamp to the nearest given value. Default is 1024*1024.')
    opts, args = p.parse_args(sys.argv[1:])
    if len(args) < 1: 
        print 'Please specify PID of Xengine BORPH process.'
        sys.exit()
    pid =  int(args[0])
    c = CorrTX(pid, ip=opts.udp_ip, x_per_fpga=opts.x_per_fpga, port=opts.udp_port, payload_len=opts.payload_len, timestamp_rnd=opts.timestamp_rounding, verbose=opts.verbose)
    c.start()
