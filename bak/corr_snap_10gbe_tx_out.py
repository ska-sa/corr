#!/usr/bin/env python

'''
Grabs the contents of the 10GbE output snap blocks for analysis of SPEAD packets. THIS SCRIPT IS INCOMPLETE.

'''
import corr, time, numpy, struct, sys, logging

#brams
brams=['bram_msb','bram_lsb','bram_oob']

# OOB signalling bit offsets:
ip_addr_bit_width = 32-8
ip_addr_bit_offset = 6
eof_bit = 5
link_up_bit = 4
tx_led_bit = 3
tx_afull_bit = 2
tx_over_bit = 1
valid_bit = 0

pkt_ip_mask = (2**(ip_addr_bit_width+ip_addr_bit_offset)) -(2**ip_addr_bit_offset)

def exit_fail():
    print 'FAILURE DETECTED. Log entries:\n',c.log_handler.printMessages()
    print "Unexpected error:", sys.exc_info()

    try:
        c.disconnect_all()
    except: pass
    time.sleep(1)
    raise
    exit()

def exit_clean():
    try:
        c.disconnect_all()
    except: pass
    exit()

def ip2str(pkt_ip):
    ip_4 = (pkt_ip&((2**32)-(2**24)))>>24
    ip_3 = (pkt_ip&((2**24)-(2**16)))>>16
    ip_2 = (pkt_ip&((2**16)-(2**8)))>>8
    ip_1 = (pkt_ip&((2**8)-(2**0)))>>0
    #print 'IP:%i. decoded to: %i.%i.%i.%i'%(pkt_ip,ip_4,ip_3,ip_2,ip_1)
    return '%i.%i.%i.%i'%(ip_4,ip_3,ip_2,ip_1)    

def unpack_item(flav1,flav2,data):
    rv={}
    rv['addr_mode'] = (data & (1<<((flav2+flav1)*8-1)))>>((flav2+flav1)*8-1)
    rv['item_id']   = (data & (((2**((flav1)*8-1))-1)<<(flav2*8)))>>(flav2*8)
    rv['data_addr'] = (data &  ((2**((flav2)*8))-1))
    return rv


if __name__ == '__main__':
    from optparse import OptionParser

    p = OptionParser()
    p.set_usage('%prog [options] CONFIG_FILE')
    p.set_description(__doc__)
    p.add_option('-t', '--man_trigger', dest='man_trigger', action='store_true',default=False,
        help='Trigger the snap block manually')   
    p.add_option('-v', '--verbose', dest='verbose', action='store_true',
        help='Be Verbose; print raw packet contents.')   
    p.add_option('-n', '--core_n', dest='core_n', type='int', default=0,
        help='Core number to decode. Default 0.')


    opts, args = p.parse_args(sys.argv[1:])

    if opts.man_trigger:
        man_trig=True
    else:
        man_trig=False

    verbose=opts.verbose
    man_valid=False
    man_trig=False

    dev_name = 'snap_gbe_tx%i'%opts.core_n

    if args==[]:
        config_file=None
    else:
        config_file=args[0]
    verbose=opts.verbose

try:        
    print 'Connecting...',
    c=corr.corr_functions.Correlator(config_file=config_file,log_level=logging.DEBUG if verbose else logging.INFO, connect=False)
    c.connect()
    print 'done'

    report = dict()
    binary_point = c.config['feng_fix_pnt_pos']
    num_bits = c.config['feng_bits']
    packet_len=c.config['10gbe_pkt_len']
    n_ants = c.config['n_ants']
    n_chans = c.config['n_chans']
    n_ants_per_ibob=c.config['n_ants_per_xaui']

    print '------------------------'
    print 'Grabbing snap data...',
    servers = c.xsrvs
    fpgas=c.xfpgas
    bram_dmp=bram_dmp=corr.snap.snapshots_get(fpgas=c.xfpgas,dev_names=dev_name,man_trig=man_trig,man_valid=man_valid,wait_period=2)
    print 'done'

#print 'BRAM DUMPS:'
#print bram_dmp

    print 'Unpacking bram contents...',
    sys.stdout.flush()
    bram_oob=dict()
    for f,server in enumerate(servers):
        if len(bram_dmp[brams[2]][f])<=4:
            print '\n   No data for engine %s.'%server
            bram_oob[f]={}
        else:
            print '\n   Got %i values from %s.'%(len(bram_dmp[brams[2]][f])/4,server)
            bram_oob[f]={'raw':struct.unpack('>%iL'%(len(bram_dmp[brams[2]][f])/4),bram_dmp[brams[2]][f])}
            bram_oob[f].update({'eof':[bool(i & (2**eof_bit)) for i in bram_oob[f]['raw']]})
            bram_oob[f].update({'valid':[bool(i & (2**valid_bit)) for i in bram_oob[f]['raw']]})
            bram_oob[f].update({'link':[bool(i & (2**link_up_bit)) for i in bram_oob[f]['raw']]})
            bram_oob[f].update({'tx_led':[bool(i & (2**tx_led_bit)) for i in bram_oob[f]['raw']]})
            bram_oob[f].update({'tx_afull':[bool(i & (2**tx_afull_bit)) for i in bram_oob[f]['raw']]})
            bram_oob[f].update({'tx_over':[bool(i & (2**tx_over_bit)) for i in bram_oob[f]['raw']]})
            bram_oob[f].update({'ip_addr':[(i&pkt_ip_mask)>>ip_addr_bit_offset for i in bram_oob[f]['raw']]})
            #print '\n\nFPGA %i, bramoob:'%f,bram_oob
    print 'Done unpacking.'

    print 'Analysing packets:'
    for f,fpga in enumerate(fpgas):
        report[f]=dict()
        report[f]['pkt_total']=0
        pkt_len = 0
        prev_eof_index=-1

        i=0
        item_cnt=-1
        n_items=0

        
        while i < (len(bram_dmp[brams[1]][f])/4):  #"i" is 64 bit index
            #if verbose==True:
            pkt_64bit = struct.unpack('>Q',bram_dmp['bram_msb'][f][(4*i):(4*i)+4]+bram_dmp['bram_lsb'][f][(4*i):(4*i)+4])[0]
            print '[%s] IDX: %6i'%(servers[f],i),
            print '[%s]'%ip2str(bram_oob[f]['ip_addr'][i]),
            if bram_oob[f]['valid'][i]: print '[valid]',
            if bram_oob[f]['link'][i]: print '[link]',
            if bram_oob[f]['tx_led'][i]: print '[tx_led]',
            if bram_oob[f]['tx_afull'][i]: print '[TX buffer almost full!]',
            if bram_oob[f]['tx_over'][i]: print '[TX buffer OVERFLOW!]',

            if bram_oob[f]['eof'][i]: 
                #next piece should be SPEAD header:
                item_cnt = -1
                print '%016x'%(pkt_64bit),
                print '[EOF]'

            elif item_cnt == -1:
                #This might be a SPEAD header
                magic = (pkt_64bit &(((2**8)-1)<<56))>>56
                ver   = (pkt_64bit &(((2**8)-1)<<48))>>48
                flav1 = (pkt_64bit &(((2**8)-1)<<40))>>40
                flav2 = (pkt_64bit &(((2**8)-1)<<32))>>32
                n_items = (pkt_64bit &(((2**16)-1)))
                if magic == 0x53: 
                    print 'Looks like SPEAD%i-%i, version %i with magic 0x%2x and %i items.'%((flav1+flav2)*8,(flav2*8),ver,magic,n_items)
                    if flav1 != (c.config['spead_flavour'][0] - c.config['spead_flavour'][1])/8 or flav2 != c.config['spead_flavour'][1]/8 : \
                        print 'Warning: SPEAD flavour is not %i-%i.'%(c.config['spead_flavour'][0],c.config['spead_flavour'][1])
                    if n_items != 6: print 'Warning: n_items !=6.'
                    item_cnt=0
                else:
                    print 'Not a SPEAD packet, magic number is %i.'%magic
                    item_cnt=9999

            elif item_cnt < n_items and item_cnt >=0:
                item=unpack_item(flav1,flav2,pkt_64bit)

                if item['addr_mode'] == 0: print '[imm addr]',
                elif item['addr_mode'] == 1: print '[abs addr]',    
                else: print '[UNPACK LOGIC ERR!]'

                if item['item_id'] == 1:    print 'Heap PCNT:   %12i'%item['data_addr']
                if item['item_id'] == 2:    print 'Heap Size:   %12i'%item['data_addr']
                if item['item_id'] == 3:    print 'Heap Offset: %12i'%item['data_addr']
                if item['item_id'] == 4:    print 'Payload len: %12i'%item['data_addr']
                if item['item_id'] == 5632: print 'Timestamp:   %12i'%item['data_addr']
                if item['item_id'] == 6144: print 'Data addr:   %12i'%item['data_addr']
                item_cnt += 1

            else:
                print '%016x'%(pkt_64bit)

            i +=1

    print 'Done with all servers.'



except KeyboardInterrupt:
    exit_clean()
except:
    exit_fail()

exit_clean()
