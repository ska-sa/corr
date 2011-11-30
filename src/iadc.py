"""Module for performing various iADC functions from software. 
Author: Jason Manley, using code segments from Hong Chen and David George."""
import numpy,struct,time

def spi_write_register(fpga,zdok_n,reg_addr,reg_value):
    """Writes to a register from the ADC via SPI (two bytes at a time)."""
    if not zdok_n in [0,1]: raise RuntimeError("zdok_n must be 0 or 1. Please select your ZDok port.")
    #adc 0 is at offset 4
    #adc 1 is at offset 8
    #these addresses are WRITE-ONLY
    fpga.blindwrite('iadc_controller',struct.pack('>H2B',reg_value,reg_addr,0x01), offset=0x4+zdok_n*(0x04))

def rst(fpga,zdok_n):
    """Reset the ADC and FPGA DCM. This will just pulse the reset lines."""
    #Reset pulse: writing '1' to bit 0 resets ADC0; writing '1' to bit 1 resets ADC1 (at offset 0x3).
    if not zdok_n in [0,1]: raise RuntimeError("zdok_n must be 0 or 1. Please select your ZDok port.")
    fpga.blindwrite('iadc_controller','%c%c%c%c'%(0x0,0x00,0x03,0x1<<zdok_n))

def set_mode(fpga,mode='SPI'):
    """Sets the MODE pin on the iADCs. mode='SPI' allows for software control (you need to set this before you an issue any other commands), else 'GW' for gateware autoconf else use ADC hardware defaults:
        * Dual channel I and Q activated 
        * One clock I 
        * 0 dB gain 
        * DMUX mode 1:1
        * DRDA I & Q = 0 ps 
        * ISA I & Q = 0 ps 
        * FiSDA Q = 0 ps 
        * Cal = 0 
        * Decimation test mode OFF 
        * Calibration setting OFF 
        * Data Ready = Fs/4"""
    if mode =='SPI':    fpga.blindwrite('iadc_controller','%c%c%c%c'%(0x0,0x00,0x03,0x00))
    elif mode =='GW':    fpga.blindwrite('iadc_controller','%c%c%c%c'%(0x0,0x00,0x30,0x00))
    else:    fpga.blindwrite('iadc_controller','%c%c%c%c'%(0x0,0x00,0x00,0x00))
    
#register 0x00:
# 0-1:  standby modes
# 2     Chip version test bit. Not implemented on A/B versions (C only). Ignore.
# 3     Demux mode (0= 1:1; 1=1:2)
# 4-5   Analogue input select (11 = indep, 10= input I, 00 = input Q)
# 6-7   Clk select (10 = clkI to both, 00 = clkI to I and clkIn to Q)
# 8     Decimation
# 9     Always zero
# 10-11 Calibration (01 = keep last value, 00=zero gain and DC offset, 11 = perform new calibration)
# 12-13 Control wait bit calibration (11 for >500MSps, 10 for 250-500MSps, 01 for 125-250MSps, 00 for <125Msps)
# 14    DMUX (0=Fs/4, 1=Fs/2)
# 15    NA

def configure(fpga,zdok_n,mode='indep',cal='new',clk_speed=800):
    """fpga is an FpgaClient object; 
        zdok_n is the adc number (0,1);
        mode in ('indep','inter_Q','inter_I');
        input select is 'I' or 'Q';
        Clk source will always be from clkI (compat with iADC v1.1 through v1.3);
        clk_speed is in MHz and is used for auto-phase calibration.
        cal in ('new','old','zero')"""
    if not zdok_n in [0,1]: raise RuntimeError("zdok_n must be 0 or 1. Please select your ZDok port.")
    clk_bits = 0 if clk_speed<125 else 1 if (clk_speed<250) else 2 if (clk_speed<500) else 3 
    cal_bits = 0 if cal=='zero' else 1 if cal=='old' else 3 #if cal=='new' else raise RuntimeError ('bad cal option')
    mode_bits = 0x2 if mode=='inter_I' else 0 if mode=='inter_Q' else 0xB
    spi_write_register(fpga,zdok_n,0x0,(1<<14)+(clk_bits<<12)+(cal_bits<<10)+(mode_bits<<4)+(1<<3)+(1<<2))
    rst(fpga,zdok_n)

def analogue_gain_adj(fpga,zdok_n,gain_I=0,gain_Q=0):
    """Adjusts the on-chip analogue gain for the two ADCs in dB. Valid range is -1.5 to +1.5 in steps of 0.011dB."""
    if gain_I>1.5 or gain_I<-1.5 or gain_Q<-1.5 or gain_Q>1.5: raise RuntimeError("Invalid gain setting. Valid range is -1.5 to +1.5dB")
    #bits_I= int(((gain_I+1.5)*256)/3.0)
    #bits_Q= int(((gain_Q+1.5)*256)/3.0)
    #spi_write_register(fpga,zdok_n,0x1,(bits_Q<<8) + (bits_I<<0))
    bits_I= abs(int(((gain_I)*127)/1.5))
    bits_Q= abs(int(((gain_Q)*127)/1.5))
    sign_I = 1 if gain_I<0 else 0
    sign_Q = 1 if gain_Q<0 else 0
    val=((sign_Q<<15) + (sign_I<<7) + (bits_Q<<8) + (bits_I<<0))
    print 'Writing %4x'%(val)
    spi_write_register(fpga,zdok_n,0x1,val)


#NOT TESTED from this point onwards...
def offset_adj(fpga,zdok_n,offset_I=0,offset_Q=0):
    """Adjusts the on-chip DC offset. Offset is in range [-31.75LSb:+31.75LSb:0.25LSb]. NOT TESTED. YMMV!"""
    if offset_I>31.75 or offset_I<-31.75 or offset_Q<-31.75 or offset_Q>31.75: raise RuntimeError("Invalid offset setting. Valid range is -31.75 to +31.75LSb")
    bits_I= abs(int(((offset_I)*127)/31.75))
    bits_Q= abs(int(((offset_Q)*127)/31.75))
    sign_I = 1 if offset_I>0 else 0
    sign_Q = 1 if offset_Q>0 else 0
    val=((sign_Q<<15) + (sign_I<<7) + (bits_Q<<8) + (bits_I<<0))
    print 'Writing %4x'%(val)
    spi_write_register(fpga,zdok_n,0x2,val)

def gain_adj(fpga,zdok_n,gain):
    """Adjusts the on-chip gain for the two ADCs in dB. Valid range is -0.315 to +0.315dB in steps of 0.011dB. NOT TESTED. YMMV!"""
    if gain<-0.315 or gain>0.315: raise RuntimeError("Invalid gain setting. Valid range is -1.5 to +1.5dB")
    bits= abs(int(((gain)*63)/0.315))
    sign = 1 if gain<0 else 0
    print 'Writing %4x'%((sign<<6) + (bits<<0))
    spi_write_register(fpga,zdok_n,0x3,(sign<<6) + (bits<<0))

def fisda_Q_adj(fpga,zdock_n,delay=0):
    """Adjusts the Fine Sampling Delay Adjustment (FiSDA) on channel Q. delay is in ps and has a valid range of -60 to +60ps in 4ps steps. NOT TESTED! YMMV!"""
    if delay<-60 or delay>60: raise RuntimeError("Invalid delay setting. Valid range is -60ps to +60ps.")
    bits= abs(int(((delay)*15)/60))
    sign = 1 if delay<0 else 0
    print 'Writing %4x'%((sign<<10) + (bits<<6))
    spi_write_register(fpga,zdok_n,0x7,(sign<<10) + (bits<<6))
    
