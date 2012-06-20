"""
These functions help grab snapshot data and unpack the bitstreams.
Author: Paul Prozesky

Revs:
2012-01-09: JRM rx_snap now accepts fpga_ids instead of xeng core ids.

"""

import corr, numpy, time, struct, construct, logging
from construct import *

def snapshots_get(fpgas,dev_names,man_trig=False,man_valid=False,wait_period=-1,offset=-1,circular_capture=False):
    """Fetches data from multiple snapshot devices. fpgas and dev_names are lists of katcp_wrapper.FpgaClient,and 'snapshot_device_name', respectively.
        This function triggers and retrieves data from the snap block devices. The actual captured length and starting offset is returned with the dictionary of data for each FPGA (useful if you've done a circular capture and can't calculate this yourself).\n
        \tdev_names: list of strings, names of the snap block corresponding to FPGA list. Can optionally be 1-D, in which case name is used for all FPGAs.\n
        \tman_trig: boolean, Trigger the snap block manually.\n
        \toffset: integer, wait this number of valids before beginning capture. Set to negative if your hardware doesn't support offset triggering or to leave the register alone. Note that you should explicitly set this to zero to start directly after a trigger because by default (negative), it will remember the last-set offset value.\n
        \tcircular_capture: boolean, Enable the circular capture function.\n
        \twait_period: integer, wait this number of seconds between triggering and trying to read-back the data. Make it negative to wait forever.\n
        \tRETURNS: dictionary with keywords: \n
        \t\tlengths: list of integers matching number of valids captured off each fpga.\n
        \t\toffset: optional (depending on snap block version) list of number of valids elapsed since last trigger on each fpga.
        \t\t{brams}: list of data from each fpga for corresponding bram.\n
        """
    # 2011-06-24 JRM first write. 
    if isinstance(dev_names,str):
        dev_names=[dev_names for f in fpgas]

    if offset >=0:
        for fn,fpga in enumerate(fpgas):
            fpga.write_int(dev_names[fn]+'_trig_offset',offset)

    for fn,fpga in enumerate(fpgas):
        fpga.write_int(dev_names[fn]+'_ctrl',(0 + (man_trig<<1) + (man_valid<<2) + (circular_capture<<3)))
        fpga.write_int(dev_names[fn]+'_ctrl',(1 + (man_trig<<1) + (man_valid<<2) + (circular_capture<<3)))

    done=False
    start_time=time.time()
    while not done and ((time.time()-start_time)<wait_period or (wait_period < 0)): 
        addr      = [fpga.read_uint(dev_names[fn]+'_status') for fn,fpga in enumerate(fpgas)]
        done_list = [not bool(i & 0x80000000) for i in addr]
        if (done_list == [True for i in fpgas]): done=True

    bram_dmp=dict()
    bram_dmp['data']=[]
    bram_dmp['lengths']=[i&0x7fffffff for i in addr]
    bram_dmp['offsets']=[0 for fn in fpgas]
    for fn,fpga in enumerate(fpgas):
        now_status=bool(fpga.read_uint(dev_names[fn]+'_status')&0x80000000)
        now_addr=fpga.read_uint(dev_names[fn]+'_status')&0x7fffffff
        if (bram_dmp['lengths'][fn] != now_addr) or (bram_dmp['lengths'][fn]==0) or (now_status==True):
            #if address is still changing, then the snap block didn't finish capturing. we return empty.  
            raise RuntimeError("A snap block logic error occurred on capture #%i. It reported capture complete but the address is either still changing, or it returned 0 bytes captured after the allotted %2.2f seconds. Addr at stop time: %i. Now: Still running :%s, addr: %i."%(fn,wait_period,bram_dmp['lengths'][fn],{True:'yes',False:'no'}[now_status],now_addr))
            bram_dmp['lengths'][fn]=0
            bram_dmp['offsets'][fn]=0

        if circular_capture:
            bram_dmp['offsets'][fn]=fpga.read_uint(dev_names[fn]+'_tr_en_cnt') - bram_dmp['lengths'][fn]
        else: 
            bram_dmp['offsets'][fn]=0

        if bram_dmp['lengths'][fn] == 0:
            bram_dmp['data'].append([])
        else:
            bram_dmp['data'].append(fpga.read(dev_names[fn]+'_bram',bram_dmp['lengths'][fn]))

    bram_dmp['offsets']=numpy.add(bram_dmp['offsets'],offset)
    
    for fn,fpga in enumerate(fpgas):
        if (bram_dmp['offsets'][fn]<0): 
            bram_dmp['offsets'][fn]=0

    return bram_dmp

#def unpack_snapshot(data, bitmap, word_width=32):
#    """Unpacks data from a snap block. data is the raw binary (string). bitmap is a dictionary of form {yourvariablename: (bitfield_length,bitfield_start_pos,dtype)}. dtype should be a numpy type (eg numpy.int8, numpy.int16, numpy.uint32 etc). Bitfields with length of 1 are automatically unpacked as binary values (True/False). Word width should reflect your snap hardware block's databus width."""
#    if word_width==8:
#        req_dtype=numpy.uint8
#    elif word_width==16:
#        req_dtype=numpy.uint16
#    elif word_width==32:
#        req_dtype=numpy.uint32
#    elif word_width==64:
#        req_dtype=numpy.uint64
#    elif word_width==128:
#        req_dtype=numpy.uint128
#
#    unpacked_data = numpy.fromstring(data,dtype=numpy.int8)        
#    for key,value in bitmap.iteritems():
#   INCOMPLETE. use construct instead.


def get_adc_snapshots(correlator, ant_strs = [], trig_level = -1, sync_to_pps = True):
    """Fetches multiple ADC snapshots from hardware. Set trig_level to negative value to disable triggered captures. Timestamps only valid if system is correctly sync'd!"""
    if correlator.config['adc_n_bits'] !=8: 
        raise RuntimeError('This function is hardcoded to work with 8 bit ADCs. According to your config file, yours is %i bits.' % correlator.config['adc_n_bits'])

    fpgas = []
    dev_names = []
    for ant_str in ant_strs:    
        (ffpga_n, xfpga_n, fxaui_n, xxaui_n, feng_input) = correlator.get_ant_str_location(ant_str)
        fpgas.append(correlator.ffpgas[ffpga_n])
        dev_names.append('adc_snap%i' % feng_input)

    #if correlator.is_narrowband():
    #    return corr.corr_nb.get_adc_snapshot(c = correlator, ant_names = ant_strs, trig_level = trig_level, sync_to_pps = sync_to_pps)

    init_mcnt = correlator.mcnt_current_get(ant_str = ant_strs[0])
    mcnt_lsbs = init_mcnt & 0xffffffff

    if trig_level >= 0:
        [fpga.write_int('trig_level', trig_level) for fpga in fpgas]
        raw = snapshots_get(fpgas, dev_names, wait_period = -1, circular_capture = True, man_trig = (not sync_to_pps))
        ready = ((int(time.time() * 10) % 10) == 5)
        while not ready:
            time.sleep(0.05)
            ready = ((int(time.time() * 10) % 10) == 5)
    else:
        raw = snapshots_get(fpgas, dev_names, wait_period = 2, circular_capture = False, man_trig = (not sync_to_pps))
    
    rv = {}
    for ant_n, ant_str in enumerate(ant_strs):    
        rv[ant_str] = {'data': numpy.fromstring(raw['data'][ant_n], dtype = numpy.int8), 'offset': raw['offsets'][ant_n], 'length': raw['lengths'][ant_n]}
        ts = fpgas[ant_n].read_uint(dev_names[ant_n] + '_val')
        rv[ant_str]['timestamp'] = correlator.time_from_mcnt((init_mcnt & 0xffffffff00000000) + ts)
        if mcnt_lsbs > ts: 
            rv[ant_str]['timestamp'] += 0x100000000 # 32 bit number must've overflowed once.

    return rv
       
    #return numpy.fromstring(self.ffpgas[ffpga_n].snapshot_get('adc_snap%i'%feng_input,man_trig=False,circular_capture=True,wait_period=-1)['data'],dtype=numpy.int8)        

def get_quant_snapshot(correlator, ant_str, n_spectra = 1, man_trig = False, man_valid = False, wait_period = 2):
    """
    Fetches a quantiser snapshot from hardware for a single given antenna.
    Returns a numpy array.
    """
    if correlator.config['feng_bits'] != 4:
        raise RuntimeError('Sorry, this function is currently hard-coded to unpack 4 bit values')
    (ffpga_n, xfpga_n, fxaui_n, xxaui_n, feng_input) = correlator.get_ant_str_location(ant_str)
    ns = 0
    unpacked_vals = []
    fpga = correlator.ffpgas[ffpga_n]
    while ns < n_spectra:
        if correlator.is_wideband():
            bram_dmp = fpga.snapshot_get('quant_snap%i' % feng_input, man_trig = man_trig, man_valid = man_valid, wait_period = wait_period)
            pckd_8bit = numpy.fromstring(bram_dmp['data'], dtype = numpy.uint8)
            for val in pckd_8bit:
                # get the right 4 bit values:
                r_bits = (val & ((2**8) - (2**4))) >> 4
                i_bits = (val & ((2**4) - (2**0)))
                # cast up to signed numbers:
                unpacked_vals.append(float(((numpy.int8(r_bits << 4) >> 4))) + (1j * float(((numpy.int8(i_bits << 4) >> 4)))))
        elif correlator.is_narrowband():
            # the narrowband snap block may be shorter than one spectrum, so make sure we get enough data
            tempdata = []
            offset = 0
            while len(tempdata) < correlator.config['n_chans']:
                #quanttemp = corr.corr_nb.get_snap_quant(correlator, [fpga], offset = offset)[0][feng_input]
                logging.debug('get_quant_snapshot: nb, read snap - have %i/%i channels' % (len(tempdata), correlator.config['n_chans']))
                quanttemp = corr.corr_nb.get_snap_quant_wbc_compat(correlator, [fpga], offset = offset)[0][feng_input]
                tempdata.extend(quanttemp)
                # the debug snap block is 1024 128-bit words, so it's 16kbytes long. The offset is in BYTES!
                # the data in tempdata represents 128-bit WORDS
                offset = offset + (len(quanttemp) * 128/8)
            unpacked_vals.extend(tempdata)
        else:
            raise RuntimeError('Unknown mode.')
        ns = len(unpacked_vals) / correlator.config['n_chans']
        logging.debug('get_quant_snapshot: got spectrum %i/%i' % (ns, n_spectra))
    rv = numpy.array(unpacked_vals)
    if len(rv) % correlator.config['n_chans'] != 0:
        raise RuntimeError('Retrieved data is not a multiple of n_chans, something is wrong.')
    rv.shape = (ns, correlator.config['n_chans'])
    if ns < n_spectra:
        raise RuntimeError('Needed %i spectra, but only ended up with %i, something is wrong.' % (n_spectra, ns))
    if n_spectra == 1:
        return rv[0], 1
    else:
        return rv[0:n_spectra, :], n_spectra

def Swapped(subcon):
    """swaps the bytes of the stream, prior to parsing"""
    return Buffered(subcon,
        encoder = lambda buf: buf[::-1],
        decoder = lambda buf: buf[::-1],
        resizer = lambda length: length
    )

def get_rx_snapshot(correlator, xfpgas = [], snapname = 'snap_rx0'):
    "Grabs a snapshot of the decoded incomming packet stream. xeng_ids is a list of integers (xeng core numbers)."
    if xfpgas == []:
       xfpgas = correlator.xfpgas
    raw = snapshots_get(xfpgas, snapname, wait_period = 3, circular_capture = False, man_trig = False)
    if correlator.is_wideband():
        rx_bf = corr.corr_wb.snap_xengine_rx
    elif correlator.is_narrowband():
        rx_bf = corr.corr_nb.snap_xengine_rx
    else: raise RuntimeError('Unknown mode. Cannot get rx snapshot.')
    unp_rpt = construct.GreedyRepeater(rx_bf)
    rv = []
    for index, d in enumerate(raw['data']):
        v= {}
        v['fpga_index'] = index
        v['data'] = unp_rpt.parse(d)
        rv.append(v)
    return rv

def get_gbe_rx_snapshot(correlator, xfpgas = [], snapname = 'snap_gbe_rx0'):
    """
    Takes a list of X-ENGINE fpgas and returns the contents of the snap_gbe_rx0 block for each of them in a list.
    The list contents is a dictionary of the decoded data.
    """
    if xfpgas == []:
       xfpgas = correlator.xfpgas
    raw = snapshots_get(xfpgas, snapname, wait_period = 3, circular_capture = False, man_trig = False)
    if correlator.is_wideband():
        rx_bf = corr.corr_wb.snap_xengine_gbe_rx
    elif correlator.is_narrowband():
        rx_bf = corr.corr_nb.snap_xengine_gbe_rx
    else:
        raise RuntimeError('Unknown mode. Cannot get gbe rx snapshot.')
    unp_rpt = construct.GreedyRepeater(rx_bf)
    rv = []
    for index, d in enumerate(raw['data']):
        v = {}
        v['fpga_index'] = index
        v['data'] = unp_rpt.parse(d)
        rv.append(v)
    return rv


def get_gbe_tx_snapshot_xeng(correlator, snapnames = 'snap_gbe_tx0', offset = -1, man_trigger = False, man_valid = False):
    raw = snapshots_get(correlator.xfpgas, dev_names = snapnames, wait_period = 3, circular_capture = False, man_trig = man_trigger, offset = offset, man_valid = man_valid)
    unp_rpt = construct.GreedyRepeater(corr.corr_wb.snap_xengine_gbe_tx)
    rv = []
    for index, d in enumerate(raw['data']):
        v = {}
        v['fpga_index'] = index
        v['data'] = unp_rpt.parse(d)
        rv.append(v)
    return rv

def get_gbe_tx_snapshot_feng(correlator, snap_name = 'snap_gbe_tx0', offset = -1, man_trigger = False, man_valid = False):
    raw = snapshots_get(correlator.ffpgas, dev_names = snap_name, wait_period = 3, circular_capture = False, man_trig = man_trigger, offset = offset)
    unp_rpt = construct.GreedyRepeater(corr.corr_wb.snap_fengine_gbe_tx)
    rv = []
    #step though each FPGA for which we got snap data:
    for index, d in enumerate(raw['data']):
        v = {}
        v['fpga_index'] = index
        v['data'] = unp_rpt.parse(d)
        #add some fake values to make it look like a XAUI snap block so we can use the same functions on this data interchangeably:
        for dp in v['data']:
            dp['link_down'] = not dp['link_up']
            dp['hdr_valid'] = False
            dp['mrst'] = False
            dp['sync'] = False
        rv.append(v)
    return rv

def get_xaui_snapshot(correlator, snap_name = None, offset = -1, man_trigger = False, man_valid = False, wait_period = 3):
    """Grabs data from fengines' TX xaui blocks"""
    if correlator.is_wideband():
        snap_bitfield = corr.corr_wb.snap_fengine_xaui
        if snap_name == None:
            dev_name = 'snap_xaui0'
        else:
            dev_name = snap_name
        raw = snapshots_get(correlator.ffpgas, dev_names = dev_name, wait_period = wait_period, circular_capture = False, man_trig = man_trigger, offset = offset, man_valid = man_valid)
    elif correlator.is_narrowband():
        snap_bitfield = corr.corr_nb.snap_fengine_xaui
        if snap_name == None:
            dev_name = 'snap_xaui'
        else:
            dev_name = snap_name
        raw = corr.corr_nb.get_snap_xaui(correlator, correlator.ffpgas, offset = offset, man_trigger = man_trigger, man_valid = man_valid, wait_period = wait_period)
    else:
        raise RuntimeError('Unsupported correlator type.')
    unpack_repeater = construct.GreedyRepeater(snap_bitfield)
    rv = []
    for index, d in enumerate(raw['data']):
        v = {}
        v['fpga_index'] = index
        v['data'] = unpack_repeater.parse(d)
        for dp in v['data']:
            dp['ip_addr'] = 0
            dp['link_up'] = not dp['link_down']
            dp['tx_over'] = False
            dp['tx_full'] = False
            dp['led_tx'] = False
            dp['link_up'] = False
        rv.append(v)
    return rv

