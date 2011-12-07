"""Module for performing various katadc functions from software"""
import numpy,struct,time

WR = 0x0 << 0
RD = 0x1 << 0
START = 0x1 << 1
STOP = 0x1 << 2
LOCK = 0x1 << 3

IIC_RD = 0x1
IIC_WR = 0x0

def iic_write_register(fpga, katadc_n, dev_addr, reg_addr, reg_value):
    """fpga is an FpgaClient object, katadc_n is the adc number (0,1)"""
    if not katadc_n in [0,1]: raise RuntimeError("katadc_n must be 0 or 1. Please select your ZDok port.")
    iic_controller='iic_adc%i'%katadc_n
    #print 'Trying to write %x to %s at dev_addr %x, reg_addr %x.'%(reg_value,iic_controller,dev_addr,reg_addr)
    # Block Fifo
    fpga.blindwrite(iic_controller,'%c%c%c%c'%(0x0,0x00,0x00,0x01), offset=12)
    # Write IIC control byte
    fpga.blindwrite(iic_controller,'%c%c%c%c'%(0x0,0x00, WR | START | LOCK, (dev_addr << 1) | IIC_WR), offset=0x0)
    # Write IIC register address
    fpga.blindwrite(iic_controller,'%c%c%c%c'%(0x0,0x00, WR | LOCK, reg_addr), offset=0x0)
    # Write IIC register value
    fpga.blindwrite(iic_controller,'%c%c%c%c'%(0x0,0x00, WR | STOP, reg_value), offset=0x0)
    # Unblock Fifo
    fpga.blindwrite(iic_controller,struct.pack('>4B',0,0,0,0), offset=12)

def iic_read_register(fpga,katadc_n, dev_addr, reg_addr):
    "reads from an arbitrary I2C address. fpga is an FpgaClient object and katadc_n is the adc number (0,1)."
    if not katadc_n in [0,1]: raise RuntimeError("katadc_n must be 0 or 1. Please select your ZDok port.")
    iic_controller='iic_adc%i'%katadc_n
    # Block Fifo
    fpga.blindwrite(iic_controller,'%c%c%c%c'%(0x0,0x00,0x00,0x01), offset=12)
    # Write IIC control byte
    fpga.blindwrite(iic_controller,'%c%c%c%c'%(0x0,0x00, WR | START | LOCK, (dev_addr << 1) | IIC_WR), offset=0x0)
    # Write IIC register address
    fpga.blindwrite(iic_controller,'%c%c%c%c'%(0x0,0x00, WR | LOCK, reg_addr), offset=0x0)
    # Send repeated START
    fpga.blindwrite(iic_controller,'%c%c%c%c'%(0x0,0x00, WR | START | LOCK, (dev_addr << 1) | IIC_RD), offset=0x0)
    # Fetch IIC register value
    fpga.blindwrite(iic_controller,'%c%c%c%c'%(0x0,0x00, RD | STOP, 0), offset=0x0)
    # Unblock Fifo
    fpga.blindwrite(iic_controller,'%c%c%c%c'%(0x0,0x00,0x00,0x00), offset=12)
    time.sleep(0.1)
    return struct.unpack('>BBBB',fpga.read(iic_controller,4,4))[3]

def _eeprom_read(fpga,katadc_n,n_bytes,offset=0):
    "Reads an arbitrary number of bytes from the I2C EEPROM. fpga is an FpgaClient object and katadc_n is the adc number (0,1)."
    if not katadc_n in [0,1]: raise RuntimeError("katadc_n must be 0 or 1. Please select your ZDok port.")
    iic_controller='iic_adc%i'%katadc_n
    reg_addr=offset
    dev_addr=0x51
    n_bytes_remaining=n_bytes
    rv=[]
    #flush the fifos:
    fpga.blindwrite(iic_controller,'%c%c%c%c'%(0xff,0xff,0xff,0xff),offset=0x8)
    #break n_bytes into 32-byte chunks (max fifo length):
    while n_bytes_remaining > 0:
        # Block Fifo
        fpga.blindwrite(iic_controller,'%c%c%c%c'%(0x0,0x00,0x00,0x01), offset=12)
        # Write IIC control byte
        fpga.blindwrite(iic_controller,'%c%c%c%c'%(0x0,0x00, WR | START | LOCK, (dev_addr << 1) | IIC_WR), offset=0x0)
        # Write IIC register address
        fpga.blindwrite(iic_controller,'%c%c%c%c'%(0x0,0x00, WR | LOCK, reg_addr+len(rv)), offset=0x0)
        # Send repeated START
        fpga.blindwrite(iic_controller,'%c%c%c%c'%(0x0,0x00, WR | START | LOCK, (dev_addr << 1) | IIC_RD), offset=0x0)
        # Fetch IIC register value
        for i in range(min(31,n_bytes_remaining-1)):
            fpga.blindwrite(iic_controller,'%c%c%c%c'%(0x0,0x00, RD, 0), offset=0x0)
            #print '%4X'%struct.unpack('>L',fpga.read(iic_controller,4,0x8))
        fpga.blindwrite(iic_controller,'%c%c%c%c'%(0x0,0x00, RD | STOP, 0), offset=0x0)
        #check for OP buffer overflow:
        #   Bit[0] RXFIFO empty flag 
        #   Bit[1] RXFIFO full flag 
        #   Bit[2] RXFIFO overflow error latch 
        #   Bit[4] OPFIFO empty flag 
        #   Bit[5] OPFIFO full flag 
        #   Bit[6] OPFIFO overflow error latch 
        #   Bit[8] NACK on write error latch
        if bool(struct.unpack('>L',fpga.read(iic_controller,4,0x8))[0]&int('1100110',2)): 
            #fpga.blindwrite(iic_controller,'%c%c%c%c'%(0xff,0xff,0xff,0xff),offset=0x8)
            raise RuntimeError("Sorry, you requested too many bytes and the IIC controller's buffer overflowed.")
        # Unblock Fifo
        fpga.blindwrite(iic_controller,'%c%c%c%c'%(0x0,0x00,0x00,0x00), offset=12)
        for i in range(min(32,n_bytes_remaining)):
            rv.append(fpga.read(iic_controller,4,4)[3])
        n_bytes_remaining -= min(32,n_bytes_remaining)
        #print 'got %i bytes, remaining: %i bytes'%(len(rv),n_bytes_remaining)
    return ''.join(rv)

#NOT WORKING:
#def iic_write(fpga,katadc_n, dev_addr, start_addr, raw_data):
#    "Writes an arbitrary string to an arbitrary IIC device. fpga is an FpgaClient object and katadc_n is the adc number (0,1)."
#    if not katadc_n in [0,1]: raise RuntimeError("katadc_n must be 0 or 1. Please select your ZDok port.")
#    iic_controller='iic_adc%i'%katadc_n
#    # Block Fifo
#    fpga.blindwrite(iic_controller,'%c%c%c%c'%(0x0,0x00,0x00,0x01), offset=12)
#    for n,c in enumerate(raw_data):
#        # Write IIC control byte
#        fpga.blindwrite(iic_controller,'%c%c%c%c'%(0x0,0x00, WR | START | LOCK, (dev_addr << 1) | IIC_WR), offset=0x0)
#        # Write IIC register address
#        fpga.blindwrite(iic_controller,'%c%c%c%c'%(0x0,0x00, WR | LOCK, n+start_addr), offset=0x0)
#        # Write IIC register value
#        fpga.blindwrite(iic_controller,'%c%c%c%c'%(0x0,0x00, WR | STOP, c), offset=0x0)
#    #check for OP buffer overflow:
#    #   Bit[0] RXFIFO empty flag 
#    #   Bit[1] RXFIFO full flag 
#    #   Bit[2] RXFIFO overflow error latch 
#    #   Bit[4] OPFIFO empty flag 
#    #   Bit[5] OPFIFO full flag 
#    #   Bit[6] OPFIFO overflow error latch 
#    #   Bit[8] NACK on write error latch
#    if bool(ord(fpga.read(iic_controller,4,12)[0])&0b10000): raise RuntimeError("Sorry, you requested too many bytes and the IIC controller's buffer overflowed.")
#    # Unblock Fifo
#    fpga.blindwrite(iic_controller,'%c%c%c%c'%(0x0,0x00,0x00,0x00), offset=12)


def get_ambient_temp(fpga,katadc_n):
    """Returns ambient board temp in degC."""
    if not katadc_n in [0,1]: raise RuntimeError("katadc_n must be 0 or 1. Please select your ZDok port.")
    hb=iic_read_register(fpga,katadc_n,0x4C,0x00)
    lb=iic_read_register(fpga,katadc_n,0x4C,0x10)
    return numpy.int8(hb)+numpy.uint8(lb)/float(256)

def get_adc_temp(fpga,katadc_n):
    """Returns temp in degC of ADC IC."""
    if not katadc_n in [0,1]: raise RuntimeError("katadc_n must be 0 or 1. Please select your ZDok port.")
    hb=iic_read_register(fpga,katadc_n,0x4C,0x01)
    lb=iic_read_register(fpga,katadc_n,0x4C,0x11)
    return numpy.int8(hb)+numpy.uint8(lb)/float(256)

def _eeprom_write(fpga,katadc_n,eeprom_bin):
    """Generic write of raw bytestream into the IIC EEPROM."""
    if not katadc_n in [0,1]: raise RuntimeError("katadc_n must be 0 or 1. Please select your ZDok port.")
    for n,c in enumerate(eeprom_bin):
       iic_write_register(fpga,katadc_n,0x51,n,c) 
        
def eeprom_details_get(fpga,katadc_n,fetch_cal=False):
    """Retrieves data from the EEPROM and unpacks it. Returns a dictionary."""
    if not katadc_n in [0,1]: raise RuntimeError("katadc_n must be 0 or 1. Please select your ZDok port.")
    if fetch_cal==True: eeprom_dump=_eeprom_read(fpga,katadc_n,256)
    else: eeprom_dump=_eeprom_read(fpga,katadc_n,16)
    rv={}
    #for b in range(16):
    #    eeprom_dump.append(iic_read_register(fpga,katadc_n,0x51,b))
    rv['serial_number']   = struct.unpack('>H',eeprom_dump[0:2])[0]
    rv['pcb_rev']         = struct.unpack('>H',eeprom_dump[2:4])[0]
    rv['adc_ic_id']       = struct.unpack('>H',eeprom_dump[4:6])[0]
    rv['rf_fe_id']        = struct.unpack('>H',eeprom_dump[6:8])[0]
    rv['reserved']        = struct.unpack('>4H',eeprom_dump[8:16])
    if fetch_cal==True:
        rv['cal_data'] = struct.unpack('>%iH'%((256-16)/2),eeprom_dump[16:])
    return rv

def eeprom_details_set(fpga,katadc_n,serial_number,pcb_rev,adc_ic_id,rf_fe_id,cal_data=''):
    """Stores the ADC details in the onboard EEPROM. Remember to set the onboard write-enable jumper."""
    if not katadc_n in [0,1]: raise RuntimeError("katadc_n must be 0 or 1. Please select your ZDok port.")
    raw_str=struct.pack('>8H',serial_number,pcb_rev,adc_ic_id,rf_fe_id,0,0,0,0)+str(cal_data)
    _eeprom_write(fpga,katadc_n,raw_str)
    

def spi_write_register(fpga,katadc_n,reg_addr,reg_value):
    """Writes to a register from the ADC via SPI (two bytes at a time)."""
    if not katadc_n in [0,1]: raise RuntimeError("katadc_n must be 0 or 1. Please select your ZDok port.")
    #adc 1 is at offset 8
    #reg_addr is only 4 bits!
    #these addresses are WRITE-ONLY
    fpga.blindwrite('kat_adc_controller',struct.pack('>H2B',reg_value,reg_addr,0x01), offset=0x4+katadc_n*(0x04))

def set_interleaved(fpga,katadc_n,input_sel,dlf=True):
    """fpga is an FpgaClient object, katadc_n is the adc number (0,1) input select is 'I' or 'Q'."""
    if not katadc_n in [0,1]: raise RuntimeError("katadc_n must be 0 or 1. Please select your ZDok port.")
    reset(fpga,katadc_n,reset=True)
    if input_sel == 'I':
        spi_write_register(fpga,katadc_n,0x9,0x23ff+(dlf<<10))
    elif input_sel == 'Q':
        spi_write_register(fpga,katadc_n,0x9,0x33ff+(dlf<<10))
    else:
        raise RuntimeError("Invalid input selection. Must be 'I' or 'Q'.")
    reset(fpga,katadc_n,reset=False)

def set_noninterleaved(fpga,katadc_n,dlf=True):
    if not katadc_n in [0,1]: raise RuntimeError("katadc_n must be 0 or 1. Please select your ZDok port.")
    reset(fpga,katadc_n,reset=True)
    spi_write_register(fpga,katadc_n,0x9,0x03ff+(dlf<<10))
    reset(fpga,katadc_n,reset=False)
    #fpga.blindwrite('kat_adc_controller','%c%c%c%c'%(0x03,0xff,0x09,0x01), offset=0x4+katadc_n*(0x04))

def reset(fpga,katadc_n,reset=False):
    """Reset the ADC and FPGA DCM. Set "reset" to True to hold in reset, False to clear."""
    #Reset pulse: writing '1' to bit 0 resets ADC0; writing '1' to bit 1 resets ADC1 (at offset 0x3).
    #Reset level: writing '1' to bit 4/5 holds ADC0/1 and associated DCM in reset (at byte offset 0x3).
    if not katadc_n in [0,1]: raise RuntimeError("katadc_n must be 0 or 1. Please select your ZDok port.")
    fpga.blindwrite('kat_adc_controller','%c%c%c%c'%(0x0,0x00,0x00,reset*(0x10<<katadc_n)))

def cal_now(fpga,katadc_n):
    """Triggers adc's self-calibrate function"""
    #Addr 0h, bit 15.
    if not katadc_n in [0,1]: raise RuntimeError("katadc_n must be 0 or 1. Please select your ZDok port.")
    spi_write_register(fpga,katadc_n,0x0,0xffff)
    time.sleep(1)
    spi_write_register(fpga,katadc_n,0x0,0xefff)

def fsr_adj(fpga,katadc_n,input_sel,fsr_val=700):
    """Adjusts the on-chip full scale range for the given input (channel) in ('I','Q') in mV. Valid range is 560-840mV."""
    #fsr_val is integer in range(0,512) representing 560mVp-p to 840mVp-p. POR default: 700mV (0x100)."""
    #addr 0x3 and 0xB, bits 7-15.
    if input_sel == 'I': pol=0
    elif input_sel == 'Q': pol=1
    else: raise RuntimeError("Invalid input selection. Must be 'I' or 'Q'.")
    if fsr_val<560 or fsr_val>840: raise RuntimeError("Invalid fsr value of %i. Must be in range(560,840)."%fsr_val)
    fsr_bin=int(float((fsr_val-560)*512)/(840-560))
    spi_write_register(fpga,katadc_n,0x3 if pol==0 else 0xb,0xef+(fsr_bin<<7))


def offset_adj(fpga,katadc_n,input_sel,offset=0):
    """Adjusts the on-chip DC offset for the given input (channel) in ('I','Q'). Offset is in range [0:45mV:0.176mV]"""
    #addr 0x2 and 0xA, bits 7-15.
    if input_sel == 'I': pol=0
    elif input_sel == 'Q': pol=1
    else: raise RuntimeError("Invalid input selection. Must be 'I' or 'Q'.")
    if offset<-45 or offset>45: raise RuntimeError("Invalid offset value of %i. Must be in range [0:45:0.176mV]."%offset)
    offset_bin=abs(int(float(offset*256)/45))
    sign=0 if offset<0 else 1
    #sign=1 if offset<0 else 0
    spi_write_register(fpga,katadc_n,0x2 if pol==0 else 0xA,0xef+(sign<<7)+(offset_bin<<8))

#NOT TESTED FROM HERE ONWARDS:

#ext control register -- set using interleaved/non-interleaved mode
#def test_pattern(fpga,katadc_n,enabled=False):
#    """Enables or disables the test pattern generator."""
#    #addr 0x9, bit 15

def rf_fe_set(fpga,katadc_n,input_sel,gain=0,enabled=True):
    """Gain is in dB.""" # MSB = switch, load_enable (gain), 6 bits = gain
    if input_sel == 'I': pol=0
    elif input_sel == 'Q': pol=1
    else: raise RuntimeError("Invalid input selection. Must be 'I' or 'Q'.")
    if gain<-11.5: raise RuntimeError('Valid gain range is -11.5dB to +20dB. %idB is invalid.'%gain)
    iic_write_register(fpga,katadc_n,0x20+pol,2,0x40+(enabled<<7)+int((gain*2)+23))

def rf_fe_get(fpga,katadc_n,input_sel):
    """Fetches and decodes the RF frontend on the KATADCs."""
    #P0-5 Atten setting
    #P06 Atten latch enable
    #P07 terminate (low = terminated. hight=rf input select)
    #P10 cal run (for ADC) on 0x20
    #P10 cal line (for ADC) on 0x21
    if input_sel == 'I': pol=0
    elif input_sel == 'Q': pol=1
    else: raise RuntimeError("Invalid input selection. Must be 'I' or 'Q'.")
    bitmap=iic_read_register(fpga,katadc_n,0x20+pol,2)
    return {'enabled': bool(bitmap>>7),
            'gain': -11.5+(bitmap&0x3f)/2.} 
 
def gpio_header_get(fpga,katadc_n):
    for pol in range(2):
        print "IIC GPIO expansion on ADC%i's %s input:"%(katadc_n,{0:'Q',1:'I'}[pol])
        for i in range(0,8):
            print '\t%x: %x'%(i,iic_read_register(fpga, 'iic_adc%i'%katadc_n, 0x20+pol, i))

def gpio_header_set(fpga,katadc_n,input_sel):
    if input_sel == 'I': pol=0
    elif input_sel == 'Q': pol=1
    else: raise RuntimeError("Invalid input selection. Must be 'I' or 'Q'.")
    # registers 0 and 1 are input
    #P0-5 Atten setting
    #P06 Atten latch enable
    #P07 terminate (low = terminated. hight=rf input select)
    #P10 cal run (for ADC) on 0x20
    #P10 cal line (for ADC) on 0x21
    iic_write_register(fpga, 'iic_adc%i'%adc, 0x20+pol, 2, 0xC0 + gain) # MSB = switch, load_enable (gain), 6 bits = gain
    iic_write_register(fpga, 'iic_adc%i'%adc, 0x20+pol, 3, 0xFF) # write stuff in here for later comparison
    iic_write_register(fpga, 'iic_adc%i'%adc, 0x20+pol, 4, 0x00) # output inversion register for register 2 (here not inverted)
    iic_write_register(fpga, 'iic_adc%i'%adc, 0x20+pol, 5, 0x00) # output inversion register for register 3
    iic_write_register(fpga, 'iic_adc%i'%adc, 0x20+pol, 6, 0x00) # output enable (active low) for byte 2
    iic_write_register(fpga, 'iic_adc%i'%adc, 0x20+pol, 7, 0xFF) # output enable (active low) for byte 3
"""
To Access Local (Ambient) Temperature on TMP421 (IIC ADDR 0x4C, REGISTER ADDR 0x0)
mw d0040000 298; # START, WRITE, DATA=0x98 (4C << 1 + 0x0(IIC WRITE)) mw d0040000 000; # WRITE, DATA=0x00 (Register Address) mw d0040000 299; # START(REPEATED), WRITE, DATA=0x99 (4C << 1 + 0x1(IIC READ)) mw d0040000 500; # STOP, READ md d0040004 1; # Read Data from RXFIFO
mw d0040000 298; mw d0040000 000; mw d0040000 299; mw d0040000 500; md d0040004 1;

To Access ADC Temperature on TMP421 (IIC ADDR 0x4C, REGISTER ADDR 0x1)
    mw d0040000 298; # START, WRITE, DATA=0x98 (4C << 1 + 0x0(IIC WRITE)) 
    mw d0040000 001; # WRITE, DATA=0x01 (Register Address) 
    mw d0040000 299; # START(REPEATED), WRITE, DATA=0x99 (4C << 1 + 0x1(IIC READ)) 
    mw d0040000 500; # STOP, READ 
    md d0040004 1; # Read Data from RXFIFO

To Write EEPROM DATA (IIC ADDR 0x51, ADDR 0x4, DATA 0xDEADBEEF)
    mw d0040000 2A2; # START, WRITE, DATA=0xA2 (0x51 << 1 + 0x0(IIC WRITE)) 
    mw d0040000 004; # WRITE, DATA=0x04 (Register Address) 
    mw d0040000 0de; # WRITE, DATA=0xde 
    mw d0040000 0ad; # WRITE, DATA=0xad
    mw d0040000 0be; # WRITE, DATA=0xbe 
    mw d0040000 4ef; # WRITE, DATA=0xef

To READ EEPROM DATA (IIC ADDR 0x51, ADDR 0x4)
    (IIC ADDR 0x51, ADDR 0x4)
    mw d0040000 2A2; # START, WRITE, DATA=0xA2 (0x51 << 1 + 0x0(IIC WRITE)) 
    mw d0040000 004; # WRITE, DATA=0x04 (Register Address) 
    mw d0040000 2A3; # START(REP),WRITE, DATA=0xA2 (0x51 << 1 + 0x1(IIC READ)) 
    mw d0040000 100; # READ 
    mw d0040000 100; # READ 
    mw d0040000 100; # READ 
    mw d0040000 500; # STOP, READ 
    md d0040004 1;  
    md d0040004 1; 
    md d0040004 1; 
    md d0040004 1;
"""
