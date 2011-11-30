#!/usr/bin/env python

'''
Turns on the pre-CT TVG on a specified F-engine roach and check the contents of the XAUI packets
to ensure they contain the correct data. i.e. the channel number.

Author: Paul Prozesky

Revisions:
2010-11-04: PVP Based on corr_snap_xaui_feng, check that the XAUI packet contains the correct thing after the pre-corner turner TVG is switched on.
'''

import corr, struct, sys, logging

# snap and bram names
brams = ['bram_msb', 'bram_lsb', 'bram_oob']
snapName = 'snap_xaui0'

# OOB signalling bit allocations:
linkdn_bit =    8
mrst_bit =      4
adc_bit =       3
eof_bit =       2
sync_bit =      1
hdr_bit =       0

def exit_fail():
    print 'FAILURE DETECTED. Log entries:\n',c.log_handler.printMessages()
    print "Unexpected error:", sys.exc_info()
    try:
        c.feng_ctrl_set_all(tvg_ct_sel = False, tvg_en = False)
        c.disconnect_all()
    except: pass
    raise
    exit()

def exit_clean():
    try:
        c.feng_ctrl_set_all(tvg_ct_sel = False, tvg_en = False)
        c.disconnect_all()
    except: pass
    exit()

# unpack 64-bits of data - 32 from bram_msb and 32 from bram_lsb
def feng_unpack(f, hdr_index, pkt_len, skip_indices):
    headerIndex = 4 * hdr_index
    pkt_64bit = struct.unpack('>Q', bram_dmp['bram_msb'][f][headerIndex : headerIndex + 4] + bram_dmp['bram_lsb'][f][headerIndex : headerIndex + 4])[0]
    pkt_mcnt = (pkt_64bit & ((2**64) - (2**16))) >> 16
    pkt_ant  = pkt_64bit & ((2**16) - 1)
    pkt_freq = pkt_mcnt % n_chans

    # average the packet contents - ignore first entry (header)
    dataTotal = 0
    dataCount = 0
    mismatchErrors = 0
    for pkt_index in range(1, (pkt_len)):
        abs_index = hdr_index + pkt_index
        
        if skip_indices.count(abs_index)>0: 
            print 'Skipped %i' % abs_index
            continue

        pkt_64bit = struct.unpack('>Q', bram_dmp['bram_msb'][f][(4*abs_index):(4*abs_index)+4]+bram_dmp['bram_lsb'][f][(4*abs_index):(4*abs_index)+4])[0]

        for offset in range(0,64,16):
            # read the data counter out of the data in the packet and compare it to the frequency channel counter from the oob
            data = (pkt_64bit & ((2**(offset + 16)) - (2**(offset)))) >> offset
            dataTotal += data
            dataCount += 1
            if data != pkt_freq:
                mismatchErrors += 1
                if opts.verbose:
                    print "Error: F-engine(%s) antenna(%i) - pkt_freq in header %i, data reads %i" % (f, pkt_ant, pkt_freq, data)
                    break
    
    num_accs = (pkt_len - len(skip_indices)) * (64 / 16)

    return {'pkt_mcnt': pkt_mcnt,\
            'pkt_ant': pkt_ant,\
            'pkt_freq': pkt_freq,\
            'dataTotal': dataTotal,\
            'dataCount': dataCount,\
            'mismatchErrors': mismatchErrors}

# if this is being run as a standalone script, which it always will be, then process command-line args
if __name__ == '__main__':
    from optparse import OptionParser
    p = OptionParser()
    p.set_usage('%prog [options] CONFIG_FILE')
    p.set_description(__doc__)
    p.add_option('-f', '--fengine', dest='fengineToUse', type='int', default=0, help='Which f-engine should be checked.')
    p.add_option('-v', '--verbose', dest='verbose', action='store_true', help='Print raw output.')
    #p.add_option('-t', '--man_trigger', dest='man_trigger', action='store_true', help='Trigger the snap block manually')
    #p.add_option('-o', '--offset', dest='offset', type='int', default=0, help='Offset in channels to start capturing. Default: 0')
    #p.add_option('-x', '--xaui_port', dest='xaui_port', type='int', default=0, help='Capture from which XAUI port. Default: 0')
    opts, args = p.parse_args(sys.argv[1:])

    if args==[]:
        config_file=None
    else:
        config_file=args[0]
    verbose=opts.verbose

try:
    print 'Connecting...',
    c=corr.corr_functions.Correlator(config_file=config_file,log_level=logging.DEBUG if verbose else logging.INFO,connect=False)
    c.connect()
    print 'done'

    collectedData = {}
    offset = 0
    
    # turn on the TVG before the corner turner
    c.feng_ctrl_set_all(tvg_ct_sel = True, tvg_en = True)

    binary_point = c.config['feng_fix_pnt_pos']
    packet_len = c.config['10gbe_pkt_len']
    n_chans = c.config['n_chans']
    num_bits = c.config['feng_bits']
    adc_bits = c.config['adc_bits']
    adc_levels_acc_len = c.config['adc_levels_acc_len']
    x_engines_per_fpga = c.config['x_per_fpga']

    if num_bits != 4:
        print 'This script is only written to work with 4 bit quantised values.'
        raise KeyboardInterrupt
    
    print 'Grabbing data off snap block...',
    #for x in range(c.config['n_xaui_ports_per_ffpga']):
    dataOffset = offset * num_bits * 2 * 2 / 64 * packet_len
    bram_dmp = c.fsnap_all(snapName, brams, man_trig = False, wait_period = 3, offset = dataOffset)
    print 'done.'

    print 'Unpacking bram out-of-band contents...',
    sys.stdout.flush()
    bram_oob = dict()

    for f, srv in enumerate(c.fsrvs):
        if len(bram_dmp[brams[2]][f])<=4:
            print '\n   No data for F engine %s.' % srv
            bram_oob[f] = {}
        else:
            if opts.verbose:
                print '\n   Got %i values from %s.' % (len(bram_dmp['bram_oob'][f]) / 4, srv)
            bram_oob[f] = {'raw': struct.unpack('>%iL' % (len(bram_dmp['bram_oob'][f]) / 4), bram_dmp['bram_oob'][f])}
            bram_oob[f].update({'linkdn': [bool(i & (2**linkdn_bit)) for i in bram_oob[f]['raw']]})
            bram_oob[f].update({'mrst': [bool(i & (2**mrst_bit)) for i in bram_oob[f]['raw']]})
            bram_oob[f].update({'adc': [bool(i & (2**adc_bit)) for i in bram_oob[f]['raw']]})
            bram_oob[f].update({'eof': [bool(i & (2**eof_bit)) for i in bram_oob[f]['raw']]})
            bram_oob[f].update({'sync': [bool(i & (2**sync_bit)) for i in bram_oob[f]['raw']]})
            bram_oob[f].update({'hdr': [bool(i & (2**hdr_bit)) for i in bram_oob[f]['raw']]})
    print 'done.'

    # run through the packets and collect data
    print 'Analysing packets...',
    skip_indices = []
    for f, srv in enumerate(c.fsrvs):
        collectedData[srv] = {}
        collectedData[srv]['antennas'] = {}
        collectedData[srv]['totalPackets'] = 0
        collectedData[srv]['malformedPackets'] = 0
        pkt_hdr_idx = -1
        oobLength = len(bram_dmp['bram_oob'][f]) / 4 # in 32-bit words
        # loop through the data we received from this F-engine
        for i in range(0, oobLength):
            if opts.verbose:
                pkt_64bit = struct.unpack('>Q',bram_dmp['bram_msb'][f][(4 * i) : (4 * i) + 4] + bram_dmp['bram_lsb'][f][(4 * i) : (4 * i) + 4])[0]
                print '[%s @ %4i]: %016X' % (srv, i, pkt_64bit),
                if bram_oob[f]['eof'][i]: print '[EOF]',
                if bram_oob[f]['linkdn'][i]: print '[LINK DOWN]',
                if bram_oob[f]['mrst'][i]: print '[MRST]',
                if bram_oob[f]['adc'][i]: print '[ADC_UPDATE]',
                if bram_oob[f]['sync'][i]: print '[SYNC]',
                if bram_oob[f]['hdr'][i]: print '[HDR]',
                print '' 
            # link down?
            if bram_oob[f]['linkdn'][i]:
                print '[%s] LINK DOWN AT %i' % (srv, i)
            # is this a header?
            elif bram_oob[f]['hdr'][i]:
                pkt_hdr_idx = i
                # skip_indices records positions in table which are ADC updates and should not be counted towards standard data.
                skip_indices = []
            elif bram_oob[f]['adc'][i]:
                print "(%s,%i,%i) - got a legacy ADC amplitude update. This shouldn't happen in modern designs. I think you connected an old (or a faulty!) F engine." % (srv, f, i)
                skip_indices.append(i)
            elif bram_oob[f]['eof'][i]:
                # skip the first packet entry which has no header (snap block triggered on sync)
                if pkt_hdr_idx < 0:
                    continue
                # else unpack the data and check it
                pkt_len = i - pkt_hdr_idx + 1
                feng_unpkd_pkt = feng_unpack(f, pkt_hdr_idx, pkt_len, skip_indices)
                # packet_len is length of data, not including header
                if (pkt_len - len(skip_indices)) != (packet_len + 1):
                    print '%s - MALFORMED PACKET! of length %i starting at index %i' % (srv, pkt_len - len(skip_indices), i)
                    print 'len of skip_indices: %i (%s)' % len(skip_indices), skip_indices
                    collectedData[srv]['malformedPackets'] += 1
                # add the antenna number to the report
                antennaKey = feng_unpkd_pkt['pkt_ant']
                if not collectedData[srv]['antennas'].has_key(antennaKey):
                    collectedData[srv]['antennas'][antennaKey] = {}
                    collectedData[srv]['antennas'][antennaKey]["count"] = 1
                    collectedData[srv]['antennas'][antennaKey]["channels"] = {}
                    collectedData[srv]['antennas'][antennaKey]["mismatchErrors"] = 0
                    collectedData[srv]['antennas'][antennaKey]["jumpErrors"] = 0
                    collectedData[srv]['antennas'][antennaKey]["lastChannel"] = -1
                else:
                    collectedData[srv]['antennas'][antennaKey]["count"] += 1
                # what frequency was include in this packet? what did the data contain?
                frequencyKey = feng_unpkd_pkt['pkt_freq']
                # did that jump correctly?
                if collectedData[srv]['antennas'][antennaKey]["lastChannel"] != -1:
                    channelJump = n_chans / (len(c.xsrvs) * x_engines_per_fpga)
                    jumpTo = (collectedData[srv]['antennas'][antennaKey]["lastChannel"] + channelJump)
                    if jumpTo >= n_chans: jumpTo -= (n_chans - 1)
                    if frequencyKey != jumpTo:
                        if opts.verbose:
                            print "Error: F-engine(%s) antenna(%i) - freq channel jumped incorrectly from %i to %i, should have been to %i." % (srv,\
                            antennaKey,\
                            collectedData[srv]['antennas'][antennaKey]["lastChannel"],\
                            frequencyKey,\
                            jumpTo)
                        collectedData[srv]['antennas'][antennaKey]["jumpErrors"] += 1
                collectedData[srv]['antennas'][antennaKey]["lastChannel"] = frequencyKey
                # check the freq channel data
                if not collectedData[srv]['antennas'][antennaKey]["channels"].has_key(frequencyKey):
                    collectedData[srv]['antennas'][antennaKey]["channels"][frequencyKey] = {}
                    collectedData[srv]['antennas'][antennaKey]["channels"][frequencyKey]['count'] = 1
                    collectedData[srv]['antennas'][antennaKey]["channels"][frequencyKey]['dataTotal'] = feng_unpkd_pkt['dataTotal']
                    collectedData[srv]['antennas'][antennaKey]["channels"][frequencyKey]['dataCount'] = feng_unpkd_pkt['dataCount']
                    collectedData[srv]['antennas'][antennaKey]["channels"][frequencyKey]['mismatchErrors'] = feng_unpkd_pkt['mismatchErrors']
                else:
                    collectedData[srv]['antennas'][antennaKey]["channels"][frequencyKey]['count'] += 1
                    collectedData[srv]['antennas'][antennaKey]["channels"][frequencyKey]['dataTotal'] += feng_unpkd_pkt['dataTotal']
                    collectedData[srv]['antennas'][antennaKey]["channels"][frequencyKey]['dataCount'] += feng_unpkd_pkt['dataCount']
                    collectedData[srv]['antennas'][antennaKey]["channels"][frequencyKey]['mismatchErrors'] += feng_unpkd_pkt['mismatchErrors']
                collectedData[srv]['antennas'][antennaKey]["mismatchErrors"] += feng_unpkd_pkt['mismatchErrors']
                # increment the packet counter
                collectedData[srv]['totalPackets'] += 1
                    
    print "done."
    
    # show a quick summary of the results
    for fengine in collectedData:
        print "\nF-engine %s - data in %i packets from %i antennas:" % (fengine, collectedData[srv]['totalPackets'], len(collectedData[fengine]['antennas']))
        for antenna in collectedData[fengine]['antennas']:
            numChannels = len(collectedData[fengine]['antennas'][antenna]['channels'])
            print "\tAntenna %i - data in %i channels, %i mismatch errors, %i jump errors." % (antenna, numChannels,\
            collectedData[fengine]['antennas'][antenna]["mismatchErrors"],\
            collectedData[srv]['antennas'][antennaKey]["jumpErrors"])
            if ((collectedData[fengine]['antennas'][antenna]["mismatchErrors"] > 0) or (collectedData[srv]['antennas'][antennaKey]["jumpErrors"] > 0)) and not opts.verbose:
                print "Errors were detected, please run with -v to see verbose output. Verbose output can be large and is best viewed in a file."

except KeyboardInterrupt:
    exit_clean()
except:
    exit_fail()

exit_clean()

# end
