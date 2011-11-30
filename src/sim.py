"""A module for generating simulation data for a casper_n correlator.  This
is used to verify the data-flow through the packetization and readout system.

Author: Aaron Parsons
Modified: Jason Manley
Revisions:
2010-07-30  JRM Merged with casper-correlator-0.1.1
2008-02-08  JRM Neatening, removing redundant interfaces
2007-10-29  JRM added addr_decode and addr_encode functions

"""

import struct, time, math

def xeng_encode(freq,n_xeng=8, n_chans=2048,adc_clk=600,ddc_decimation=4,ddc_mix_freq=0.25):
    bandwidth = adc_clk/ddc_decimation
    center_freq = adc_clk*ddc_mix_freq
    start_freq = center_freq - bandwidth/2
    im = freq - start_freq
    chan = int((float(im)/bandwidth * n_chans))
    out = dict()
    if (chan >= (n_chans/2)):
        chan = chan - (n_chans/2)
    else:
        chan = chan + (n_chans/2)
    out['chan'] = chan
    out['x_eng'] = int(chan % n_xeng)
    out['group'] = int(chan/n_xeng)
    return out

def xeng_decode(x_eng,chan,n_xeng=8, n_chans=2048,adc_clk=600,ddc_decimation=4,ddc_mix_freq=0.25):    
    bandwidth = float(adc_clk)/ddc_decimation
    chan_bw = bandwidth/n_chans
    print chan_bw
    center_freq = float(adc_clk)*ddc_mix_freq
    start_freq = center_freq - bandwidth/2
    freq_offset = x_eng * chan_bw
    freq = (chan*n_xeng)*chan_bw
    freq = freq + freq_offset
    if freq >= bandwidth/2:
        freq += start_freq
    else:
        freq += center_freq
    return freq

def addr_decode(address,vector_len=18432):
    """Calculates which bank,row,rank,column and block a particular 
    address maps to. Good for BEE2 1GB DRAMs."""
    if vector_len > 512:
        bit_shift = int(math.ceil(math.log(float(vector_len)/512.0,2)))
    else:
        bit_shift = 1
    #print bit_shift
    #address = (2**20) + (2**29) +(2**13)
    out = dict()
    out['bank'] = (address & ((2**28) + (2**29)))>>28
    out['row'] =  (address & (  ((2**28)-1) - ((2**14)-1)  ))>>14
    out['rank'] = (address & (2**13))>>13
    out['col'] = (address & (  ((2**13)-1) - ((2**3)-1)  ))>>3
    out['block'] = out['bank'] + ((out['row']>>bit_shift) <<2) + (out['rank']<<10)
    #print bank,row,rank,col,block
    return out

def addr_encode(int_num=0,offset=0,vector_len=18432):
    """Calculates the address location in DRAM of an integration.
    int_num: the number of the integration you're looking for.
    offset:
    vector_len: Programmed length of the DRAM_VACC."""
    if vector_len > 512:
        bit_shift = int(math.ceil(math.log(float(vector_len)/512.0,2)))
    else:
        bit_shift = 1

    block_row_bits = 14-bit_shift

    bank = int_num & 3
    block_row = (int_num >> 2) & ((2**block_row_bits)-1) 
    rank = (int_num>>(block_row_bits + 2))

    column = offset & ((2**9)-1)
    row_offset = (offset >> 9)

    address = (column << 4) + (rank<<13) + (row_offset << 14) + (block_row<<(14 + bit_shift)) + (bank << 28)
    
    #print bank,bit_shift, block_row, block_row_bits, rank, column, row_offset
    return address


def ij2bl(i, j):
    """Convert i, j baseline notation (counting from 0) to Miriad's baseline
    notation (counting from 1, a 16 bit number)."""
    return ((i+1) << 8) | (j+1)

def bl2ij(bl):
    """Convert from Miriad's baseline notation (counting from 1, a 16 bit 
    number) to i, j baseline notation (counting from 0)."""
    return ((bl >> 8) & 255) - 1, (bl & 255) - 1

def get_bl_order(n_ants):
    """Return the order of baseline data output by a CASPER correlator
    X engine."""
    order1, order2 = [], []
    for i in range(n_ants):
        for j in range(int(n_ants/2),-1,-1):
            k = (i-j) % n_ants
            if i >= k: order1.append((k, i))
            else: order2.append((i, k))
    order2 = [o for o in order2 if o not in order1]
    return tuple([o for o in order1 + order2])

def get_bl_order_sp(n_inputs):
    """Return the order of baseline data output by a dual-polarisation 
        CASPER correlator X engine when remapped as a single pol system."""
    dp_bls=get_bl_order(n_inputs/2)
    rv=[]
    for bl in dp_bls:
        rv.append(tuple((bl[0]*2,bl[1]*2)))
        rv.append(tuple((bl[0]*2+1,bl[1]*2+1)))
        rv.append(tuple((bl[0]*2,bl[1]*2+1)))
        rv.append(tuple((bl[0]*2+1,bl[1]*2)))
    return rv

def encode_32bit(i, j, stokes, r_i, chan):
    """Encode baseline, stokes, real/imaginary, and frequency info as 
    a 32 bit unsigned integer."""
    return (r_i << 31) | (stokes << 29) | (chan << 16) | ij2bl(i,j)

def decode_32bit(data):
    """Decode baseline, stokes, real/imaginary, and frequency info from
    a 32 bit number."""
    i,j = bl2ij(data & (2**16-1))
    freq = (data >> 16) & (2**13-1)
    stokes = (data >> 29) & 3
    r_i = (data >> 31) & 1
    return i, j , stokes, r_i, freq

class XEngine:
    def __init__(self, nant=8, nchan=2048, npol=4, id=0, pktlen=2048,
            engine_id=0, instance_id=0, instrument_id=3, start_t=0, intlen=1):
        self.pktlen = pktlen
        self.engine_id = engine_id
        self.instance_id = instance_id
        self.instrument_id = instrument_id
        self.t = start_t
        self.intlen = intlen
        self.data = []
        data = [encode_32bit(i,j,p, r_i, ch) \
            for ch in range(engine_id,nchan,nant) \
            for (i,j) in get_bl_order(nant) \
            for p in range(npol) \
            for r_i in [0,1] \
        ]
        self.data = struct.pack('%dI' % len(data), *data)
    def init_pkt(self):
        pkt = CorrPacket()
        pkt.packet_len = self.pktlen
        pkt.packet_count = 1
        pkt.engine_id = self.engine_id
        pkt.instance_id = self.instance_id
        pkt.instrument_id = self.instrument_id
        pkt.currerr = 0
        return pkt
    def get_pkt_stream(self):
        c, L = 0, self.pktlen
        while True:
            pkt = self.init_pkt()
            pkt.heap_off = c * L
            noff = (c+1) * L
            pkt.timestamp = self.t
            d = self.data[pkt.heap_off:noff]
            pkt.set_data(d)
            pkt.packet_count = c
            yield pkt
            if noff >= len(self.data):
                c = 0
                self.t += self.intlen
            else: c += 1

#class CorrSimulator:
#    def __init__(self, xengines=None, nant=8, nchan=2048, npol=4):
#        if xengines is None: xengines = range(nant)
#        self.xeng = xengines
#        self.bls = get_bl_order(nant)
#        self.nchan = nchan
#        self.npol = npol
#        data = n.zeros((len(self.bls), nchan/nant, npol, 2), dtype=n.uint32)
#        for c,(i,j) in enumerate(self.bls): data[c,...] = ij2bl(i,j)
#        ch = n.arange(0, nchan, nant, dtype=n.uint32)
#        ch = n.left_shift(ch, 16)
#        ch.shape = (1,nchan/nant,1,1)
#        for c,pol in enumerate(range(npol)):
#            data[:,:,c,...] = n.bitwise_or(data[:,:,c,...], (pol << 29))
#        data[...,1] = n.bitwise_or(data[...,1], (1 << 31))
#        self.data = data
#    def get_pkt(self):
#        """Generate data for a casper_n correlator.  Each data
#        sample is encoded with the baseline, stokes, real/imag, frequency
#        that it represents."""
#        #while True:
#        #    data = self.data.copy()
#        #    for c in range(self.nchan/nant
#        data = []
#        # Loop through channels in X engine (spaced every n_ants channels)
#        for coarse_chan in range(n_chans/n_ants):
#            c = coarse_chan * n_ants + x_num
#            # Loop through baseline order out of X engine
#            for bl in bls:
#                # Loop through stokes parameters
#                for s in range(n_stokes):
#                    # Real and imaginary components
#                    for ri in (0, 1):
#                        data.append(encode_32bit(bl, s, ri, c))
#        fmt = '%s%dI' % (endian, len(data))
#        return struct.pack(fmt, *data)
#
#        
#
##class PacketSimulator:
##   def __init__(self, nant, nchan, npol):

