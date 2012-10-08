#! /usr/bin/env python
""" 
Selection of commonly-used correlator control functions. This is the top-level file used to communicate with correlators.

Author: Jason Manley
"""
"""
Revisions:
2012-06-015 JRM Object-wide spead itemgroup and transmitter.
2012-01-11: JRM Cleanup of SPEAD metadata to match new documentation.
2011-07-06: PVP New functions to read/write/pulse bitfields within registers. Remove a bit of duplicate code for doing that.
2011-06-23: JMR Moved all snapshot stuff into new file (snap.py)
2011-05-xx: JRM change ant,pol handling to be arbitrary strings.
                deprecated get_ant_location. Replaced by get_ant_str_location
                updates to adc_amplitudes_get
                added rf_level low warning
                spead metadata changes: antenna mapping and baseline ordering. no more cross-pol ordering.
                new functions: fr_delay_set_all to set all fringe and delay rates in one go. does check to ensure things loaded correctly.
2011-04-20: JRM Added xeng status call
                Mods to check_all 
                acc_time_set now resets counters (vaccs produce errors when resyncing)
2011-04-04: JRM Don't write to config file anymore
                Cleanup of RF frontend stuff
                get_adc_snapshot with trigger support
2011-02-11: JRM Issue SPEAD data descriptors for interleaved case.
2011-01-02: JRM Removed requirement for stats package (basic mode calc built-in).
                Bugfix to arm and check_feng_clks logic (waiting for half second).
2011-01-03: JRM Modified check_fpga_comms to limit random number 2**32.
2010-12-02  JRM Added half-second wait for feng clk check's PPS count
2010-11-26: JRM Added longterm ppc count check in feng clock check.
2010-11-22: JRM corr-0.6.0 now with support for fengines with 10gbe cores instead of xaui links.
                Mods to fr_delay calcs for fine delay.
                spead, pcnt and mcnt from time functions now account for wrapping counters.
2010-10-18: JRM initialise function added.
                Fix to SPEAD metadata issue when using iADCs.
2010-08-05: JRM acc_len_set -> acc_n_set. acc_let_set now in seconds.
2010-06-28  JRM Port to use ROACH based F and X engines.
                Changed naming convention for function calls.
2010-04-02  JCL Removed base_ant0 software register from Xengines, moved it to Fengines, and renamed it to use ibob_addr0 and ibob_data0.  
                New function write_ibob().
                Check for VACC errors.
2010-01-06  JRM Added gbe_out enable to X engine control register
2009-12-14  JRM Changed snap_x to expect two kinds of snap block, original simple kind, and new one with circular capture, which should have certain additional registers (wr_since_trig).
2009-12-10  JRM Started adding SPEAD stuff.
2009-12-01  JRM Added check for loopback mux sync to, and fixed bugs in, loopback_check_mcnt.
                Changed all "check" functions to just return true/false for global system health. Some have "verbose" option to print more detailed errors.
                Added loopback_mux_rst to xeng_ctrl
2009-11-06  JRM Bugfix snap_x offset triggering.
2009-11-04  JRM Added ibob_eq_x.
2009-10-29  JRM Bugfix snap_x.
2009-06-26  JRM UNDER CONSTRUCTION.
\n"""

import corr, time, sys, numpy, os, logging, katcp, struct, construct, socket, spead

DEFAULT_CONFIG='/etc/corr/default'

def statsmode(inlist):
    """Very rudimentarily calculates the mode of an input list. Only returns one value, the first mode. Can't deal with ties!"""
    value=inlist[0]
    count=inlist.count(value)
    for i in inlist:
        if inlist.count(i) > count:
            value = i 
            count = inlist.count(i)
    return value 

def ip2str(pkt_ip, verbose = False):
    """
    Returns a dot notation IPv4 address given a 32-bit number.
    """
    ip_4 = (pkt_ip & ((2**32) - (2**24))) >> 24
    ip_3 = (pkt_ip & ((2**24) - (2**16))) >> 16
    ip_2 = (pkt_ip & ((2**16) - (2**8)))  >> 8
    ip_1 = (pkt_ip & ((2**8)  - (2**0)))  >> 0
    ipstr = '%i.%i.%i.%i' % (ip_4, ip_3, ip_2, ip_1)
    if verbose:
        print 'IP(%i) decoded to:' % pkt_ip, ipstr
    return ipstr
    
def write_masked_register(device_list, bitstruct, names = None, **kwargs):
    """
    Modify arbitrary bitfields within a 32-bit register, given a list of devices that offer the write_int interface - should be KATCP FPGA devices.
    """
    # lazily let the read function check our arguments
    currentValues = read_masked_register(device_list, bitstruct, names, return_dict = False)
    wv = []
    pulse_keys = []
    for c in currentValues:
        for key in kwargs:
            if not c.__dict__.has_key(key):
                raise RuntimeError('Attempting to write key %s but it doesn\'t exist in bitfield.' % key)
            if kwargs[key] == 'pulse':
                if pulse_keys.count(key) == 0: pulse_keys.append(key)
            else:
                c.__dict__[key] = (not c.__dict__[key]) if (kwargs[key] == 'toggle') else kwargs[key]
        bitstring = bitstruct.build(c)
        unpacked = struct.unpack('>I', bitstring)
        wv.append(unpacked[0])
    for d, device in enumerate(device_list):
        device.write_int(c.register_name, wv[d])
    # now pulse any that were asked to be pulsed
    if len(pulse_keys) > 0:
        #print 'Pulsing keys from write_... :(', pulse_keys
        pulse_masked_register(device_list, bitstruct, pulse_keys)

def read_masked_register(device_list, bitstruct, names = None, return_dict = True):
    """
    Read a 32-bit register from each of the devices (anything that provides the read_uint interface) in the supplied list and apply the given construct.BitStruct to the data.
    A list of Containers or dictionaries is returned, indexing the same as the supplied list.
    """
    if bitstruct == None:
        return
    if bitstruct.sizeof() != 4:
        raise RuntimeError('Function can only work with 32-bit bitfields.')
    registerNames = names
    if registerNames == None:
        registerNames = []
        for d in device_list: registerNames.append(bitstruct.name)
    if len(registerNames) !=  len(device_list):
        raise RuntimeError('Length of list of register names does not match length of list of devices given.')
    rv = []
    for d, device in enumerate(device_list):
        vuint = device.read_uint(registerNames[d])
        rtmp = bitstruct.parse(struct.pack('>I', vuint))
        rtmp.raw = vuint
        rtmp.register_name = registerNames[d]
        if return_dict: rtmp = rtmp.__dict__
        rv.append(rtmp)
    return rv

def pulse_masked_register(device_list, bitstruct, fields):
    """
    Pulse a boolean var somewhere in a masked register.
    The fields argument is a list of strings representing the fields to be pulsed. Does NOT check Flag vs BitField, so make sure!
    http://stackoverflow.com/questions/1098549/proper-way-to-use-kwargs-in-python
    """
    zeroKwargs = {}
    oneKwargs = {}
    for field in fields:
      zeroKwargs[field] = 0
      oneKwargs[field] = 1
    #print zeroKwargs, '|', oneKwargs
    write_masked_register(device_list, bitstruct, **zeroKwargs)
    write_masked_register(device_list, bitstruct, **oneKwargs)
    write_masked_register(device_list, bitstruct, **zeroKwargs)

def log_runtimeerror(logger, err):
    """
    Have the logger log an error and then raise it.
    """
    logger.error(err)
    raise RuntimeError(err)

class Correlator:

    def __init__(self, connect = True, config_file = None, log_handler = None, log_level = logging.INFO):
        self.MODE_WB = 'wbc'
        self.MODE_NB = 'nbc'
        self.MODE_DDC = 'ddc'
        self.log_handler = log_handler if log_handler != None else corr.log_handlers.DebugLogHandler(100)
        self.syslogger = logging.getLogger('corrsys')
        self.syslogger.addHandler(self.log_handler)
        self.syslogger.setLevel(log_level)

        if config_file == None: 
            config_file = DEFAULT_CONFIG
            self.syslogger.warn('Defaulting to config file %s.' % DEFAULT_CONFIG)
        self.config = corr.cn_conf.CorrConf(config_file)

        self.xsrvs = self.config['servers_x']
        self.fsrvs = self.config['servers_f']
        self.allsrvs = self.fsrvs + self.xsrvs

        self.floggers = [logging.getLogger(s) for s in self.fsrvs]
        self.xloggers = [logging.getLogger(s) for s in self.xsrvs]
        self.loggers = self.floggers + self.xloggers
        for logger in (self.loggers): 
            logger.addHandler(self.log_handler)
            logger.setLevel(log_level)

        self.syslogger.info('Configuration file %s parsed ok.' % config_file)
        self.spead_tx=spead.Transmitter(spead.TransportUDPtx(self.config['rx_meta_ip_str'], self.config['rx_udp_port']))
        self.spead_ig=spead.ItemGroup()

        if connect == True:
            self.connect()

    def connect(self):
        self.xfpgas=[corr.katcp_wrapper.FpgaClient(server,self.config['katcp_port'],
                       timeout=10,logger=self.xloggers[s]) for s,server in enumerate(self.xsrvs)]
        self.ffpgas=[corr.katcp_wrapper.FpgaClient(server,self.config['katcp_port'],
                       timeout=10,logger=self.floggers[s]) for s,server in enumerate(self.fsrvs)]
        self.allfpgas = self.ffpgas + self.xfpgas
        time.sleep(1)
        if not self.check_katcp_connections():
            raise RuntimeError("Connection to FPGA boards failed.")
        #self.get_rcs()

    def __del__(self):
        self.disconnect_all()

    def disconnect_all(self):
        """Stop all TCP KATCP links to all FPGAs defined in the config file."""
        #tested ok corr-0.5.0 2010-07-19
        try:
            for fpga in (self.allfpgas): fpga.stop()
        except:
            pass

    def get_rcs(self):
        """Extracts and returns a dictionary of the version control information from the F and X engines."""
        try:
            frcs=self.ffpgas[0].get_rcs()
            if frcs.has_key('user'):
                self.syslogger.info('F engines version %i found.'%frcs['user'])
            if frcs.has_key('compile_timestamp'):
                self.syslogger.info('F engine bitstream was compiled at %s.'%time.ctime(frcs['compile_timestamp']))
            if frcs.has_key('app_last_modified'):
                self.syslogger.info('F engine bitstream was last modified on %s.'%time.ctime(frcs['app_last_modified']))
            if frcs.has_key('lib_rcs_type'):
                self.syslogger.info('F engine bitstream was compiled from %s DSP libraries, rev %0X %s.'%(
                    frcs['lib_rcs_type'],
                    frcs['lib_rev'],
                    ('DIRTY' if frcs['lib_dirty'] else 'CLEAN')))
            if frcs.has_key('app_rcs_type'):
                self.syslogger.info('F engine bitstream was compiled from %s, rev %0X %s.'%(
                    frcs['app_rcs_type'],
                    frcs['app_rev'],
                    ('DIRTY' if frcs['app_dirty'] else 'CLEAN')))

            if self.config['adc_type'] == 'katadc':
                for fn,fpga in enumerate(self.ffpgas):
                    for an in range(self.config['f_per_fpga']):
                        adc_details=corr.katadc.eeprom_details_get(fpga,an)
                        self.floggers[fn].info("KATADC %i, rev %3.1f found on ZDOK port %i."%(adc_details['serial_number'],adc_details['pcb_rev']/10.0,an))

            xrcs=self.xfpgas[0].get_rcs()
            if xrcs.has_key('user'):
                self.syslogger.info('X engines version %i found.'%xrcs['user'])
            if xrcs.has_key('compile_timestamp'):
                self.syslogger.info('X engine bitstream was compiled at %s.'%time.ctime(xrcs['compile_timestamp']))
            if xrcs.has_key('app_last_modified'):
                self.syslogger.info('X engine bitstream was last modified on %s.'%time.ctime(xrcs['app_last_modified']))
            if xrcs.has_key('lib_rcs_type'):
                self.syslogger.info('X engine bitstream was compiled from %s DSP libraries, rev %0X %s.'%(
                    xrcs['lib_rcs_type'],
                    xrcs['lib_rev'],
                    ('DIRTY' if xrcs['lib_dirty'] else 'CLEAN')))
            if xrcs.has_key('app_rcs_type'):
                self.syslogger.info('X engine bitstream was compiled from %s, rev %0X %s.'%(
                    xrcs['app_rcs_type'],
                    xrcs['app_rev'],
                    ('DIRTY' if xrcs['app_dirty'] else 'CLEAN')))
            return {'f':frcs,'x':xrcs}
        except:
            self.syslogger.warn('Error retrieving RCS info from correlator')
            return {}

    def label_input(self,input_n,ant_str):
        """Labels inputs as specified. input_n is an integer specifying the physical connection. Ordering: first input of first feng, second input of first feng,...,first input of second feng, second input of second feng,...,second-last input of last feng,last input of last feng."""
        if input_n>=self.config['n_inputs']:
            raise RuntimeError("Trying to configure input %i? That's crazytalk, you only have %i inputs in your system!"%(input_n,self.config['n_inputs']))
        if ant_str=='' or ant_str==None:
            self.syslogger.warning('No antenna label specified, using defaults')
            a=input_n/2
            p=self.config['pols'][input_n%2]
            ant_str='%i%c'%(a,p)
        mapping=self.config._get_ant_mapping_list()
        mapping[input_n]=ant_str
        self.config.write_var_list('antenna_mapping',mapping)
        ffpga_n,xfpga_n,fxaui_n,xxaui_n,feng_input = self.get_ant_str_location(ant_str)
        self.floggers[ffpga_n].info('Relabelled my input %i (system-wide input %i) to %s.'%(feng_input,input_n,ant_str))
        self.spead_labelling_issue()

    def get_bl_order(self):
        """Return the order of baseline data output by a CASPER correlator X engine."""
        n_ants=self.config['n_ants']
        order1, order2 = [], []
        for i in range(n_ants):
            for j in range(int(n_ants/2),-1,-1):
                k = (i-j) % n_ants
                if i >= k: order1.append((k, i))
                else: order2.append((i, k))
        order2 = [o for o in order2 if o not in order1]
        dp_bls = tuple([o for o in order1 + order2])
        rv=[]
        for bl in dp_bls:
            rv.append(tuple((self.map_input_to_ant(bl[0]*2),self.map_input_to_ant(bl[1]*2))))
            rv.append(tuple((self.map_input_to_ant(bl[0]*2+1),self.map_input_to_ant(bl[1]*2+1))))
            rv.append(tuple((self.map_input_to_ant(bl[0]*2),self.map_input_to_ant(bl[1]*2+1))))
            rv.append(tuple((self.map_input_to_ant(bl[0]*2+1),self.map_input_to_ant(bl[1]*2))))
        return rv

    def get_crosspol_order(self):
        "Returns the order of the cross-pol terms out the X engines"
        pol1=self.config['rev_pol_map'][0]
        pol2=self.config['rev_pol_map'][1]
        return (pol1+pol1,pol2+pol2,pol1+pol2,pol2+pol1) 

    def prog_all(self):
        """Programs all the FPGAs."""
        #tested ok corr-0.5.0 2010-07-19
        for fpga in self.ffpgas:
            fpga.progdev(self.config['bitstream_f'])
        for fpga in self.xfpgas:
            fpga.progdev(self.config['bitstream_x'])
        if not self.check_fpga_comms(): 
            raise RuntimeError("Failed to successfully program FPGAs.")
        else:
            self.syslogger.info("All FPGAs programmed ok.")
            time.sleep(1)
            self.get_rcs()

    def check_fpga_comms(self):
        """Checks FPGA <-> BORPH communications by writing a random number into a special register, reading it back and comparing."""
        #Modified 2010-01-03 so that it works on 32 bit machines by only generating random numbers up to 2**30.
        rv = True
        for fn,fpga in enumerate(self.allfpgas):
            #keep the random number below 2^32-1 and do not include zero (default register start value), but use a fair bit of the address space...
            rn=numpy.random.randint(1,2**30)
            try: 
                fpga.write_int('sys_scratchpad',rn)
                self.loggers[fn].info("FPGA comms ok")
            except: 
                rv=False
                self.loggers[fn].error("FPGA comms failed")
        if rv==True: self.syslogger.info("All FPGA comms ok.")
        return rv

    def deprog_all(self):
        """Deprograms all the FPGAs."""
        #tested ok corr-0.5.0 2010-07-19
        for fpga in self.ffpgas:
            fpga.progdev('')
        for fpga in self.xfpgas:
            fpga.progdev('')
        self.syslogger.info("All FPGAs deprogrammed.")

    def xread_all(self,register,bram_size,offset=0):
        """Reads a register of specified size from all X-engines. Returns a list."""
        rv = [fpga.read(register,bram_size,offset) for fpga in self.xfpgas]
        return rv

    def fread_all(self,register,bram_size,offset=0):
        """Reads a register of specified size from all F-engines. Returns a list."""
        rv = [fpga.read(register,bram_size,offset) for fpga in self.ffpgas]
        return rv

    def xread_uint_all(self, register):
        """Reads a value from register 'register' for all X-engine FPGAs."""
        return [fpga.read_uint(register) for fpga in self.xfpgas]

    def fread_uint_all(self, register):
        """Reads a value from register 'register' for all F-engine FPGAs."""
        return [fpga.read_uint(register) for fpga in self.ffpgas]

    def xwrite_int_all(self,register,value):
        """Writes to a 32-bit software register on all X-engines."""
        [fpga.write_int(register,value) for fpga in self.xfpgas]

    def fwrite_int_all(self,register,value):
        """Writes to a 32-bit software register on all F-engines."""
        [fpga.write_int(register,value) for fpga in self.ffpgas]

    def feng_ctrl_set_all(self, **kwargs):
        """Valid keyword args include: 
        tvgsel_noise','tvgsel_fdfs', 'tvgsel_pkt', 'tvgsel_ct', 'tvg_en', 'adc_protect_disable', 'flasher_en', 'gbe_enable', 'gbe_rst', 'clr_status', 'arm', 'soft_sync', 'mrst'
        """
        if self.is_wideband():
            write_masked_register(self.ffpgas, corr.corr_wb.register_fengine_control, **kwargs)
        elif self.is_narrowband():
            write_masked_register(self.ffpgas, corr.corr_nb.register_fengine_control, **kwargs)
        else:
            raise RuntimeError('Unknown mode. Cannot write F-engine control.')

    def feng_ctrl_get_all(self):
        if self.is_wideband():
            return read_masked_register(self.ffpgas, corr.corr_wb.register_fengine_control)
            #return corr.corr_wb.feng_status_get(self, ant_str)
        elif self.is_narrowband():
            return read_masked_register(self.ffpgas, corr.corr_nb.register_fengine_control)
            #return corr.corr_nb.feng_status_get(self, ant_str)
        else:
            raise RuntimeError('Unknown mode. Cannot read F-engine control.')

    def kitt_enable(self):
        """Turn on the Knightrider effect for system idle."""
        self.feng_ctrl_set_all(flasher_en=True)
        self.xeng_ctrl_set_all(flasher_en=True)

    def kitt_disable(self):
        """Turn off the Knightrider effect for system idle."""
        self.feng_ctrl_set_all(flasher_en=False)
        self.xeng_ctrl_set_all(flasher_en=False)

    def feng_tvg_available_tvgs(self):
        reg = None
        if self.is_wideband():
            reg = corr.corr_wb.register_fengine_control
        elif self.is_narrowband():
            reg = corr.corr_nb.register_fengine_control
        else:
            raise RuntimeError('Unknown mode.')
        # go to some lengths to get the names of the fields out of the construct.BitStruct
        keys = reg.subcon.subcons
        tvgs = []
        for k in keys:
            if type(k) == construct.MappingAdapter:
                if k.name[0:7] == 'tvgsel_':
                    tvgs.append(k.name)
        return tvgs

    def feng_tvg_select(self, **kwargs):
        """
        Turn ONE TVG on at a time. Use feng_tvg_vailable_tvgs() to see what TVGs are available to you in the current mode. 
        """
        available_tvgs = self.feng_tvg_available_tvgs()
        newkwargs = {}
        if len(kwargs) == 0:
            print 'No TVG given. Available f-engine TVGs in this mode are:'
            print available_tvgs
            raise RuntimeError('No TVG specified.')
        elif len(kwargs) > 1:
            raise RuntimeError('Only one TVG can be turned on at a time.')
        matched = False
        seltvg = kwargs.keys()[0]
        for avtvg in available_tvgs:
            newkwargs[avtvg] = False
            if avtvg == seltvg:
                newkwargs[avtvg] = True
                matched = True
        if not matched:
            print 'TVG \'%s\' doesn\'t exist. Available f-engine TVGs in this mode are:' % seltvg
            print available_tvgs
            raise RuntimeError('Invalid TVG specified.')
        self.feng_ctrl_set_all(tvg_en = True, **newkwargs)
        self.feng_ctrl_set_all(tvg_en = False, **newkwargs)

    def feng_tvg_sel_OLD(self, noise = False, ct = False, pkt = False, fdfs = False):
        """Turns TVGs on/off on the F engines."""
        if not self.is_wideband():
            raise RuntimeError('Only valid in wideband mode.')
        self.feng_ctrl_set_all(tvg_en = True,  tvgsel_noise = noise, tvgsel_ct = ct, tvgsel_pkt = pkt, tvgsel_fdfs = fdfs)
        self.feng_ctrl_set_all(tvg_en = False, tvgsel_noise = noise, tvgsel_ct = ct, tvgsel_pkt = pkt, tvgsel_fdfs = fdfs)

    def xeng_ctrl_set_all(self, **kwargs):
        write_masked_register(self.xfpgas, corr.corr_wb.register_xengine_control, **kwargs)

    def xeng_ctrl_get_all(self):
        return read_masked_register(self.xfpgas, corr.corr_wb.register_xengine_control)

    def fft_shift_set_all(self, fft_shift = -1):
        """Configure the FFT on all F engines to the specified schedule. If not specified, default to schedule listed in config file."""
        #tested ok corr-0.5.0 2010-07-20
        if self.is_wideband():
            if fft_shift < 0:
                fft_shift = self.config['fft_shift']
            for input_n in range(self.config['f_inputs_per_fpga']):
                self.fwrite_int_all("fft_shift%i"%input_n,fft_shift)
            self.syslogger.info('Set FFT shift patterns on all Fengs to 0x%x.'%fft_shift)
        elif self.is_narrowband():
            corr.corr_nb.fft_shift_coarse_set_all(self)
            corr.corr_nb.fft_shift_fine_set_all(self)
            self.syslogger.info('Set coarse(0x%x) and fine(0x%x) FFT shift patterns.' % (self.config['fft_shift_coarse'], self.config['fft_shift_fine']))
        else: raise RuntimeError('Cannot set FFT shift for unknown mode.')

    def fft_shift_get_all(self):
        if self.is_wideband():
            rv = {}
            for in_n, ant_str in enumerate(self.config._get_ant_mapping_list()):
                ffpga_n, xfpga_n, fxaui_n, xxaui_n, feng_input = self.get_ant_str_location(ant_str)
                rv[ant_str] = self.ffpgas[ffpga_n].read_uint('fft_shift%i'%feng_input)
        elif self.is_narrowband():
            rv = corr.corr_nb.fft_shift_get_all(self)
        else:
            raise RuntimeError('Cannot get FFT shift for unknown mode.')
        return rv

    def feng_status_get_all(self):
        """Reads and decodes the status register from all the Fengines. Also does basic clock check."""
        rv={}
        feng_clks=self.check_feng_clks(quick_test=True,per_board=True)
        for ant_str in self.config._get_ant_mapping_list():
            rv[ant_str] = self.feng_status_get(ant_str)
        return rv

    def feng_status_get(self,ant_str):
        if self.is_wideband():
            return corr.corr_wb.feng_status_get(self, ant_str)
        elif self.is_narrowband():
            return corr.corr_nb.feng_status_get(self, ant_str)
        else:
            raise RuntimeError('Unknown mode. Cannot read F-engine status.')

    def xeng_status_get_all(self):
        """Reads and decodes the status registers for all xengines."""
        rv = {}
        for loc_xeng_n in range(self.config['x_per_fpga']):
            for xfpga_num, srv in enumerate(self.xsrvs):
                xeng_id = 'xeng%i' % (loc_xeng_n + self.config['x_per_fpga'] * xfpga_num)
                rv[xeng_id] = read_masked_register([self.xfpgas[xfpga_num]], corr.corr_wb.register_xengine_status, names = ['xstatus%i' % loc_xeng_n])[0]
                if (rv[xeng_id]['gbe_lnkdn'] or rv[xeng_id]['xeng_err'] or 
                    rv[xeng_id]['vacc_err'] or rv[xeng_id]['rx_bad_pkt'] or 
                    rv[xeng_id]['rx_bad_frame'] or rv[xeng_id]['tx_over'] or 
                    rv[xeng_id]['pkt_reord_err'] or rv[xeng_id]['pack_err']):
                    rv[xeng_id]['lru_state'] = 'fail'
                else:
                    rv[xeng_id]['lru_state'] = 'ok'
        return rv

    def initialise(self, n_retries = 40, reprogram = True, clock_check = True, set_eq = True, config_10gbe = True, config_output = True, send_spead = True, prog_timeout_s = 5):
        """Initialises the system and checks for errors."""
        if reprogram:
            self.deprog_all()
            time.sleep(prog_timeout_s)
            self.prog_all()

        if self.tx_status_get(): self.tx_stop()

        if self.config['feng_out_type'] == '10gbe':
            self.gbe_reset_hold_f()
        self.gbe_reset_hold_x()

        if not self.arm(): self.syslogger.error("Failed to successfully arm and trigger system.")
        if clock_check == True: 
            if not self.check_feng_clks(): 
                raise RuntimeError("System clocks are bad. Please fix and try again.")

        #Only need to set brd id on xeng if there's no incomming 10gbe, else get from base ip addr
        if self.config['feng_out_type'] == '10gbe':
            self.xeng_brd_id_set()
        self.feng_brd_id_set()

        if self.config['adc_type'] == 'katadc': 
            self.rf_gain_set_all()

        self.fft_shift_set_all()

        if set_eq: self.eq_set_all()
        else: self.syslogger.info('Skipped EQ config.')

        if config_10gbe: 
            self.config_roach_10gbe_ports()
            sleep_time=((self.config['10gbe_ip']&255) + self.config['n_xeng']*self.config['n_xaui_ports_per_xfpga'])*0.1
            self.syslogger.info("Waiting %i seconds for ARP to complete."%sleep_time)
            time.sleep(sleep_time)
            
        if self.config['feng_out_type'] == '10gbe':
            self.gbe_reset_release_f()
        self.gbe_reset_release_x()

        time.sleep(len(self.xfpgas)/2)
        self.rst_status_and_count()
        time.sleep(1)

        stat=self.check_all(details=True)
        for in_n,ant_str in enumerate(self.config._get_ant_mapping_list()):
            ffpga_n,xfpga_n,fxaui_n,xxaui_n,feng_input = self.get_ant_str_location(ant_str)
            try:
                # This is not quite right... Both ROACH's QDRs are used in a single corner-turn for both inputs. HARDCODED to check two QDRs per board!
                if stat['ant_str']['ct_error']==True:
                    self.floggers[ffpga_n].warn("Corner-Turn is in error.")
                    for qdr_n in range(2):
                        loop_retry_cnt=0
                        while (c.ffpgas[ffpga_n].qdr_status(qdr_n)['calfail']==True) and (loop_retry_cnt< n_retries):
                            time.sleep(0.2)
                            loop_retry_cnt+=1
                            self.floggers[ffpga_n].warn("SRAM calibration failed. Forcing software reset/recalibration... retry %i"%loop_retry_cnt)
                            c.ffpgas[ffpga_n].qdr_rst(qdr_n)
                        if c.ffpgas[ffpga_n].qdr_status(qdr_n)['calfail']==True:
                            raise RuntimeError("Could not calibrate QDR%i after %i retries. Giving up."%(qdr_n,n_retries))

                if (stat['ant_str']['adc_disabled']==True) or (stat['ant_str']['adc_overrange']==True):
                    self.floggers[ffpga_n].warn("%s input levels are too high!"%ant_str)
                if stat['ant_str']['fft_overrange']==True:
                    self.floggers[ffpga_n].warn("%s FFT is overranging. Spectrum output is garbage."%ant_str)
            except:
                pass 

        if self.config['feng_out_type'] == 'xaui':
            if not self.check_xaui_error(): raise RuntimeError("XAUI checks failed.")
            if not self.check_xaui_sync(): raise RuntimeError("Fengines appear to be out of sync.")
        if not self.check_10gbe_tx(): raise RuntimeError("10GbE cores are not transmitting properly.")
        if not self.check_10gbe_rx(): raise RuntimeError("10GbE cores are not receiving properly.")
        if self.config['feng_out_type'] == 'xaui':
            if not self.check_loopback_mcnt_wait(n_retries=n_retries): raise RuntimeError("Loopback muxes didn't sync.")
        if not self.check_x_miss(): raise RuntimeError("X engines are missing data.")
        self.acc_time_set()   #self.rst_status_and_count() is done as part of this setup
        self.syslogger.info("Waiting %i seconds for an integration to finish so we can test the VACCs."%self.config['int_time'])
        time.sleep(self.config['int_time']+0.1)
        if not self.check_vacc(): 
            for x in range(self.config['x_per_fpga']):
                for nx,xsrv in enumerate(self.xsrvs):
                    while (c.xfpgas[nx].qdr_status(x)['calfail']==True) and (loop_retry_cnt< n_retries):
                        time.sleep(0.2)
                        loop_retry_cnt+=1
                        self.xloggers[nx].warn("SRAM calibration failed. Forcing software reset/recalibration... retry %i"%loop_retry_cnt)
                        c.xfpgas[nx].qdr_rst(x)
                    if c.xfpgas[nx].qdr_status(x)['calfail']==True:
                        raise RuntimeError("Could not calibrate QDR%i."%x)
            
            raise RuntimeError("Vector accumulators are broken.")

        if send_spead:
            self.spead_issue_all()

        if config_output: 
            self.config_udp_output()

        self.kitt_enable()
        self.syslogger.info("Initialisation completed.")

    def gbe_reset_hold_x(self):
        """ Places the 10gbe core in reset. ALSO DISABLES ANY DATA OUTPUT TO THE CORE."""
        self.xeng_ctrl_set_all(gbe_out_enable = False, gbe_enable = False, gbe_rst = False)
        self.xeng_ctrl_set_all(gbe_out_enable = False, gbe_enable = False, gbe_rst = True)
        self.syslogger.info("Holding X engine 10GbE cores in reset.")

    def gbe_reset_hold_f(self):
        """ Places the 10gbe core in reset. """
        self.feng_ctrl_set_all(gbe_enable = False, gbe_rst = False)
        self.feng_ctrl_set_all(gbe_enable = False, gbe_rst = True)
        self.syslogger.info("Holding F engine 10GbE cores in reset.")

    def gbe_reset_release_x(self):
        """ Enables the 10gbe core. DOES NOT START DATA TRANSMISSION! """
        self.xeng_ctrl_set_all(gbe_enable = False, gbe_rst = False)
        self.xeng_ctrl_set_all(gbe_enable = True, gbe_rst = False)
        self.syslogger.info("X engine 10GbE cores released from reset.")

    def gbe_reset_release_f(self):
        """ Enables the 10gbe core. DOES NOT START DATA TRANSMISSION! """
        self.feng_ctrl_set_all(gbe_enable = False, gbe_rst = False)
        self.feng_ctrl_set_all(gbe_enable = True, gbe_rst = False)
        self.syslogger.info("F engine 10GbE cores released from reset.")

    def tx_start(self):
        """Start outputting SPEAD products. Only works for systems with 10GbE output atm.""" 
        if self.config['out_type'] == '10gbe':
            self.xeng_ctrl_set_all(gbe_out_enable = True)
            self.syslogger.info("Correlator output started.")
        else:
            self.syslogger.error('Sorry, your output type is not supported. Could not enable output.')
            #raise RuntimeError('Sorry, your output type is not supported.')

    def tx_stop(self,spead_stop=True):
        """Stops outputting SPEAD data over 10GbE links."""
        if self.config['out_type'] == '10gbe':
            self.xeng_ctrl_set_all(gbe_out_enable = False)
            self.syslogger.info("Correlator output paused.")
            if spead_stop:
                tx_temp = spead.Transmitter(spead.TransportUDPtx(self.config['rx_meta_ip_str'], self.config['rx_udp_port']))
                tx_temp.end()
                self.syslogger.info("Sent SPEAD end-of-stream notification.")
            else:
                self.syslogger.info("Did not send SPEAD end-of-stream notification.")
        else:
            #raise RuntimeError('Sorry, your output type is not supported.')
            self.syslogger.warn("Sorry, your output type is not supported. Cannot disable output.")

    def tx_status_get(self):
        """Returns boolean true/false if the correlator is currently outputting data. Currently only works on systems with 10GbE output."""
        if self.config['out_type']!='10gbe': 
            self.syslogger.warn("This function only works for systems with 10GbE output!")
            return False
        rv=True
        stat=self.xeng_ctrl_get_all()
        for xn,xsrv in enumerate(self.xsrvs):
            if stat[xn]['gbe_out_enable'] != True or stat[xn]['gbe_out_rst']!=False: rv=False
        self.syslogger.info('Output is currently %s'%('enabled' if rv else 'disabled'))
        return rv

    def check_feng_clks(self, quick_test=False, per_board=False):
        """ Checks all Fengine FPGAs' clk_frequency registers to confirm correct PPS operation. Requires that the system be sync'd. If per_board is True, returns a list of all f engine boards' clk status. If quick_test is true, does not estimate the boards' clock frequencies."""
        # tested ok corr-0.5.0 2010-07-19
        rv = [True for b in self.fsrvs]
        expect_rate = round(self.config['feng_clk'] / 1000000) # expected clock rate in MHz.

        # estimate actual clk freq 
        if quick_test == False:
            clk_freq=self.feng_clks_get()
            clk_mhz=[round(cf) for cf in clk_freq] #round to nearest MHz
            for fbrd,fsrv in enumerate(self.fsrvs):
                if clk_freq[fbrd] <= 100: 
                    self.floggers[fbrd].error("No clock detected!")
                    rv[fbrd] = False
                if (clk_mhz[fbrd] > (expect_rate+1)) or (clk_mhz[fbrd] < (expect_rate -1)) or (clk_mhz[fbrd]==0):
                    self.floggers[fbrd].error("Estimated clock freq is %i MHz, where expected rate is %i MHz."%(clk_mhz[fbrd], expect_rate))
                    rv[fbrd] = False
            if False in rv: 
                self.syslogger.error("Some Fengine clocks are dead. We can't continue.")
                if not per_board:
                    return False
                else:
                    return rv
            else: 
                self.syslogger.info("Fengine clocks are approximately correct at %i MHz."%expect_rate)

        #check long-term integrity
        #wait for within 100ms of a second, then delay a bit and query PPS count.
        ready=((int(time.time()*10)%10)==5)
        while not ready: 
            ready=((int(time.time()*10)%10)==5)
            #print time.time()
            time.sleep(0.05)
        uptime=[ut[1] for ut in self.feng_uptime()]
        exp_uptime = numpy.floor(time.time() - self.config['sync_time'])
        mode = statsmode(uptime)
        modalmean=numpy.mean(mode)
        for fbrd,fsrv in enumerate(self.fsrvs):
            if uptime[fbrd] == 0: 
                rv[fbrd]=False
                self.floggers[fbrd].error("No PPS detected! PPS count is zero.")
            elif (uptime[fbrd] > (modalmean+1)) or (uptime[fbrd] < (modalmean -1)) or (uptime[fbrd]==0):
                rv[fbrd]=False
                self.floggers[fbrd].error("PPS count is %i pulses, where modal mean is %i pulses. This board has a bad 1PPS input."%(uptime[fbrd], modalmean))
            elif uptime[fbrd] != exp_uptime: 
                rv[fbrd]=False
                self.floggers[fbrd].error("Expected uptime is %i seconds, but we've counted %i PPS pulses."%(exp_uptime,uptime[fbrd]))
            else:
                self.floggers[fbrd].info("Uptime is %i seconds, as expected."%(uptime[fbrd]))

        #check the PPS against sampling clock.
        all_values = self.fread_uint_all('clk_frequency')
        mode = statsmode(all_values)
        modalmean=numpy.mean(mode)
        #modalmean=stats.mean(mode[1])
        modalfreq=numpy.round((expect_rate*1000000.)/modalmean,3)
        if (modalfreq != 1):
            self.syslogger.error("PPS period is approx %3.2f Hz, not 1Hz (assuming a clock frequency of %i MHz)."%(modalfreq,expect_rate))
            rv=[False for b in self.fsrvs]
        else:
            self.syslogger.info("Assuming a clock of %iMHz and that the PPS and clock are correct on most boards, PPS period is %3.2fHz and clock rate is %6.3fMHz."%(expect_rate,modalfreq,modalmean/1000000.))

        for fbrd,fsrv in enumerate(self.fsrvs):
            if all_values[fbrd] == 0: 
                self.floggers[fbrd].error("No PPS or no clock... clk_freq register is zero!")
                rv[fbrd]=False
            if (all_values[fbrd] > (modalmean+2)) or (all_values[fbrd] < (modalmean -2)) or (all_values[fbrd]==0):
                self.floggers[fbrd].error("Clocks between PPS pulses is %i, where modal mean is %i. This board has a bad sampling clock or PPS input."%(all_values[fbrd], modalmean))
                rv[fbrd]=False
            else:
                self.floggers[fbrd].info("Clocks between PPS pulses is %i as expected."%(all_values[fbrd]))

        if per_board:
            return rv
        else:
            if False in rv: return False
            else: return True

    def feng_uptime(self):
        """Returns a list of tuples of (armed_status and pps_count) for all fengine fpgas. Where the count since last arm of the pps signals received (and hence number of seconds since last arm)."""
        #tested ok corr-0.5.0 2010-07-19
        all_values = self.fread_uint_all('pps_count')
        pps_cnt = [val & 0x7FFFFFFF for val in all_values]
        arm_stat = [bool(val & 0x80000000) for val in all_values]
        return [(arm_stat[fn],pps_cnt[fn]) for fn in range(len(self.ffpgas))]

    def mcnt_current_get(self,ant_str=None):
        "Returns the current mcnt for a given antenna. If not specified, return a list of mcnts for all connected f engine FPGAs"
        #tested ok corr-0.5.0 2010-07-19
        if ant_str==None:
            msw = self.fread_uint_all('mcount_msw')
            lsw = self.fread_uint_all('mcount_lsw')
            mcnt = [(msw[i] << 32) + lsw[i] for i,srv in enumerate(self.fsrvs)]
            return mcnt
        else:
            ffpga_n,xfpga_n,fxaui_n,xxaui_n,feng_input = self.get_ant_str_location(ant_str)
            msw = self.ffpgas[ffpga_n].read_uint('mcount_msw')
            lsw = self.ffpgas[ffpga_n].read_uint('mcount_lsw')
            return (msw << 32) + lsw 
    
    def pcnt_current_get(self):
        "Returns the current packet count. ASSUMES THE SYSTEM IS SYNC'd!"
        msw = self.ffpgas[0].read_uint('mcount_msw')
        lsw = self.ffpgas[0].read_uint('mcount_lsw')
        mcount = (msw << 32) + lsw
        return int(mcount * self.config['pcnt_scale_factor'] / self.config['mcnt_scale_factor'])
    
    def arm(self, spead_update = True):
        """Arms all F engines, records arm time in config file and issues SPEAD update. Returns the UTC time at which the system was sync'd in seconds since the Unix epoch (MCNT=0)"""
        # tested ok corr-0.5.0 2010-07-19
        # wait for within 100ms of a half-second, then send out the arm signal.
        rv = True
        ready = ((int(time.time() * 10) % 10) == 5)
        while not ready: 
            ready = ((int(time.time() * 10) % 10) == 5)
        start_time = time.time()
        self.feng_ctrl_set_all(arm = 'pulse')
        max_wait = self.config['feng_sync_delay'] + 2
        #print 'Issued arm at %f.'%start_time
        done = False
        armed_stat = []
        while ((time.time() - start_time) < max_wait) and (not done):
            armed_stat = [armed[0] for armed in self.feng_uptime()]
            done_now = True
            #print time.time(), armed_stat
            for i, stat in enumerate(armed_stat):
                if armed_stat[i]: done_now = False
            if done_now: done = True
            time.sleep(0.1)
        done_time = time.time()
        if not done:
            for i,stat in enumerate(armed_stat):
                if armed_stat[i]:
                    self.floggers[i].error("Did not trigger. Check clock and 1PPS.")
                    rv = False
                else:
                    self.floggers[i].info('Triggered.')
        else:
            self.syslogger.info("All boards triggered.")
        #print 'Detected trigger at %f.'%done_time
        self.config.write_var('sync_time', str(numpy.floor(done_time)))
        elapsed_time=numpy.floor(done_time)-numpy.ceil(start_time)
        if (elapsed_time) > self.config['feng_sync_delay']:
            log_runtimeerror(self.syslogger, 'We expected to trigger the boards in %i 1PPS pulses, but %i seconds have elapsed.' % (self.config['feng_sync_delay'],elapsed_time))
        #print 'Recorded sync time as at %f.'%numpy.floor(done_time)
        if rv == False:
            log_runtimeerror(self.syslogger, "Failed to arm and trigger the system properly.")
        if spead_update:
            self.spead_time_meta_issue()
        self.syslogger.info("Arm OK, sync time recorded as %i."%numpy.floor(done_time))
        return int(numpy.floor(done_time))

    def get_roach_gbe_conf(self,start_addr,fpga,port):
        """Generates 10GbE configuration strings for ROACH-based xengines starting from 
        ip "start_addr" for FPGA numbered "FPGA" (offset from start addr).
        Returns a (mac,ip,port) tuple suitable for passing to tap_start."""
        sys.stdout.flush()
        ip = (start_addr + fpga) & ((1<<32)-1)
        mac = (2<<40) + (2<<32) + ip
        return (mac,ip,port)

    def rst_status_and_count(self):
        """Resets all status registers and error counters on all connected boards."""
        self.rst_fstatus()
        self.rst_xstatus()

    def rst_xstatus(self):
        """Clears the status registers and counters on all connected X engines."""
        if self.is_wideband():
            pulse_masked_register(self.xfpgas, corr.corr_wb.register_xengine_control, ['cnt_rst', 'clr_status'])
        elif self.is_narrowband():
            pulse_masked_register(self.xfpgas, corr.corr_nb.register_xengine_control, ['cnt_rst', 'clr_status'])
        else:
            raise RuntimeError('Unknown mode. Cannot reset X-engine status and error counters.')

    def rst_fstatus(self):
        """Clears the status registers on all connected F engines."""
        #self.feng_ctrl_set_all(clr_status='pulse')
        if self.is_wideband():
            pulse_masked_register(self.ffpgas, corr.corr_wb.register_fengine_control, ['clr_status'])
        elif self.is_narrowband():
            pulse_masked_register(self.ffpgas, corr.corr_nb.register_fengine_control, ['clr_status'])
        else:
            raise RuntimeError('Unknown mode. Cannot reset F-engine status and error counters.')

    def rst_vaccs(self):
        """Resets all Xengine Vector Accumulators."""
        #self.xeng_ctrl_set_all(vacc_rst='pulse')
        if self.is_wideband():
            pulse_masked_register(self.xfpgas, corr.corr_wb.register_xengine_control, ['vacc_rst'])
        elif self.is_narrowband():
            pulse_masked_register(self.xfpgas, corr.corr_nb.register_xengine_control, ['vacc_rst'])
        else:
            raise RuntimeError('Unknown mode. Cannot reset vector accumulators.')

    def xeng_clks_get(self):
        """Returns the approximate clock rate of each X engine FPGA in MHz."""
        #tested ok corr-0.5.0 2010-07-19
        return [fpga.est_brd_clk() for fpga in self.xfpgas]

    def feng_clks_get(self):
        """Returns the approximate clock rate of each F engine FPGA in MHz."""
        #tested ok corr-0.5.0 2010-07-19
        return [fpga.est_brd_clk() for fpga in self.ffpgas]

    def check_katcp_connections(self):
        """Returns a boolean result of a KATCP ping to all all connected boards."""
        result = True
        for fn,fpga in enumerate(self.allfpgas):
            try:
                fpga.ping()
                self.loggers[fn].info('KATCP connection ok.')
            except:
                self.loggers[fn].error('KATCP connection failure.')
                result = False
        if result == True: self.syslogger.info('KATCP communication with all boards ok.')
        else: self.syslogger.error('KATCP communication with one or more boards FAILED.')
        return result

    def check_x_miss(self):
        """Returns boolean pass/fail to indicate if any X engine has missed any data, or if the descrambler is stalled."""
        rv = True
        for x in range(self.config['x_per_fpga']):
            err_check = self.xread_uint_all('pkt_reord_err%i' % x)
            cnt_check = self.xread_uint_all('pkt_reord_cnt%i' % x)
            for xbrd, xsrv in enumerate(self.xsrvs):
                if (err_check[xbrd] != 0) or (cnt_check[xbrd] == 0) :
                    self.xloggers[xbrd].error("Data error on this xeng(%i,%i) - %s %s." % (x, xbrd, "(ERR == %8i, 0b%s != 0)" % (err_check[xbrd], numpy.binary_repr(err_check[xbrd],32)) if err_check[xbrd] != 0 else "", "(CNT==0)" if cnt_check[xbrd] == 0 else ""))
                    rv = False
                else:
                    self.xloggers[xbrd].info("All X engine data on this xeng(%i,%i) OK." % (x, xbrd))
        if rv == True:
            self.syslogger.info("No missing Xeng data.")
        else:
            self.syslogger.error("Some Xeng data missing.")
        return rv

    def check_xaui_error(self):
        """Returns a boolean indicating if any X engines have bad incomming XAUI links.
        Checks that data is flowing and that no errors have occured. Returns True/False."""
        if self.config['feng_out_type'] != 'xaui':
            raise RuntimeError("According to your config file, you don't have any XAUI cables connected to your F engines!")
        rv = True
        for x in range(self.config['n_xaui_ports_per_xfpga']):
            cnt_check = self.xread_uint_all('xaui_cnt%i'%(x))
            err_check = self.xread_uint_all('xaui_err%i'%x)
            for f in range(self.config['n_ants']/self.config['n_ants_per_xaui']/self.config['n_xaui_ports_per_xfpga']):
                if (cnt_check[f] == 0):
                    rv=False
                    self.xloggers[f].error('No F engine data on XAUI port %i.'%(x))
                elif (err_check[f] !=0):
                    self.xloggers[f].error('Bad F engine data on XAUI port %i.'%(x))
                    rv=False
                else:
                    self.xloggers[f].info('F engine data on XAUI port %i OK.'%(x))

        if rv == True: self.syslogger.info("All XAUI links look good.")
        else: self.syslogger.error("Some bad XAUI links here.")
        return rv
    
    def check_10gbe_tx(self):
        """Checks that the 10GbE cores are transmitting data. Outputs boolean good/bad."""
        rv=True
        if self.config['feng_out_type'] == 'xaui':
            for x in range(self.config['n_xaui_ports_per_xfpga']):
                firstpass_check = self.xread_uint_all('gbe_tx_cnt%i'%x)
                time.sleep(0.01)
                secondpass_check = self.xread_uint_all('gbe_tx_cnt%i'%x)

                for f in range(self.config['n_ants']/self.config['n_ants_per_xaui']/self.config['n_xaui_ports_per_xfpga']):
                    if (secondpass_check[f] == 0) or (secondpass_check[f] == firstpass_check[f]):
                        self.xloggers[f].error('10GbE core %i is not sending any data.'%(x))
                        rv = False
                    else:
                        self.xloggers[f].info('10GbE core %i is sending data.'%(x))
        elif self.config['feng_out_type'] == '10gbe':
            stat=self.feng_status_get_all()
            for in_n,ant_str in enumerate(self.config._get_ant_mapping_list()):
                ffpga_n,xfpga_n,fxaui_n,xxaui_n,feng_input = self.get_ant_str_location(ant_str)
                if stat[(ant_str)]['xaui_lnkdn'] == True:
                    self.floggers[ffpga_n].error("10GbE core %i for antenna %s link is down."%(fxaui_n,ant_str))
                    rv = False
                elif stat[(ant_str)]['xaui_over'] == True:
                    self.floggers[ffpga_n].error('10GbE core %i for antenna %s is overflowing.'%(fxaui_n,ant_str))
                    rv = False
            for x in range(self.config['n_xaui_ports_per_ffpga']):
                firstpass_check = self.fread_uint_all('gbe_tx_cnt%i'%x)
                time.sleep(0.01)
                secondpass_check = self.fread_uint_all('gbe_tx_cnt%i'%x)
                for f in range(self.config['n_ffpgas']):
                    if (secondpass_check[f] == 0) or (secondpass_check[f] == firstpass_check[f]):
                        self.floggers[f].error('10GbE core %i is not sending any data.'%(x))
                        rv = False
                    else:
                        self.floggers[f].info('10GbE core %i is sending data.'%(x))
        else:
            self.syslogger.error("Skipped 10GbE TX check")

        if rv == True: self.syslogger.info("10GbE TX exchange check passed.")
        else: self.syslogger.error("Some 10GbE cores aren't sending data.")
        return rv

    def check_10gbe_rx(self):
        """Checks that all the 10GbE cores are receiving packets."""
        rv=True
        for x in range(min(self.config['n_xaui_ports_per_xfpga'],self.config['x_per_fpga'])):
            firstpass_check = self.xread_uint_all('gbe_rx_cnt%i'%x)
            time.sleep(0.01)
            secondpass_check = self.xread_uint_all('gbe_rx_cnt%i'%x)
            for s,xsrv in enumerate(self.xsrvs):
                if (secondpass_check[s] == 0):
                    rv=False
                    self.xloggers[s].error('10GbE core %i is not receiving any packets.'%(x))
                elif (secondpass_check[s] == firstpass_check[s]):
                    rv=False
                    self.xloggers[s].error('10GbE core %i received %i packets, but then stopped..'%(x,secondpass_check[s]))
                else:
                    self.xloggers[s].info('10GbE core %i received %i packets total. All OK.'%(x,secondpass_check[s]))
        if rv == True: self.syslogger.info("All 10GbE cores are receiving data.")
        else: self.syslogger.error("Some 10GbE cores aren't receiving data.")
        return rv

    def decode_10gbe_header(self, headerdata):
        """
        Returns a dictionary with the header fields decoded from the 64-bit word passed in.
        {mcnt, antbase, timestamp, pcnt, freq_chan, x_eng}
        Currently only valid for contiguous mode.
        """
        if self.config['xeng_format'] != "cont":
            raise RuntimeError("Only valid for contiguous mode at the moment. Is interleaved mode even valid anymore?!")
        import math
        fbits = int(math.log(self.config['n_chans'], 2))
        header = {}
        header['mcnt'] = headerdata >> 16
        header['antbase'] = headerdata & ((2**16) - 1)
        header['timestamp'] = header['mcnt'] >> fbits
        header['pcnt'] = header['mcnt'] & (self.config['n_chans'] - 1)
        header['freq_chan'] = header['mcnt'] % self.config['n_chans']
        header['x_eng'] = header['freq_chan'] / (self.config['n_chans'] / self.config['n_xeng'])
        return header

    def check_loopback_mcnt_wait(self,n_retries=40):
        """Waits up to n_retries for loopback muxes to sync before returning false if it is still failing."""
        sys.stdout.flush()
        loopback_ok=self.check_loopback_mcnt()
        loop_retry_cnt=0
        while (not loopback_ok) and (loop_retry_cnt< n_retries):
            time.sleep(1)
            loop_retry_cnt+=1
            self.syslogger.info("waiting for loopback lock... %i tries so far."%loop_retry_cnt)
            sys.stdout.flush()
            loopback_ok=self.check_loopback_mcnt()
        if self.check_loopback_mcnt(): 
            self.syslogger.info("loopback lock achieved after %i tries."%loop_retry_cnt)
            return True
        else: 
            self.syslogger.error("Failed to achieve loopback lock after %i tries."%n_retries)
            return False


    def check_loopback_mcnt(self):
        """Checks to see if the mux_pkts block has become stuck waiting for a crazy mcnt Returns boolean true/false."""
        rv=True
        for x in range(min(self.config['n_xaui_ports_per_xfpga'],self.config['x_per_fpga'])):
            firstpass_check = self.xread_all('loopback_mux%i_mcnt'%x,4)
            time.sleep(0.01)
            secondpass_check = self.xread_all('loopback_mux%i_mcnt'%x,4)
            for f in range(self.config['n_ants']/self.config['n_ants_per_xaui']/self.config['n_xaui_ports_per_xfpga']):
                firstloopmcnt,firstgbemcnt=struct.unpack('>HH',firstpass_check[f])
                secondloopmcnt,secondgbemcnt=struct.unpack('>HH',secondpass_check[f])

                if (secondgbemcnt == firstgbemcnt):
                    self.xloggers[f].error('10GbE input on GbE port %i is stalled.' %(x))
                    rv = False

                if (secondloopmcnt == firstloopmcnt):
                    self.xloggers[f].error('Loopback on GbE port %i is stalled.' %x)
                    rv = False

                if abs(secondloopmcnt - secondgbemcnt) > (self.config['x_per_fpga']*len(self.xsrvs)): 
                    self.xloggers[f].error('Loopback mux on GbE port %i is not syncd.'%x)
                    rv=False
        if rv == True: self.syslogger.info("All loopback muxes are locked.")
        else: self.syslogger.error("Some loopback muxes aren't locked.")
        return rv

    def check_vacc(self):
        """Returns boolean pass/fail to indicate if any X engine has vector accumulator errors."""
        rv = True
        for x in range(self.config['x_per_fpga']):
            err_check = self.xread_uint_all('vacc_err_cnt%i'%(x))
            cnt_check = self.xread_uint_all('vacc_cnt%i'%(x))
            for nx,xsrv in enumerate(self.xsrvs):
                if (err_check[nx] !=0):
                    self.xloggers[nx].error('Vector accumulator errors on this X engine %i.'%(x))
                    rv=False
                elif (cnt_check[nx] == 0) :
                    self.xloggers[nx].error('No vector accumulator data this X engine %i.'%(x))
                    rv=False
                else:
                    self.xloggers[nx].info('Vector accumulator on this X engine %i ok.'%(x))
        if rv == True: self.syslogger.info("All vector accumulators are workin' perfectly.")
        else: self.syslogger.error("Some vector accumulators are broken.")
        return rv

    def check_all(self,clock_check=False,basic_check=True,details=False):
        """Checks system health. 'basic_check' disables the checks of x engine counters to ensure that data is actually flowing. If 'details' is true, return a dictionary of results for each engine in the system. If details is false, returns boolean true if the system is operating nominally or boolean false if something's wrong."""
        rv={'sys':{'lru_state':'ok'}}
        rv.update(self.feng_status_get_all())
        rv.update(self.xeng_status_get_all())

        for b,s in rv.iteritems():
            if s['lru_state']=='fail': rv['sys']['lru_state']='warn'
        
        if clock_check:
            if not self.check_feng_clks(): rv['sys']['lru_state']='fail' 

        if not basic_check:
            if self.config['feng_out_type'] == 'xaui':
                if not self.check_xaui_error(): rv['sys']['lru_state']='fail' 
                if not self.check_xaui_sync(): rv['sys']['lru_state']='fail' 
            if not self.check_10gbe_tx(): rv['sys']['lru_state']='fail' 
            if not self.check_10gbe_rx(): rv['sys']['lru_state']='fail' 
            if self.config['feng_out_type'] == 'xaui':
                if not self.check_loopback_mcnt_wait(n_retries=n_retries): rv['sys']['lru_state']='fail' 
            if not self.check_x_miss(): rv['sys']['lru_state']='fail' 
        if details:
            return rv
        else:
            return (True if rv['sys']['lru_state']=='ok' else False)


    def tvg_vacc_sel(self,constant=0,n_values=-1,spike_value=-1,spike_location=0,counter=False):
        """Select Vector Accumulator TVG in X engines. Disables other TVGs in the process. 
            Options can be any combination of the following:
                constant:   Integer.    Insert a constant value for accumulation.
                n_values:   Integer.    How many numbers to inject into VACC. Value less than zero uses xengine timing.
                spike_value:    Int.    Inject a spike of this value in each accumulated vector. value less than zero disables.
                spike_location: Int.    Position in vector where spike should be placed.
                counter:    Boolean.    Place a ramp in the VACC.
        """
        #bit5 = rst
        #bit4 = inject counter
        #bit3 = inject vector
        #bit2 = valid_sel
        #bit1 = data_sel
        #bit0 = enable pulse generation

        if spike_value>=0:
            ctrl = (counter<<4) + (1<<3) + (1<<1)
        else:
            ctrl = (counter<<4) + (0<<3) + (1<<1)

        if n_values>0:
            ctrl += (1<<2)
            
        for xeng in range(self.config['x_per_fpga']):
            self.xwrite_int_all('vacc_tvg%i_write1'%(xeng),constant)
            self.xwrite_int_all('vacc_tvg%i_ins_vect_loc'%(xeng),spike_location)
            self.xwrite_int_all('vacc_tvg%i_ins_vect_val'%(xeng),spike_value)
            self.xwrite_int_all('vacc_tvg%i_n_pulses'%(xeng),n_values)
            self.xwrite_int_all('vacc_tvg%i_n_per_group'%(xeng),self.config['n_bls']*2)
            self.xwrite_int_all('vacc_tvg%i_group_period'%(xeng),self.config['n_ants']*self.config['xeng_acc_len'])
            self.xwrite_int_all('tvg_sel',(ctrl + (1<<5))<<9)
            self.xwrite_int_all('tvg_sel',(ctrl + (0<<5) + 1)<<9)


    def tvg_xeng_sel(self,mode=0, user_values=()):
        """Select Xengine TVG. Disables VACC (and other) TVGs in the process. Mode can be:
            0: no TVG selected.
            1: select 4-bit counters. Real components count up, imaginary components count down. Both polarisations have equal values.
            2: Fixed numbers: Pol0real=0.125, Pol0imag=-0.75, Pol1real=0.5, Pol1imag=-0.2
            3: User-defined input values. Should be 8 values, passed as tuple in user_value."""

        if mode>4 or mode<0:
            raise RuntimeError("Invalid mode selection. Mode must be in range(0,4).")
        else:
            self.xwrite_int_all('tvg_sel',mode<<3) 

        if mode==3:
            for i,v in enumerate(user_val):
                for xeng in range(self.config['x_per_fpga']):
                    self.xwrite_int_all('xeng_tvg%i_tv%i'%(xeng,i),v)

    def fr_delay_set(self,ant_str,delay=0,delay_rate=0,fringe_phase=0,fringe_rate=0,ld_time=-1,ld_check=True):
        """
        Configures a given antenna to a delay in seconds using both the coarse and the fine delay. Also configures the fringe rotation components. This is a blocking call. \n
        By default, it will wait 'till load time and verify that things worked as expected. This check can be disabled by setting ld_check param to False. \n
        Load time is optional; if not specified, load ASAP.\n
        \t Fringe offset is in degrees.\n
        \t Fringe rate is in cycles per second (Hz).\n
        \t Delay is in seconds.\n
        \t Delay rate is in seconds per second.\n
        Notes: \n
        IS A ONCE-OFF UPDATE (no babysitting by software)\n"""
        #Fix to fine delay calc on 2010-11-19

        fine_delay_bits =       16
        coarse_delay_bits =     16
        fine_delay_rate_bits =  16
        fringe_offset_bits =    16
        fringe_rate_bits =      16
        bitshift_schedule =     23
        
        min_ld_time = 0.1 # assume we're able to set and check all the registers in 100ms
        ffpga_n,xfpga_n,fxaui_n,xxaui_n,feng_input = self.get_ant_str_location(ant_str)

        # delays in terms of ADC clock cycles:
        delay_n = delay*self.config['adc_clk']                  # delay in clock cycles
        #coarse_delay = int(numpy.round(delay_n))               # delay in whole clock cycles #good for rev 369.
        coarse_delay = int(delay_n)                             # delay in whole clock cycles #testing for rev370
        fine_delay = (delay_n-coarse_delay)                     # delay remainder. need a negative slope for positive delay
        fine_delay_i = int(fine_delay*(2**(fine_delay_bits)))   # 16 bits of signed data over range 0 to +pi
    
        fine_delay_rate = int(float(delay_rate) * (2**(bitshift_schedule + fine_delay_rate_bits-1))) 

        # figure out the fringe as a fraction of a cycle        
        fr_offset = int(fringe_phase/float(360) * (2**(fringe_offset_bits)))
        # figure out the fringe rate. Input is in cycles per second (Hz). 1) divide by brd clock rate to get cycles per clock. 2) multiply by 2**20
        fr_rate = int(float(fringe_rate) / self.config['feng_clk'] * (2**(bitshift_schedule + fringe_rate_bits-1)))

        cnts = self.ffpgas[ffpga_n].read_uint('delay_tr_status%i'%feng_input)
        arm_cnt0 = cnts >> 16
        ld_cnt0 = cnts & 0xffff

        act_delay = (coarse_delay + float(fine_delay_i)/2**fine_delay_bits)/self.config['adc_clk']
        act_fringe_offset = float(fr_offset)/(2**fringe_offset_bits)*360 
        act_fringe_rate = float(fr_rate)/(2**(fringe_rate_bits+bitshift_schedule-1))*self.config['feng_clk']
        act_delay_rate = float(fine_delay_rate)/(2**(bitshift_schedule + fine_delay_rate_bits-1))

        if (delay != 0):
            if (fine_delay_i == 0) and (coarse_delay == 0): 
                self.floggers[ffpga_n].info('Requested delay is too small for this configuration (our resolution is too low). Setting delay to zero.')
            elif abs(fine_delay_i) > 2**(fine_delay_bits):
                log_runtimeerror('Internal logic error calculating fine delays.')
            elif abs(coarse_delay) > (2**(coarse_delay_bits)):
                log_runtimeerror(self.floggers[ffpga_n], 'Requested coarse delay (%es) is out of range (+-%es).' % (float(coarse_delay)/self.config['adc_clk'], float(2**(coarse_delay_bits-1))/self.config['adc_clk']))
            else:
                self.floggers[ffpga_n].info('Delay actually set to %e seconds.' % act_delay)
        if (delay_rate != 0):
            if fine_delay_rate == 0:
                self.floggers[ffpga_n].info('Requested delay rate too slow for this configuration. Setting delay rate to zero.')
            if (abs(fine_delay_rate) > 2**(fine_delay_rate_bits-1)):
                log_runtimeerror(self.floggers[ffpga_n], 'Requested delay rate out of range (+-%e).' % (2**(bitshift_schedule-1)))
            else:
                self.floggers[ffpga_n].info('Delay rate actually set to %e seconds per second.' % act_delay_rate) 

        if fringe_phase != 0:
            if fr_offset == 0: 
                self.floggers[ffpga_n].info('Requested fringe phase is too small for this configuration (we do not have enough resolution). Setting fringe phase to zero.')
            else:
                self.floggers[ffpga_n].info('Fringe offset actually set to %6.3f degrees.' % act_fringe_offset)

        if fringe_rate != 0:
            if fr_rate == 0: 
                self.floggers[ffpga_n].info('Requested fringe rate is too slow for this configuration. Setting fringe rate to zero.')
            else:
                self.floggers[ffpga_n].info('Fringe rate actually set to %e Hz.' % act_fringe_rate)

        # get the current mcnt for this feng:
        mcnt = self.mcnt_current_get(ant_str)

        # figure out the load time
        if ld_time < 0: 
            # User did not ask for a specific time; load now!
            # figure out the load-time mcnt:
            ld_mcnt = int(mcnt + self.config['mcnt_scale_factor']*(min_ld_time))
        else:
            if (ld_time < (time.time() + min_ld_time)):
                log_runtimeerror(self.syslogger, "Cannot load at a time in the past.")
            ld_mcnt = self.mcnt_from_time(ld_time)

#        if (ld_mcnt < (mcnt + self.config['mcnt_scale_factor']*min_ld_time)):
#            log_runtimeerror(self.syslogger, "This works out to a loadtime in the past! Logic error :(") 
        
        # setup the delays:
        self.ffpgas[ffpga_n].write_int('coarse_delay%i' % feng_input,coarse_delay)
        self.floggers[ffpga_n].debug("Set a coarse delay of %i clocks." % coarse_delay)
        # fine delay (LSbs) is fraction of a cycle * 2^15 (16 bits allocated, signed integer). 
        # increment fine_delay by MSbs much every FPGA clock cycle shifted 2**20???
        self.ffpgas[ffpga_n].write('a1_fd%i' % feng_input,struct.pack('>hh', fine_delay_rate,fine_delay_i))
        self.floggers[ffpga_n].debug("Wrote %4x to fine_delay and %4x to fine_delay_rate register a1_fd%i." % (fine_delay_i, fine_delay_rate, feng_input))
        
        # setup the fringe rotation
        # LSbs is offset as a fraction of a cycle in fix_16_15 (1 = pi radians ; -1 = -1radians). 
        # MSbs is fringe rate as fractional increment to fr_offset per FPGA clock cycle as fix_16.15. FPGA divides this rate by 2**20 internally.
        self.ffpgas[ffpga_n].write('a0_fd%i'%feng_input,struct.pack('>hh',fr_rate,fr_offset))  
        self.floggers[ffpga_n].debug("Wrote %4x to fringe_offset and %4x to fringe_rate register a0_fd%i."%(fr_offset,fr_rate,feng_input))
        #print 'Phase offset: %2.3f (%i), phase rate: %2.3f (%i).'%(fringe_phase,fr_offset,fringe_rate,fr_rate)

        # set the load time:
        # MSb (load-it! bit) is pos-edge triggered.
        self.ffpgas[ffpga_n].write_int('ld_time_lsw%i' % feng_input, (ld_mcnt&0xffffffff))
        self.ffpgas[ffpga_n].write_int('ld_time_msw%i' % feng_input, (ld_mcnt>>32)&0x7fffffff)
        self.ffpgas[ffpga_n].write_int('ld_time_msw%i' % feng_input, (ld_mcnt>>32)|(1<<31))

        if ld_check == False:
            return {
                'act_delay': act_delay,
                'act_fringe_offset': act_fringe_offset,
                'act_fringe_rate': act_fringe_rate,
                'act_delay_rate': act_delay_rate}

        # check that it loaded correctly:
        # wait 'till the time has elapsed
        sleep_time=self.time_from_mcnt(ld_mcnt) - self.time_from_mcnt(mcnt)
        self.floggers[ffpga_n].debug('waiting %2.3f seconds (now: %i, ldtime: %i)' % (sleep_time, self.time_from_mcnt(ld_mcnt), self.time_from_mcnt(mcnt)))
        time.sleep(sleep_time)

        cnts = self.ffpgas[ffpga_n].read_uint('delay_tr_status%i' % feng_input)
        if (arm_cnt0 == (cnts>>16)):
            if (cnts>>16)==0:
                log_runtimeerror(self.floggers[ffpga_n], 'Ant %s (Feng %i on %s) appears to be held in master reset. Load failed.' % (ant_str, feng_input, self.fsrvs[ffpga_n]))
            else:
                log_runtimeerror(self.floggers[ffpga_n], 'Ant %s (Feng %i on %s) did not arm. Load failed.' % (ant_str, feng_input, self.fsrvs[ffpga_n]))
        if (ld_cnt0 >= (cnts & 0xffff)):
            after_mcnt = self.mcnt_current_get(ant_str)
            print 'before: %i, target: %i, after: %i' % (mcnt, ld_mcnt, after_mcnt)
            print 'start: %10.3f, target: %10.3f, after: %10.3f' % (self.time_from_mcnt(mcnt), self.time_from_mcnt(ld_mcnt), self.time_from_mcnt(after_mcnt))
            if after_mcnt > ld_mcnt:
                log_runtimeerror(self.floggers[ffpga_n], 'We missed loading the registers by about %4.1f ms.' % ((after_mcnt-ld_mcnt)/self.config['mcnt_scale_factor']*1000))
            else:
                log_runtimeerror(self.floggers[ffpga_n], 'Ant %s (Feng %i on %s) did not load correctly for an unknown reason.' % (ant_str, feng_input, self.fsrvs[ffpga_n]))

        return {
            'act_delay': act_delay,
            'act_fringe_offset': act_fringe_offset,
            'act_fringe_rate': act_fringe_rate,
            'act_delay_rate': act_delay_rate}
        
    def fr_delay_set_all(self,coeffs={},ld_time=-1):
        """Configures all antennas to a delay in seconds using both the coarse and the fine delay. Also configures the fringe rotation components. This is a blocking call.
        It will wait 'till load time and verify that things worked as expected. \n
        Load time, in unix seconds, is optional; if not specified, load ASAP.\n
        The coeffs dictionary should contain entries for each input (ant_str), each of which is a dictionary containing the following key words:\n
        \t fringe_offset is in degrees.\n
        \t fringe_rate is in cycles per second (Hz).\n
        \t delay is in seconds.\n
        \t delay_rate is unitless (eg seconds per second).\n
        Notes: \n
        DOES NOT ACCOUNT FOR WRAPPING MCNT.\n
        IS A ONCE-OFF UPDATE (no babysitting by software)\n"""
        #TODO: Test this function!

        fine_delay_bits=16
        coarse_delay_bits=16
        fine_delay_rate_bits=16
        fringe_offset_bits=16
        fringe_rate_bits=16

        bitshift_schedule=23
        
        min_ld_time = 0.05*self.config['n_inputs'] #assume we're able to set and check all the registers in 100ms

        assert(len(coeffs)==self.config['n_inputs'])
        locs=[]
        arm_cnt_before=[]
        ld_cnt_before=[]
        rv={}

        #get the current system mcnt:
        mcnt=self.mcnt_current_get(self.map_input_to_ant(0))
        #figure out the load time
        if ld_time < 0: 
            #figure out the load-time mcnt:
            ld_mcnt=int(mcnt + self.config['mcnt_scale_factor']*(min_ld_time))
        else:
            if (ld_time < (time.time() + min_ld_time)):
                log_runtimeerror(self.syslogger, "fr_delay_set_all - Cannot load at a time in the past.")
            ld_mcnt=self.mcnt_from_time(ld_time)
        if (ld_mcnt < (mcnt + self.config['mcnt_scale_factor']*min_ld_time)):
            raise RuntimeError("fr_delay_set_all - This works out to a loadtime in the past!")

        for ant_str,ant_coeffs in coeffs.iteritems():
            locs.append(self.get_ant_str_location(ant_str))
            ffpga_n,xfpga_n,fxaui_n,xxaui_n,feng_input = locs[-1]

            delay=ant_coeffs['delay']
            delay_rate=ant_coeffs['delay_rate']
            fringe_phase=ant_coeffs['fringe_phase']
            fringe_rate=ant_coeffs['fringe_rate']

            #delays in terms of ADC clock cycles:
            delay_n=delay*self.config['adc_clk']    #delay in clock cycles
            #coarse_delay = int(numpy.round(delay_n)) #delay in whole clock cycles #good for rev 369.
            coarse_delay = int(delay_n) #delay in whole clock cycles #testing for rev370
            fine_delay = (delay_n-coarse_delay)    #delay remainder. need a negative slope for positive delay
            fine_delay_i = int(fine_delay*(2**(fine_delay_bits)))  #16 bits of signed data over range 0 to +pi
        
            fine_delay_rate=int(float(delay_rate) * (2**(bitshift_schedule + fine_delay_rate_bits-1))) 

            #figure out the fringe as a fraction of a cycle        
            fr_offset=int((fringe_phase%360)/float(360) * (2**(fringe_offset_bits)))
            #figure out the fringe rate. Input is in cycles per second (Hz). 1) divide by brd clock rate to get cycles per clock. 2) multiply by 2**20
            fr_rate = int(float(fringe_rate) / self.config['feng_clk'] * (2**(bitshift_schedule + fringe_rate_bits-1)))


            cnts=self.ffpgas[ffpga_n].read_uint('delay_tr_status%i'%feng_input)
            arm_cnt_before.append(cnts>>16)
            ld_cnt_before.append(cnts&0xffff)

            act_delay=(coarse_delay + float(fine_delay_i)/2**fine_delay_bits)/self.config['adc_clk']
            act_fringe_offset = float(fr_offset)/(2**fringe_offset_bits)*360 
            act_fringe_rate = float(fr_rate)/(2**(fringe_rate_bits+bitshift_schedule-1))*self.config['feng_clk']
            act_delay_rate = float(fine_delay_rate)/(2**(bitshift_schedule + fine_delay_rate_bits-1))

            rv[ant_str]={}
            rv[ant_str]['act_delay']=act_delay
            rv[ant_str]['act_delay_rate']=act_delay_rate
            rv[ant_str]['act_fringe_phase']=act_fringe_offset
            rv[ant_str]['act_fringe_rate']=act_fringe_rate

            if (delay != 0):
                if (fine_delay_i==0) and (coarse_delay==0): 
                    self.floggers[ffpga_n].error('fr_delay_set_all - Requested delay is too small for this configuration (our resolution is too low).')
                elif abs(fine_delay_i) > 2**(fine_delay_bits):
                    log_runtimeerror(self.floggers[ffpga_n], 'fr_delay_set_all - Internal logic error calculating fine delays.')
                elif abs(coarse_delay) > (2**(coarse_delay_bits)):
                    log_runtimeerror(self.floggers[ffpga_n], 'fr_delay_set_all - Requested coarse delay (%es) is out of range (+-%es).' % (float(coarse_delay)/self.config['adc_clk'], float(2**(coarse_delay_bits-1))/self.config['adc_clk']))
            self.floggers[ffpga_n].info('fr_delay_set_all - Delay actually set to %e seconds.'%act_delay)

            if (delay_rate != 0):
                if (fine_delay_rate==0): self.floggers[ffpga_n].error('fr_delay_set_all - Requested delay rate too slow for this configuration.')
                if (abs(fine_delay_rate) > 2**(fine_delay_rate_bits-1)):
                    log_runtimeerror(self.floggers[ffpga_n], 'fr_delay_set_all - Requested delay rate out of range (+-%e).' % (2**(bitshift_schedule-1)))
            self.floggers[ffpga_n].warn('fr_delay_set_all - Delay rate actually set to %e seconds per second.'%act_delay_rate) 

            if (fringe_phase !=0):
                if (fr_offset == 0): 
                    self.floggers[ffpga_n].error('fr_delay_set_all - Requested fringe phase is too small for this configuration (we do not have enough resolution).')
            self.floggers[ffpga_n].info('fr_delay_set_all - Fringe offset actually set to %6.3f degrees.'%act_fringe_offset)

            if (fringe_rate != 0):
                if (fr_rate==0): 
                    self.floggers[ffpga_n].error('fr_delay_set_all - Requested fringe rate is too slow for this configuration.')
            self.floggers[ffpga_n].info('fr_delay_set_all - Fringe rate actually set to %e Hz.'%act_fringe_rate)

            #setup the delays:
            self.ffpgas[ffpga_n].write_int('coarse_delay%i'%feng_input,coarse_delay)
            self.floggers[ffpga_n].debug("fr_delay_set_all - Set a coarse delay of %i clocks."%coarse_delay)
            #fine delay (LSbs) is fraction of a cycle * 2^15 (16 bits allocated, signed integer). 
            #increment fine_delay by MSbs much every FPGA clock cycle shifted 2**20???
            self.ffpgas[ffpga_n].write('a1_fd%i'%feng_input,struct.pack('>hh',fine_delay_rate,fine_delay_i))
            self.floggers[ffpga_n].debug("fr_delay_set_all - Wrote %4x to fine_delay and %4x to fine_delay_rate register a1_fd%i."%(fine_delay_i,fine_delay_rate,feng_input))
            
            #print 'Coarse delay: %i, fine delay: %2.3f (%i), delay_rate: %2.2f (%i).'%(coarse_delay,fine_delay,fine_delay_i,delay_rate,fine_delay_rate)

            #setup the fringe rotation
            #LSbs is offset as a fraction of a cycle in fix_16_15 (1 = pi radians ; -1 = -1radians). 
            #MSbs is fringe rate as fractional increment to fr_offset per FPGA clock cycle as fix_16.15. FPGA divides this rate by 2**20 internally.
            self.ffpgas[ffpga_n].write('a0_fd%i'%feng_input,struct.pack('>hh',fr_rate,fr_offset))  
            self.floggers[ffpga_n].debug("fr_delay_set_all - Wrote %4x to fringe_offset and %4x to fringe_rate register a0_fd%i."%(fr_offset,fr_rate,feng_input))
            #print 'Phase offset: %2.3f (%i), phase rate: %2.3f (%i).'%(fringe_phase,fr_offset,fringe_rate,fr_rate)

            #set the load time:
            self.ffpgas[ffpga_n].write_int('ld_time_lsw%i'%feng_input,(ld_mcnt&0xffffffff))
            self.ffpgas[ffpga_n].write_int('ld_time_msw%i'%feng_input,(ld_mcnt>>32)|(1<<31))
            self.ffpgas[ffpga_n].write_int('ld_time_msw%i'%feng_input,(ld_mcnt>>32)&0x7fffffff)

        #check that they all loaded correctly:
        #wait 'till the time has elapsed
        sleep_time=self.time_from_mcnt(ld_mcnt) - self.time_from_mcnt(mcnt)
        #print 'waiting %2.3f seconds (now: %i, ldtime: %i)'%(sleep_time, self.time_from_mcnt(ld_mcnt),self.time_from_mcnt(mcnt))
        time.sleep(sleep_time)

        for input_n,(ffpga_n,xfpga_n,fxaui_n,xxaui_n,feng_input) in enumerate(locs):
            cnts=self.ffpgas[ffpga_n].read_uint('delay_tr_status%i'%feng_input)

            if (arm_cnt_before[input_n] == cnts>>16): 
                if (cnts>>16)==0:
                    log_runtimeerror(self.floggers[ffpga_n], 'fr_delay_set_all - Ant %s (Feng %i on %s) appears to be held in master reset. Load failed.' % (self.map_input_to_ant(input_n),feng_input,self.fsrvs[ffpga_n]))
                else:
                    log_runtimeerror(self.floggers[ffpga_n], 'fr_delay_set_all - Ant %s (Feng %i on %s) did not arm. Load failed.'%(self.map_input_to_ant(input_n),feng_input,self.fsrvs[ffpga_n]))
            if (ld_cnt_before[input_n] >= (cnts&0xffff)): 
                after_mcnt=self.mcnt_current_get(self.map_input_to_ant(input_n)) 
                #print 'before: %i, target: %i, after: %i'%(mcnt,ld_mcnt,after_mcnt)
                #print 'start: %10.3f, target: %10.3f, after: %10.3f'%(self.time_from_mcnt(mcnt),self.time_from_mcnt(ld_mcnt),self.time_from_mcnt(after_mcnt))
                if after_mcnt > ld_mcnt:
                    log_runtimeerror(self.floggers[ffpga_n], 'fr_delay_set_all - We missed loading the registers by about %4.1f ms.'%((after_mcnt-ld_mcnt)/self.config['mcnt_scale_factor']*1000))
                else:
                    log_runtimeerror(self.floggers[ffpga_n], 'fr_delay_set_all - Ant %s (Feng %i on %s) did not load correctly for an unknown reason.'%(ant_str,feng_input,self.fsrvs[ffpga_n]))
        return rv
        #return {
        #    'act_delay': act_delay,
        #    'act_fringe_offset': act_fringe_offset,
        #    'act_fringe_rate': act_fringe_rate,
        #    'act_delay_rate': act_delay_rate}

    def time_from_mcnt(self,mcnt):
        """Returns the unix time UTC equivalent to the input MCNT. Does NOT account for wrapping MCNT."""
        return self.config['sync_time']+float(mcnt)/self.config['mcnt_scale_factor']
        
    def mcnt_from_time(self,time_seconds):
        """Returns the mcnt of the correlator from a given UTC system time (seconds since Unix Epoch). Accounts for wrapping mcnt."""
        return int((time_seconds - self.config['sync_time'])*self.config['mcnt_scale_factor'])%(2**self.config['mcnt_bits'])

        #print 'Current Feng mcnt: %16X, uptime: %16is, target mcnt: %16X (%16i)'%(current_mcnt,uptime,target_pkt_mcnt,target_pkt_mcnt)
        
    def time_from_pcnt(self, pcnt):
        """Returns the unix time UTC equivalent to the input packet timestamp. Does NOT account for wrapping pcnt."""
        return self.config['sync_time'] + (float(pcnt) / float(self.config['pcnt_scale_factor']))
        
    def pcnt_from_time(self, time_seconds):
        """Returns the packet timestamp from a given UTC system time (seconds since Unix Epoch). Accounts for wrapping pcnt."""
        return int((time_seconds - self.config['sync_time'])*self.config['pcnt_scale_factor'])%(2**self.config['pcnt_bits'])

    def time_from_spead(self,spead_time):
        """Returns the unix time UTC equivalent to the input packet timestamp. Does not account for wrapping timestamp counters."""
        return self.config['sync_time']+float(spead_time)/float(self.config['spead_timestamp_scale_factor'])
        
    def spead_timestamp_from_time(self,time_seconds):
        """Returns the packet timestamp from a given UTC system time (seconds since Unix Epoch). Accounts for wrapping timestamp."""
        return int((time_seconds - self.config['sync_time'])*self.config['spead_timestamp_scale_factor'])%(2**(self.config['spead_flavour'][1]))

    def acc_n_set(self,n_accs=-1,spead_update=True):
        """Set the Accumulation Length (in # of spectrum accumulations). If not specified, get the config from the config file."""
        if n_accs<0: n_accs=self.config['acc_len']
        n_accs_vacc = int(round(float(n_accs) / float(self.config['xeng_acc_len'])))
        self.xwrite_int_all('acc_len', n_accs_vacc)
        self.syslogger.info("Set number of VACC accumulations to %5i."%n_accs_vacc)
        self.vacc_sync() #this is needed in case we decrease the accumulation period on a new_acc transition where some vaccs would then be out of sync
        time.sleep(self.acc_time_get()+0.1)
        self.rst_status_and_count() #reset all errors (resyncing VACC will introduce some)
        if spead_update: 
            self.spead_time_meta_issue()

    def acc_n_get(self):
        n_accs_all=numpy.array(self.xread_uint_all('acc_len'))*self.config['xeng_acc_len']
        n_accs=n_accs_all[0]
        for xn,xeng in enumerate(self.xsrvs):
            if n_accs_all[xn] != n_accs:
                log_runtimeerror(self.syslogger, 'Not all boards have the same accumulation length set!')
        return n_accs
    
    def acc_time_get(self):
        n_accs = self.acc_n_get()
        return float(self.config['n_chans'] * n_accs) / self.config['bandwidth']

    def acc_time_set(self, acc_time = -1):
        """Set the accumulation time in seconds, as closely as we can. If not specified, use the default from the config file. Returns the actual accumulation time in seconds."""
        if acc_time < 0: acc_time = self.config['int_time']
        n_accs = int(acc_time * self.config['bandwidth'] / float(self.config['n_chans']))
        self.acc_n_set(n_accs = n_accs)
        act_acc_time = self.acc_time_get()
        if act_acc_time != acc_time:
            self.syslogger.warn("Set accumulation period to %fs (closest we could get to %fs)." % (act_acc_time, acc_time))
        else:
            self.syslogger.info("Set accumulation period to %fs." % act_acc_time)
        return act_acc_time

    def feng_brd_id_set(self):
        """Sets the F engine boards' antenna indices. (Numbers the board_id software register.)"""
        for f,fpga in enumerate(self.ffpgas):
            fpga.write_int('board_id', f)
        self.syslogger.info('F engine board IDs set ok.')

    def xeng_brd_id_set(self):
        """Sets the X engine boards' board_ids. This should not be necessary on newwer designs with XAUI links which extract this info from the 10GbE IP addresses."""
        for f,fpga in enumerate(self.xfpgas):
            fpga.write_int('board_id',f)
        self.syslogger.info('X engine board IDs set ok.')

# This function is deprecated since ant_str introduced. use get_ant_str_location instead.
#    def get_ant_location(self, ant, pol='x'):
#        " Returns the (ffpga_n,xfpga_n,fxaui_n,xxaui_n,feng_input) location for a given antenna/pol. Ant is integer, as are all returns."
#        #tested ok corr-0.5.0 2010-10-26
#        if ant > self.config['n_ants']: 
#            raise RuntimeError("There is no antenna %i in this design (total %i antennas)."%(ant,self.config['n_ants']))
#        ffpga_n  = ant/self.config['f_per_fpga']
#        fxaui_n  = ant/self.config['n_ants_per_xaui']%self.config['n_xaui_ports_per_ffpga']
#        xfpga_n  = ant/self.config['n_ants_per_xaui']/self.config['n_xaui_ports_per_xfpga']
#        xxaui_n  = ant/self.config['n_ants_per_xaui']%self.config['n_xaui_ports_per_xfpga']
#        feng_input = ant%(self.config['f_per_fpga'])*self.config['n_pols'] + self.config['pol_map'][pol]
#        return (ffpga_n,xfpga_n,fxaui_n,xxaui_n,feng_input)

    def map_ant_to_input(self,ant_str):
        """Maps an antenna string to an input number."""
        try:
            input_n = self.config._get_ant_mapping_list().index(ant_str)
            return input_n
        except:
            log_runtimeerror(self.syslogger, 'Unable to map antenna %s.'%ant_str)
     
    def map_input_to_ant(self,input_n):
        """Maps an input number to an antenna string."""
        return self.config._get_ant_mapping_list()[input_n]

    def get_ant_str_location(self, ant_str):
        """ Returns the (ffpga_n,xfpga_n,fxaui_n,xxaui_n,feng_input) location for a given antenna."""
        return self.get_input_location(self.map_ant_to_input(ant_str))
        
    def get_xeng_location(self, xeng_n):
        """ Returns the (xfpga_n,xeng_core) location for a given x engine."""
        if xeng_n>=self.config['n_xeng']:
            raise RuntimeError("There are only %i X engines in this design! Xeng %i is invalid."%(self.config['n_xeng'],xeng_n))
        return xeng_n/self.config['x_per_fpga'],xeng_n%self.config['x_per_fpga']

    def get_input_location(self, input_n):
        " Returns the (ffpga_n,xfpga_n,fxaui_n,xxaui_n,feng_input) location for a given system-wide input number."
        if input_n > self.config['n_inputs'] or input_n < 0: 
            raise RuntimeError("There is no input %i in this design (total %i inputs)."%(input_n,self.config['n_inputs']))
        ant = input_n / 2 #dual-pol ant, as transmitted across XAUI links
        ffpga_n  = ant/self.config['f_per_fpga']
        fxaui_n  = ant/self.config['n_ants_per_xaui']%self.config['n_xaui_ports_per_ffpga']
        xfpga_n  = ant/self.config['n_ants_per_xaui']/self.config['n_xaui_ports_per_xfpga']
        xxaui_n  = ant/self.config['n_ants_per_xaui']%self.config['n_xaui_ports_per_xfpga']
        feng_input = input_n%self.config['f_inputs_per_fpga'] 
        return (ffpga_n,xfpga_n,fxaui_n,xxaui_n,feng_input)

    def config_roach_10gbe_ports(self):
        """Configures 10GbE ports on roach X (and F, if needed) engines for correlator data exchange using TGTAP."""
        if self.config['feng_out_type'] == '10gbe':
            self.fwrite_int_all('gbe_port', self.config['10gbe_port'])
            for fn,fpga in enumerate(self.ffpgas):
                for fc in range(self.config['n_xaui_ports_per_ffpga']):
                    start_addr=self.config['10gbe_ip']-(self.config['n_xaui_ports_per_ffpga'] * self.config['n_feng'])
                    start_port=self.config['10gbe_port']
                    mac,ip,port=self.get_roach_gbe_conf(start_addr,(fn*self.config['n_xaui_ports_per_ffpga']+fc),start_port)
                    fpga.tap_start('gbe%i'%fc,'gbe%i'%fc,mac,ip,port)
                    # THIS LINE SHOULD NOT BE REQUIRED WITH DAVE'S UPCOMING 10GBE CORE MODS
                    # Set the Xengines' starting IP address.
                    fpga.write_int('gbe_ip%i'%fc, self.config['10gbe_ip'])
                    self.floggers[fn].info("Configured gbe%i core's IP address to %s"%(fc,ip2str(ip)))
        else:
            self.xwrite_int_all('gbe_port', self.config['10gbe_port'])

        for f,fpga in enumerate(self.xfpgas):
            for x in range(self.config['n_xaui_ports_per_xfpga']):
                start_addr=self.config['10gbe_ip']
                start_port=self.config['10gbe_port']
                mac,ip,port=self.get_roach_gbe_conf(start_addr,(f*self.config['n_xaui_ports_per_xfpga']+x),start_port)
                fpga.tap_start('gbe%i'%x,'gbe%i'%x,mac,ip,port)
                self.xloggers[f].info("Configured gbe%i core's IP address to %s"%(x,ip2str(ip)))
                # THIS LINE SHOULD NOT BE REQUIRED WITH DAVE'S UPCOMING 10GBE CORE MODS
                # Assign an IP address to each XAUI port's associated 10GbE core.
                if self.config['feng_out_type'] == 'xaui':
                    fpga.write_int('gbe_ip%i'%x, ip)
        self.syslogger.info('All 10GbE cores configured.')
                        
#    def config_roach_10gbe_ports_static(self):
#        """STATICALLY configures 10GbE ports on roach X engines for correlator data exchange. Will not work with 10GbE output (we don't know the receiving computer's MAC)."""
#        arp_table=[(2**48)-1 for i in range(256)]
#
#        for f,fpga in enumerate(self.xfpgas):
#            for x in range(self.config['n_xaui_ports_per_xfpga']):
#                start_addr=self.config['10gbe_ip']
#                start_port=self.config['10gbe_port']
#                mac,ip,port=self.get_roach_gbe_conf(start_addr,(f*self.config['n_xaui_ports_per_xfpga']+x),start_port)
#                arp_table[ip%256]=mac
#
#        for f,fpga in enumerate(self.xfpgas):
#            for x in range(self.config['n_xaui_ports_per_xfpga']):
#                mac,ip,port=self.get_roach_gbe_conf(start_addr,(f*self.config['n_xaui_ports_per_xfpga']+x),start_port)
#                fpga.config_10gbe_core('gbe%i'%x,mac,ip,port,arp_table)
#                # THIS LINE SHOULD NOT BE REQUIRED WITH DAVE'S UPCOMING 10GBE CORE MODS
#                # Assign an IP address to each XAUI port's associated 10GbE core.
#                fpga.write_int('gbe_ip%i'%x, ip)

    def config_udp_output(self,dest_ip_str=None,dest_port=None):
        """Configures the destination IP and port for X engine output. dest_port and dest_ip are optional parameters to override the config file defaults. dest_ip is string in dotted-quad notation."""
        if dest_ip_str==None:
            dest_ip_str=self.config['rx_udp_ip_str']
        else:
            self.config['rx_udp_ip_str']=dest_ip_str
            self.config['rx_udp_ip']=struct.unpack('>L',socket.inet_aton(dest_ip_str))[0]
            self.config['rx_meta_ip_str']=dest_ip_str
            self.config['rx_meta_ip']=struct.unpack('>L',socket.inet_aton(dest_ip_str))[0]

        if dest_port==None:
            dest_port=self.config['rx_udp_port']
        else:
            self.config['rx_udp_port']=dest_port

        self.xwrite_int_all('gbe_out_ip',struct.unpack('>L',socket.inet_aton(dest_ip_str))[0])
        self.xwrite_int_all('gbe_out_port',dest_port)
        self.syslogger.info("Correlator output configured to %s:%i." % (dest_ip_str, dest_port))
        #self.xwrite_int_all('gbe_out_pkt_len',self.config['rx_pkt_payload_len']) now a compile-time option

        #Temporary for correlators with separate gbe core for output data:
        #for x in range(self.config['x_per_fpga']):
        #    for f,fpga in enumerate(self.xfpgas):
        #        ip_offset=self.config['10gbe_ip']+len(self.xfpgas)*self.config['x_per_fpga']
        #        mac,ip,port=self.get_roach_gbe_conf(ip_offset,(f*self.config['n_xaui_ports_per_xfpga']+x),self.config['rx_udp_port'])
        #        fpga.tap_start('gbe_out%i'%x,mac,ip,port)

    def enable_udp_output(self):
        """Just calls tx_start. Here for backwards compatibility."""
        self.tx_start()

    def disable_udp_output(self):
        """Just calls tx_stop. Here for backwards compatibility."""
        self.tx_stop()

    def deconfig_roach_10gbe_ports(self):
        """Stops tgtap drivers for the X (and possibly F) engines."""
        if self.config['feng_out_type'] == '10gbe':
            for f,fpga in enumerate(self.ffpgas):
                for x in range(self.config['n_xaui_ports_per_ffpga']):
                    fpga.tap_stop('gbe%i'%x)

        for f,fpga in enumerate(self.xfpgas):
            for x in range(self.config['n_xaui_ports_per_xfpga']):
                fpga.tap_stop('gbe%i'%x)

    def vacc_ld_status_get(self):
        "Grabs and decodes the VACC load status registers from all the correlator's X-engines."
        rv = {}
        for xfpga_num, server in enumerate(self.xsrvs):
            rv[server] = {}
            for xeng_location in range(self.config['x_per_fpga']):
                reg_data = self.xfpgas[xfpga_num].read_uint('vacc_ld_status%i' % xeng_location)
                rv[server]['arm_cnt%i' % xeng_location] = reg_data >> 16
                rv[server]['ld_cnt%i'  % xeng_location] = reg_data & 0xffff
        return rv

    def vacc_sync(self, ld_time = -1, network_wait = 0.5, min_load_time = 1.0):
        """Arms all vector accumulators to start accumulating at a given time. If no time is specified, after about a second from now. ld_time is in seconds since unix epoch."""
        #rev: 2011-02-02 JRM:   added warning calc for leadtime. fewer time.time() calls.
        min_ld_time = min_load_time

        def load_vacc_status(correlator):
            ld_status_reg_data = correlator.vacc_ld_status_get()
            rv = {}
            for xfpga_num, server in enumerate(correlator.xsrvs):
                server_data = {}
                server_data['xfpga_number'] = xfpga_num
                server_data['xengs'] = []
                for xeng_location in range(correlator.config['x_per_fpga']):
                    xeng_index = xeng_location + (correlator.config['x_per_fpga'] * xfpga_num)
                    tmp = {}
                    tmp['xeng_number'] = xeng_location
                    tmp['arm_cnt'] = ld_status_reg_data[server]['arm_cnt%i' % xeng_location]
                    tmp['ld_cnt'] =  ld_status_reg_data[server]['ld_cnt%i'  % xeng_location]
                    tmp['xeng_index'] = xeng_index
                    server_data['xengs'].append(tmp)
                rv[server] = server_data 
            return rv

        def print_vacc_status(data):
            print '\n***************************'
            for key, server in data.items():
                print 'Xeng_fpga(%s, %i):' % (key, server['xfpga_number'])
                for xeng in server['xengs']:
                    print '\txeng(%i) xeng_index(%i) arm_cnt(%i) ld_cnt(%i)' % (xeng['xeng_number'], xeng['xeng_index'], xeng['arm_cnt'], xeng['ld_cnt'])
            print '***************************\n'

        # read the vacc status registers before syncing
        vacc_status_before = load_vacc_status(self)
        #print_vacc_status(vacc_status_before)
        reset_required = False
        for key, server in vacc_status_before.items():
            for xeng in server['xengs']:
                if xeng['arm_cnt'] != xeng['ld_cnt']: 
                    self.xloggers[server['xfpga_number']].warning("VACC syncing: xfpga(%i), xeng(%i) - arm count(%i) and load count(%i) differ by %i, resetting VACCs." % (server['xfpga_number'], xeng['xeng_number'], xeng['arm_cnt'], xeng['ld_cnt'], xeng['arm_cnt'] - xeng['ld_cnt']))
                    reset_required = True
        # reset the vaccs if any were out of alignment
        if reset_required:
            print 'Resetting vaccs...'
            self.rst_vaccs()
            vacc_status_before = load_vacc_status(self)
            for k, s in vacc_status_before.items():
                for x in s['xengs']:
                    if (x['arm_cnt'] != 0) or (x['ld_cnt'] != 0):
                        log_runtimeerror(self.syslogger, 'Xeng(%i) on %s: could not reset vacc correctly. arm_cnt(%i) != 0? ld_cnt(%i) != 0?' % (x['xeng_number'], k, x['arm_cnt'], x['ld_cnt']))
            #print_vacc_status(vacc_status_before)

        # get current pcnt from f-engines
        pcnt_before = self.pcnt_current_get()

        # figure out the load time as a pcnt
        time_start = time.time()
        if ld_time < 0:
            ld_time = time_start + min_ld_time
        if ld_time < time_start + min_ld_time:
            log_runtimeerror(self.syslogger, "Cannot load at a time in the past. Need at least %2.2f seconds leadtime." % min_ld_time)
        pcnt_ld = self.pcnt_from_time(ld_time)
        #print 'pcnt_ld(%i) gives load time(%s)' % (pcnt_ld, time.ctime(ld_time))
        if pcnt_ld <= pcnt_before:
            log_runtimeerror(self.syslogger, "Error occurred. Cannot load at a time in the past.")
        if pcnt_ld > ((2**48)-1):
            print 'Warning: the 48-bit pcnt has wrapped!'
            self.syslogger.warning("Looks like the 48bit pcnt has wrapped.")
            pcnt_ld = pcnt_ld & 0xffffffffffff

        # round to the nearest spectrum cycle. this is: n_ants*(n_chans_per_xeng)*(xeng_acc_len) clock cycles.
        # pcnts themselves are rounded to nearest xeng_acc_len.
        # round_target = self.config['n_ants'] * self.config['n_chans'] / self.config['n_xeng']
        # However, hardware rounds to n_chans, irrespective of anything else (oops!).
        # pcnt_ld = (pcnt_ld / self.config['n_chans']) * self.config['n_chans']

        # arm the x-engine vaccs
        self.xwrite_int_all('vacc_time_msw', (pcnt_ld >> 32) + (0 << 31))
        self.xwrite_int_all('vacc_time_lsw', (pcnt_ld &  0xffffffff))
        self.xwrite_int_all('vacc_time_msw', (pcnt_ld >> 32) + (1 << 31))
        self.xwrite_int_all('vacc_time_msw', (pcnt_ld >> 32) + (0 << 31))

        # wait for the load time to elapse
        #print 'waiting %2.3f seconds' % sleep_time
        time.sleep(self.time_from_pcnt(pcnt_ld) - self.time_from_pcnt(pcnt_before))
        # allow for the fact that reading/writing over the network may take some time
        time.sleep(network_wait) # account for a crazy network latency
        pcnt_after = self.pcnt_current_get()
        """
        pcnt_difference = pcnt_after - pcnt_ld
        time_before = self.time_from_pcnt(pcnt_before)
        time_ld = self.time_from_pcnt(pcnt_ld)
        time_after = self.time_from_pcnt(pcnt_after)
        time_difference = time_after - time_ld
        print 'PCNT: before(%15i) target(%15i) after(%15i) after-target(%15i)' % (pcnt_before, pcnt_ld, pcnt_after, pcnt_difference)
        print 'TIME: before(%15.3f) target(%15.3f) after(%15.3f) after-target(%15.3f)' % (time_before, time_ld, time_after, time_difference)
        """

        # read the vacc ld register again after the load time has elapsed
        vacc_status_after = load_vacc_status(self)
        #print_vacc_status(vacc_status_after)

        # loop through the x-engines and check that their load counts incremented correctly
        for serverkey, server in vacc_status_after.items():
            server_status_before = vacc_status_before[serverkey]
            xeng_logger = self.xloggers[server['xfpga_number']]
            for xeng in server['xengs']:
                xeng_status_before = server_status_before['xengs'][xeng['xeng_number']]
                #print "xeng_index(%i) arm_cnt(%i) ld_cnt(%i)" % (xeng['xeng_index'], xeng['arm_cnt'], xeng['ld_cnt'])
                # the arm count should have increased
                if (xeng['arm_cnt'] == 0):
                    log_runtimeerror(xeng_logger, 'VACC %i on %s appears to be held in reset (arm count = 0).' % (xeng['xeng_number'], serverkey))
                if (xeng_status_before['arm_cnt'] == xeng['arm_cnt']):
                    log_runtimeerror(xeng_logger, 'VACC %i on %s did not arm (arm count didn''t increment).' % (xeng['xeng_number'], serverkey))
                # so should the load count
                #print "\nxeng_ldcnt_before(%i) xeng_ldcnt_after(%i)" % (xeng_status_before['ld_cnt'], xeng['ld_cnt'])
                sys.stdout.flush()
                if xeng['ld_cnt'] <= xeng_status_before['ld_cnt']:
                    if pcnt_after > pcnt_ld:
                        miss_ms = (self.time_from_pcnt(pcnt_after) - self.time_from_pcnt(pcnt_ld)) * 1000.
                        log_runtimeerror(xeng_logger, 'vacc_sync - We missed loading the registers by about %4.1f ms.' % miss_ms)
                    else:
                        raise RuntimeError('Xeng %i on %s did not load correctly for an unknown reason.' % (xeng['xeng_number'], serverkey))
                #print 'xeng(%s, %i) VACC armed correctly.' % (server, loc_xeng_n) 

#    def freq_to_chan(self,frequency):
#        """Returns the channel number where a given frequency is to be found. Frequency is in Hz."""
#TODO: Account for DDC
#        if frequency<0: 
#            frequency=self.config['bandwidth']+self.config['frequency']
#            #print 'you want',frequency
#        if frequency>self.config['bandwidth']: raise RuntimeError("that frequency is too high.")
#        return round(float(frequency)/self.config['bandwidth']*self.config['n_chans'])%self.config['n_chans']

    def get_adc_snapshots(self,ant_strs,trig_level=-1,sync_to_pps=True):
        """Retrieves raw ADC samples from the specified antennas. Optionally capture the data at the same time. Optionally set a trigger level."""
        return corr.snap.get_adc_snapshots(self,ant_strs,trig_level=trig_level,sync_to_pps=sync_to_pps)

    def get_quant_snapshot(self, ant_str, n_spectra = 1):
        """Retrieves quantised samples from the output of the FFT for user-specified antennas."""
        return corr.snap.get_quant_snapshot(self, ant_str, n_spectra = n_spectra)

    def calibrate_adc_snapshot(self,ant_str,raw_data,n_chans=256):
        """Calibrates ADC count raw voltage input in timedomain. Returns samples in mV and a spectrum of n_chans in dBm."""
        adc_v=raw_data*self.config['adc_v_scale_factor']/(10**((self.rf_status_get(ant_str)[1])/20.))
        n_accs=len(adc_v)/n_chans/2
        freqs=numpy.arange(n_chans)*float(self.config['bandwidth'])/n_chans #channel center freqs in Hz. #linspace(0,float(bandwidth),n_chans) returns incorrect numbers
        window=numpy.hamming(n_chans*2)
        spectrum=numpy.zeros(n_chans)
        for acc in range(n_accs):
            spectrum += numpy.abs((numpy.fft.rfft(adc_v[n_chans*2*acc:n_chans*2*(acc+1)]*window)[0:n_chans])) 
        spectrum  = 20*numpy.log10(spectrum/n_accs/n_chans*4.91)
        return {'freqs':freqs,'spectrum_dbm':spectrum,'adc_v':adc_v}


    def check_xaui_sync(self):
        """Checks if all F engines are in sync by examining mcnts at sync of incomming XAUI streams. \n
        If this test passes, it does not gaurantee that the system is indeed sync'd,
         merely that the F engines were reset between the same 1PPS pulses.
        Returns boolean true/false if system is in sync.
        """
        if self.config['feng_out_type'] != 'xaui':
            raise RuntimeError("According to your config file, you don't have any XAUI cables connected to your F engines!")
        max_mcnt_difference=4
        mcnts=dict()
        mcnts_list=[]
        mcnt_tot=0
        rv=True

        for ant in range(0,self.config['n_ants'],self.config['n_ants_per_xaui']):
            f = ant / self.config['n_ants_per_xaui'] / self.config['n_xaui_ports_per_xfpga']
            x = ant / self.config['n_ants_per_xaui'] % self.config['n_xaui_ports_per_xfpga']

            n_xaui=f*self.config['n_xaui_ports_per_xfpga']+x
            #print 'Checking antenna %i on fpga %i, xaui %i. Entry %i.'%(ant,f,x,n_xaui)
            mcnts[n_xaui]=dict()
            mcnts[n_xaui]['mcnt'] =self.xfpgas[f].read_uint('xaui_sync_mcnt%i'%x)
            mcnts_list.append(mcnts[n_xaui]['mcnt'])

        mcnts['mode']=statsmode(mcnts_list)
        if mcnts['mode']==0:
            log_runtimeerror(self.syslogger, "Too many XAUI links are receiving no data. Unable to produce a reliable mcnt result.")
        mcnts['modalmean']=numpy.mean(mcnts['mode'])

#        mcnts:['mean']=stats.mean(mcnts_list)
#        mcnts['median']=stats.median(mcnts_list)
#        print 'mean: %i, median: %i, modal mean: %i mode:'%(mcnts['mean'],mcnts['median'],mcnts['modalmean']),mcnts['mode']

        for ant in range(0,self.config['n_ants'],self.config['n_ants_per_xaui']):
            f = ant / self.config['n_ants_per_xaui'] / self.config['n_xaui_ports_per_xfpga']
            x = ant / self.config['n_ants_per_xaui'] % self.config['n_xaui_ports_per_xfpga']
            n_xaui=f*self.config['n_xaui_ports_per_xfpga']+x
            if mcnts[n_xaui]['mcnt']>(mcnts['modalmean']+max_mcnt_difference) or mcnts[n_xaui]['mcnt'] < (mcnts['modalmean']-max_mcnt_difference):
                rv=False
                self.syslogger.error('Sync check failed on %s, port %i with error of %i.'%(self.xservers[f],x,mcnts[n_xaui]['mcnt']-mcnts['modalmean']))
        return rv

    def rf_gain_set(self, ant_str, gain = None):
        """Enables the RF switch and configures the RF attenuators on KATADC boards. pol is ['x'|'y']. \n
        \t KATADC's valid range is -11.5 to 20dB. \n
        \t If no gain is specified, use the defaults from the config file."""
        #RF switch is in MSb.
        ffpga_n, xfpga_n, fxaui_n, xxaui_n, feng_input = self.get_ant_str_location(ant_str)
        input_n = self.map_ant_to_input(ant_str)
        if self.config['adc_type'] != 'katadc':
            log_runtimeerror(self.floggers[ffpga_n], "RF gain cannot be configured on ADC type %s."%self.config['adc_type'])
        if gain == None:
            gain = self.config['rf_gain_%s' % (input_n)] 
        if gain > 20 or gain < -11.5:
            log_runtimeerror(self.floggers[ffpga_n], "Invalid gain setting of %i. Valid range for KATADC is -11.5 to +20")
        self.ffpgas[ffpga_n].write_int('adc_ctrl%i' % feng_input, (1<<31) + int((20 - gain) * 2))
        #self.config.write('equalisation','rf_gain_%s'%(ant_str),gain)
        self.floggers[ffpga_n].info("KATADC %i RF gain set to %2.1f." % (feng_input, round(gain * 2) / 2))

    def rf_status_get(self,ant_str):
        """Grabs the current value of the RF attenuators and RF switch state for KATADC boards. 
            Returns (enabled,gain in dB)"""
        #RF switch is in MSb.
        if self.config['adc_type'] != 'katadc' : 
            self.syslogger.warn("Unsupported ADC type of %s. Only katadc is supported."%self.config['adc_type'])
            return (True,0.0)
        else:
            ffpga_n,xfpga_n,fxaui_n,xxaui_n,feng_input = self.get_ant_str_location(ant_str)
            value = self.ffpgas[ffpga_n].read_uint('adc_ctrl%i'%feng_input)
            return (bool(value&(1<<31)),20.0-(value&0x3f)*0.5)

    def rf_status_get_all(self):
        """Grabs the current status of the RF chain on all KATADC boards."""
        #RF switch is in MSb.
        #tested ok corr-0.5.0 2010-07-19
        rv={}
        for in_n,ant_str in enumerate(self.config._get_ant_mapping_list()):
            rv[ant_str]=self.rf_status_get(ant_str)
        return rv

    def rf_gain_set_all(self,gain=None):
        """Sets the RF gain configuration of all inputs to "gain". If no level is given, use the defaults from the config file."""
        for ant_str in self.config._get_ant_mapping_list():
            self.rf_gain_set(ant_str, gain)

    def rf_disable(self,ant_str):
        """Disable the RF switch on KATADC boards. pol is ['x'|'y']"""
        #tested ok corr-0.5.0 2010-08-07
        #RF switch is in MSb.
        ffpga_n,xfpga_n,fxaui_n,xxaui_n,feng_input = self.get_ant_str_location(ant_str)
        if self.config['adc_type'] != 'katadc' : 
            self.floggers[ffpga_n].warn("RF disable unsupported on ADC type of %s. Only katadc is supported at this time."%self.config['adc_type'])
        else:
            self.ffpgas[ffpga_n].write_int('adc_ctrl%i'%feng_input,self.ffpgas[ffpga_n].read_uint('adc_ctrl%i'%feng_input)&0x7fffffff)
            self.floggers[ffpga_n].info("Disabled RF frontend.")

    def rf_enable(self,ant_str):
        """Enable the RF switch on the KATADC board associated with requested antenna."""
        #RF switch is in MSb.
        ffpga_n,xfpga_n,fxaui_n,xxaui_n,feng_input = self.get_ant_str_location(ant_str)
        if self.config['adc_type'] != 'katadc' : 
            self.floggers[ffpga_n].warn("RF enable unsupported on ADC type of %s. Only katadc is supported at this time."%self.config['adc_type'])
        else:
            self.ffpgas[ffpga_n].write_int('adc_ctrl%i'%feng_input,self.ffpgas[ffpga_n].read_uint('adc_ctrl%i'%feng_input)|0x80000000)
            self.floggers[ffpga_n].info("Enabled RF frontend.")

    def eq_set_all(self, init_poly = [], init_coeffs = []):
        """Initialise all connected Fengines' EQs to given polynomial. If no polynomial or coefficients are given, use defaults from config file."""
        for in_n, ant_str in enumerate(self.config._get_ant_mapping_list()):
            self.eq_spectrum_set(ant_str = ant_str, init_coeffs = init_coeffs, init_poly = init_poly)
        self.syslogger.info('Set all EQ gains on all Fengs.')

    def eq_default_get(self,ant_str):
        "Fetches the default equalisation configuration from the config file and returns a list of the coefficients for a given input." 
        n_coeffs = self.config['n_chans']/self.config['eq_decimation']
        input_n  = self.map_ant_to_input(ant_str)

        if self.config['eq_default'] == 'coeffs':
            equalisation = self.config['eq_coeffs_%s'%(input_n)]

        elif self.config['eq_default'] == 'poly':
            poly = self.config['eq_poly_%i' % (input_n)]
            equalisation = numpy.polyval(poly, range(self.config['n_chans']))[self.config['eq_decimation']/2::self.config['eq_decimation']]
            if self.config['eq_type'] == 'complex':
                equalisation = [eq+0*1j for eq in equalisation]
        else: 
            raise RuntimeError("Your EQ type, %s, is not understood." % self.config['eq_type'])
                
        if len(equalisation) != n_coeffs:
            raise RuntimeError("Something's wrong. I have %i eq coefficients when I should have %i." % (len(equalisation), n_coeffs))
        return equalisation

    #def eq_tostr(self,poly)
    #    for term,coeff in enumerate(equalisation):
    #        print '''Retrieved default EQ (%s) for antenna %i%c: '''%(ant,pol,self.config['eq_default']),
    #        if term==(len(coeffs)-1): print '%i...'%(coeff),
    #        else: print '%ix^%i +'%(coeff,len(coeffs)-term-1),
    #        sys.stdout.flush()
    #    print ''

    def eq_spectrum_get(self,ant_str):
        """Retrieves the equaliser settings currently programmed in an F engine for the given antenna. Assumes equaliser of 16 bits. Returns an array of length n_chans."""
        ffpga_n,xfpga_n,fxaui_n,xxaui_n,feng_input = self.get_ant_str_location(ant_str)
        register_name='eq%i'%(feng_input)
        n_coeffs = self.config['n_chans']/self.config['eq_decimation']

        if self.config['eq_type'] == 'scalar':
            bd=self.ffpgas[ffpga_n].read(register_name,n_coeffs*2)
            coeffs=numpy.array(struct.unpack('>%ih'%n_coeffs,bd))
            nacexp=(numpy.reshape(coeffs,(n_coeffs,1))*numpy.ones((1,self.config['eq_decimation']))).reshape(self.config['n_chans'])
            return nacexp
            
        elif self.config['eq_type'] == 'complex':
            bd=self.ffpgas[ffpga_n].read(register_name,n_coeffs*4)
            coeffs=struct.unpack('>%ih'%(n_coeffs*2),bd)
            na=numpy.array(coeffs,dtype=numpy.float64)
            nac=na.view(dtype=numpy.complex128)
            nacexp=(numpy.reshape(nac,(n_coeffs,1))*numpy.ones((1,self.config['eq_decimation']))).reshape(self.config['n_chans'])
            return nacexp
            
        else:
            log_runtimeerror(self.syslogger, "Unable to interpret eq_type from config file. Expecting scalar or complex.")

    def eq_spectrum_set(self, ant_str, init_coeffs = [], init_poly = []):
        """
        Set a given antenna and polarisation equaliser to given co-efficients.
        Assumes equaliser of 16 bits.
        init_coeffs is list of length (n_chans / decimation_factor)."""
        # tested ok corr-0.5.0 2010-08-07
        ffpga_n, xfpga_n, fxaui_n, xxaui_n, feng_input = self.get_ant_str_location(ant_str)
        fpga = self.ffpgas[ffpga_n]
        register_name = 'eq%i' % (feng_input)
        n_coeffs = self.config['n_chans'] / self.config['eq_decimation']

        if init_coeffs == [] and init_poly == []: 
            coeffs = self.eq_default_get(ant_str)
        elif len(init_coeffs) == n_coeffs:
            coeffs = init_coeffs
        elif len(init_coeffs) == self.config['n_chans']:
            coeffs = init_coeffs[0::self.config['eq_decimation']]
            self.floggers[ffpga_n].warn("You specified %i EQ coefficients but your system only supports %i actual values. Only writing every %ith value."%(self.config['n_chans'],n_coeffs,self.config['eq_decimation']))
        elif len(init_coeffs)>0: 
            raise RuntimeError ('You specified %i coefficients, but there are %i EQ coefficients in this design.'%(len(init_coeffs),n_coeffs))
        else:
            coeffs = numpy.polyval(init_poly, range(self.config['n_chans']))[self.config['eq_decimation']/2::self.config['eq_decimation']]
        
        if self.config['eq_type'] == 'scalar':
            coeffs = numpy.real(coeffs) 
            if numpy.max(coeffs) > ((2**16)-1) or numpy.min(coeffs)<0:
                log_runtimeerror(self.floggers[ffpga_n], "Sorry, your scalar EQ settings are out of range!")
            coeff_str = struct.pack('>%iH'%n_coeffs,coeffs)
        elif self.config['eq_type'] == 'complex':
            if numpy.max(coeffs) > ((2**15)-1) or numpy.min(coeffs)<-((2**15)-1):
                log_runtimeerror(self.floggers[ffpga_n], "Sorry, your complex EQ settings are out of range!")
            coeffs = numpy.array(coeffs, dtype = numpy.complex128)
            coeff_str = struct.pack('>%ih' % (2 * n_coeffs), *coeffs.view(dtype=numpy.float64))
        else:
            log_runtimeerror(self.floggers[ffpga_n], "Sorry, your EQ type is not supported. Expecting scalar or complex.")

        #self.floggers[ffpga_n].info('Writing new EQ coefficient values to config file...')
        #self.config.write('equalisation','eq_coeffs_%i%c'%(ant,pol),str(coeffs.tolist()))
        
        for term, coeff in enumerate(coeffs):
            self.floggers[ffpga_n].debug('''Initialising EQ for antenna %s, input %i on %s (register %s)'s index %i to %s.''' % (ant_str, feng_input, self.fsrvs[ffpga_n], register_name, term, str(coeff)))

        # if this is a narrowband implementation, swap the EQ values, because the Xilinx FFT output is in swapped halves
        if self.is_narrowband():
            coeff_str = ''.join([coeff_str[len(coeff_str)/2:], coeff_str[0:len(coeff_str)/2]])

        # finally write to the bram
        fpga.write(register_name, coeff_str)

    def adc_lru_mapping_get(self):
        """Map all the antennas to lru and physical inputs"""
        rv = []
        for input_n, ant_str in enumerate(self.config._get_ant_mapping_list()):
            ffpga_n,xfpga_n,fxaui_n,xxaui_n,feng_input = self.get_input_location(input_n)
            rv.append((ant_str,input_n,self.fsrvs[ffpga_n],feng_input))
        return rv

    def adc_amplitudes_get(self, antpols=[]):
        """Gets the ADC RMS amplitudes from the F engines. If no antennas are specified, return all."""
        #Removed 'bits' cnt. Wasn't using it anywhere 'cos it wasn't exactly accurate. Rather use get_adc_snapshot and calc std-dev.
        #2011-04-20: JRM Changed "ants" to antpol so can specify any individual input.
        if antpols == []:
            antpols=self.config._get_ant_mapping_list()
        rv = {}
        for ant_str in antpols:
            ffpga_n,xfpga_n,fxaui_n,xxaui_n,feng_input = self.get_ant_str_location(ant_str)
            rv[ant_str] = {}
            rv[ant_str]['rms_raw'] = numpy.sqrt(self.ffpgas[ffpga_n].read_uint('adc_sum_sq%i'%(feng_input))/float(self.config['adc_levels_acc_len']))
            rv[ant_str]['rms_v'] = rv[ant_str]['rms_raw']*self.config['adc_v_scale_factor']
            rv[ant_str]['adc_rms_dbm'] = v_to_dbm(rv[ant_str]['rms_v'])
            rf_status=self.rf_status_get(ant_str) 
            rv[ant_str]['analogue_gain'] = rf_status[1]
            rv[ant_str]['input_rms_dbm'] = rv[ant_str]['adc_rms_dbm']-rv[ant_str]['analogue_gain']
            rv[ant_str]['low_level_warn'] = True if (rv[ant_str]['adc_rms_dbm']<self.config['adc_low_level_warning']) else False
            rv[ant_str]['high_level_warn'] = True if (rv[ant_str]['adc_rms_dbm']>self.config['adc_high_level_warning']) else False
        return rv

    def spead_labelling_issue(self):
        """Issues the SPEAD metadata packets describing the labelling/location/connections of the system's analogue inputs."""
#        self.spead_ig.add_item(name="bls_ordering",id=0x100C,
#            description="The output ordering of the baselines from each X engine. Packed as a pair of unsigned integers, ant1,ant2 where ant1 < ant2.",
#            shape=[self.config['n_bls'],2],fmt=spead.mkfmt(('u',16)),
#            init_val=[[bl[0],bl[1]] for bl in self.get_bl_order()])

        self.spead_ig.add_item(name="bls_ordering",id=0x100C,
            description="The output ordering of the baselines from each X engine.",
            #shape=[self.config['n_bls']],fmt=spead.STR_FMT, 
            init_val=numpy.array([bl for bl in self.get_bl_order()]))

        self.spead_ig.add_item(name="input_labelling",id=0x100E,
            description="The physical location of each antenna connection.",
            init_val=numpy.array([(ant_str,input_n,lru,feng_input) for (ant_str,input_n,lru,feng_input) in self.adc_lru_mapping_get()]))

#        self.spead_ig.add_item(name="crosspol_ordering",id=0x100D,
#            description="The output ordering of the cross-pol terms. Packed as a pair of characters, pol1,pol2.",
#            shape=[self.config['n_stokes'],self.config['n_pols']],fmt=spead.mkfmt(('c',8)),
#            init_val=[[bl[0],bl[1]] for bl in self.get_crosspol_order()])
        self.spead_tx.send_heap(self.spead_ig.get_heap())
        self.syslogger.info("Issued SPEAD metadata describing baseline labelling and input mapping to %s:%i."%(self.config['rx_meta_ip_str'],self.config['rx_udp_port']))


    def spead_static_meta_issue(self):
        """ Issues the SPEAD metadata packets containing the payload and options descriptors and unpack sequences."""
        #tested ok corr-0.5.0 2010-08-07

        self.spead_ig.add_item(name="adc_clk",id=0x1007,
            description="Clock rate of ADC (samples per second).",
            shape=[],fmt=spead.mkfmt(('u',64)),
            init_val=self.config['adc_clk'])

        self.spead_ig.add_item(name="n_bls",id=0x1008,
            description="The total number of baselines in the data product.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['n_bls'])

        self.spead_ig.add_item(name="n_chans",id=0x1009,
            description="The total number of frequency channels present in any integration.",
            shape=[], fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['n_chans'])

        self.spead_ig.add_item(name="n_ants",id=0x100A,
            description="The total number of dual-pol antennas in the system.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['n_ants'])

        self.spead_ig.add_item(name="n_xengs",id=0x100B,
            description="The total number of X engines in the system.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['n_xeng'])

        self.spead_ig.add_item(name="center_freq",id=0x1011,
            description="The center frequency of the DBE in Hz, 64-bit IEEE floating-point number.",
            shape=[],fmt=spead.mkfmt(('f',64)),
            init_val=self.config['center_freq'])

        self.spead_ig.add_item(name="bandwidth",id=0x1013,
            description="The analogue bandwidth of the digitally processed signal in Hz.",
            shape=[],fmt=spead.mkfmt(('f',64)),
            init_val=self.config['bandwidth'])
        
        #1015/1016 are taken (see time_metadata_issue below)

        if self.is_wideband():
            self.spead_ig.add_item(name="fft_shift",id=0x101E,
                description="The FFT bitshift pattern. F-engine correlator internals.",
                shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
                init_val=self.config['fft_shift'])
        elif self.is_narrowband():
            self.spead_ig.add_item(name="fft_shift_fine",id=0x101C,
                description="The FFT bitshift pattern for the fine channelisation FFT. F-engine correlator internals.",
                shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
                init_val=self.config['fft_shift_fine'])
            self.spead_ig.add_item(name="fft_shift_coarse",id=0x101D,
                description="The FFT bitshift pattern for the coarse channelisation FFT. F-engine correlator internals.",
                shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
                init_val=self.config['fft_shift_coarse'])

        self.spead_ig.add_item(name="xeng_acc_len",id=0x101F,
            description="Number of spectra accumulated inside X engine. Determines minimum integration time and user-configurable integration time stepsize. X-engine correlator internals.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['xeng_acc_len'])

        self.spead_ig.add_item(name="requant_bits",id=0x1020,
            description="Number of bits after requantisation in the F engines (post FFT and any phasing stages).",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['feng_bits'])

        self.spead_ig.add_item(name="feng_pkt_len",id=0x1021,
            description="Payload size of 10GbE packet exchange between F and X engines in 64 bit words. Usually equal to the number of spectra accumulated inside X engine. F-engine correlator internals.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['10gbe_pkt_len'])

        self.spead_ig.add_item(name="rx_udp_port",id=0x1022,
            description="Destination UDP port for X engine output.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['rx_udp_port'])

        self.spead_ig.add_item(name="feng_udp_port",id=0x1023,
            description="Destination UDP port for F engine data exchange.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['10gbe_port'])

        self.spead_ig.add_item(name="rx_udp_ip_str",id=0x1024,
            description="Destination IP address for X engine output UDP packets.",
            shape=[-1],fmt=spead.STR_FMT,
            init_val=self.config['rx_udp_ip_str'])

        self.spead_ig.add_item(name="feng_start_ip",id=0x1025,
            description="F engine starting IP address.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['10gbe_ip'])

        self.spead_ig.add_item(name="xeng_rate",id=0x1026,
            description="Target clock rate of processing engines (xeng).",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['xeng_clk'])

#        self.spead_ig.add_item(name="n_stokes",id=0x1040,
#            description="Number of Stokes parameters in output.",
#            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
#            init_val=self.config['n_stokes'])

        self.spead_ig.add_item(name="x_per_fpga",id=0x1041,
            description="Number of X engines per FPGA.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['x_per_fpga'])

        self.spead_ig.add_item(name="n_ants_per_xaui",id=0x1042,
            description="Number of antennas' data per XAUI link.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['n_ants_per_xaui'])

        self.spead_ig.add_item(name="ddc_mix_freq",id=0x1043,
            description="Digital downconverter mixing freqency as a fraction of the ADC sampling frequency. eg: 0.25. Set to zero if no DDC is present.",
            shape=[],fmt=spead.mkfmt(('f',64)),
            init_val=self.config['ddc_mix_freq'])

#        self.spead_ig.add_item(name="ddc_bandwidth",id=0x1044,
#            description="Digitally processed bandwidth, post DDC, in Hz.",
#            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
#            init_val=self.config['bandwidth']) #/self.config['ddc_decimation']) config's bandwidth is already divided by ddc decimation

#0x1044 should be ddc_bandwidth, not ddc_decimation.
#        self.spead_ig.add_item(name="ddc_decimation",id=0x1044,
#            description="Frequency decimation of the digital downconverter (determines how much bandwidth is processed) eg: 4",
#            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
#            init_val=self.config['ddc_decimation'])

        self.spead_ig.add_item(name="adc_bits",id=0x1045,
            description="ADC quantisation (bits).",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['adc_bits'])

        self.spead_ig.add_item(name="xeng_out_bits_per_sample",id=0x1048,
            description="The number of bits per value of the xeng accumulator output. Note this is for a single value, not the combined complex size.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['xeng_sample_bits'])

        self.spead_tx.send_heap(self.spead_ig.get_heap())
        self.syslogger.info("Issued misc SPEAD metadata to %s:%i."%(self.config['rx_meta_ip_str'],self.config['rx_udp_port']))

    def spead_time_meta_issue(self):
        """Issues a SPEAD packet to notify the receiver that we've resync'd the system, acc len has changed etc."""

        self.spead_ig.add_item(name="n_accs",id=0x1015,
            description="The number of spectra that are accumulated per integration.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.acc_n_get())

        self.spead_ig.add_item(name="int_time",id=0x1016,
            description="Approximate (it's a float!) integration time per accumulation in seconds.",
            shape=[],fmt=spead.mkfmt(('f',64)),
            init_val=self.acc_time_get())

        self.spead_ig.add_item(name='sync_time',id=0x1027,
            description="Time at which the system was last synchronised (armed and triggered by a 1PPS) in seconds since the Unix Epoch.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['sync_time'])

        self.spead_ig.add_item(name="scale_factor_timestamp",id=0x1046,
            description="Timestamp scaling factor. Divide the SPEAD data packet timestamp by this number to get back to seconds since last sync.",
            shape=[],fmt=spead.mkfmt(('f',64)),
            init_val=self.config['spead_timestamp_scale_factor'])

        self.spead_tx.send_heap(self.spead_ig.get_heap())
        self.syslogger.info("Issued SPEAD timing metadata to %s:%i."%(self.config['rx_meta_ip_str'],self.config['rx_udp_port']))

    def spead_eq_meta_issue(self):
        """Issues a SPEAD heap for the RF gain and EQ settings."""
        if self.config['adc_type'] == 'katadc':
            for input_n,ant_str in enumerate(self.config._get_ant_mapping_list()):
                self.spead_ig.add_item(name="rf_gain_%i"%(input_n),id=0x1200+input_n,
                    description="The analogue RF gain applied at the ADC for input %i (ant %s) in dB."%(input_n,ant_str),
                    shape=[],fmt=spead.mkfmt(('f',64)),
                    init_val=self.config['rf_gain_%i'%(input_n)])

        if self.config['eq_type']=='scalar':
            for in_n,ant_str in enumerate(self.config._get_ant_mapping_list()):
                self.spead_ig.add_item(name="eq_coef_%s"%(ant_str),id=0x1400+in_n,
                    description="The unitless per-channel digital amplitude scaling factors implemented prior to requantisation, post-FFT, for input %s."%(ant_str),
                    init_val=self.eq_spectrum_get(ant_str))

        elif self.config['eq_type']=='complex':
            for in_n,ant_str in enumerate(self.config._get_ant_mapping_list()):
                self.spead_ig.add_item(name="eq_coef_%s"%(ant_str),id=0x1400+in_n,
                    description="The unitless per-channel digital scaling factors implemented prior to requantisation, post-FFT, for input %s. Complex number real,imag 32 bit integers."%(ant_str),
                    shape=[self.config['n_chans'],2],fmt=spead.mkfmt(('u',32)),
                    init_val=[[numpy.real(coeff),numpy.imag(coeff)] for coeff in self.eq_spectrum_get(ant_str)])

        else:
            raise RuntimeError("I don't know how to deal with your EQ type.")

        self.spead_tx.send_heap(self.spead_ig.get_heap())
        self.syslogger.info("Issued SPEAD EQ metadata to %s:%i."%(self.config['rx_meta_ip_str'],self.config['rx_udp_port']))

    def spead_data_descriptor_issue(self):
        """ Issues the SPEAD data descriptors for the HW 10GbE output, to enable receivers to decode the data."""
        #tested ok corr-0.5.0 2010-08-07

        if self.config['xeng_sample_bits'] != 32:
            raise RuntimeError("Invalid bitwidth of X engine output. You specified %i, but I'm hardcoded for 32."%self.config['xeng_sample_bits'])

        if self.config['xeng_format'] == 'cont':
            self.spead_ig.add_item(name=('timestamp'), id=0x1600,
                description='Timestamp of start of this integration. uint counting multiples of ADC samples since last sync (sync_time, id=0x1027). Divide this number by timestamp_scale (id=0x1046) to get back to seconds since last sync when this integration was actually started. Note that the receiver will need to figure out the centre timestamp of the accumulation (eg, by adding half of int_time, id 0x1016).',
                shape=[], fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
                init_val=0)

            self.spead_ig.add_item(name=("xeng_raw"),id=0x1800,
                description="Raw data for %i xengines in the system. This item represents a full spectrum (all frequency channels) assembled from lowest frequency to highest frequency. Each frequency channel contains the data for all baselines (n_bls given by SPEAD ID 0x100B). Each value is a complex number -- two (real and imaginary) unsigned integers."%(self.config['n_xeng']),
            ndarray=(numpy.dtype(numpy.int32),(self.config['n_chans'],self.config['n_bls'],2)))

        elif self.config['xeng_format'] =='inter':
            for x in range(self.config['n_xeng']):

                self.spead_ig.add_item(name=('timestamp%i'%x), id=0x1600+x,
                    description='Timestamp of start of this integration. uint counting multiples of ADC samples since last sync (sync_time, id=0x1027). Divide this number by timestamp_scale (id=0x1046) to get back to seconds since last sync when this integration was actually started. Note that the receiver will need to figure out the centre timestamp of the accumulation (eg, by adding half of int_time, id 0x1016).',
                    shape=[], fmt=spead.mkfmt(('u',spead.ADDRSIZE)),init_val=0)

                self.spead_ig.add_item(name=("xeng_raw%i"%x),id=(0x1800+x),
                    description="Raw data for xengine %i out of %i. Frequency channels are split amongst xengines. Frequencies are distributed to xengines in a round-robin fashion, starting with engine 0. Data from all X engines must thus be combed or interleaved together to get continuous frequencies. Each xengine calculates all baselines (n_bls given by SPEAD ID 0x100B) for a given frequency channel. For a given baseline, -SPEAD ID 0x1040- stokes parameters are calculated (nominally 4 since xengines are natively dual-polarisation; software remapping is required for single-baseline designs). Each stokes parameter consists of a complex number (two real and imaginary unsigned integers)."%(x,self.config['n_xeng']),
                    ndarray=(numpy.dtype(numpy.int32),(self.config['n_chans']/self.config['n_xeng'],self.config['n_bls'],2)))

        self.spead_tx.send_heap(self.spead_ig.get_heap())
        self.syslogger.info("Issued SPEAD data descriptor to %s:%i."%(self.config['rx_meta_ip_str'],self.config['rx_udp_port']))

    def spead_issue_all(self):
        """Issues all SPEAD metadata."""
        self.spead_data_descriptor_issue()
        self.spead_static_meta_issue()
        self.spead_time_meta_issue()
        self.spead_eq_meta_issue()
        self.spead_labelling_issue()

    def is_wideband(self):
        return self.config['mode'] == self.MODE_WB

    def is_narrowband(self):
        return self.config['mode'] == self.MODE_NB
    
    def is_ddc(self):
        return self.config['mode'] == self.MODE_DDC

def dbm_to_dbuv(dbm):
    return dbm+107

def dbuv_to_dbm(dbuv):
    return dbm-107

def v_to_dbuv(v):
    return 20*numpy.log10(v*1e6)

def dbuv_to_v(dbuv):
    return (10**(dbuv/20.))/1e6

def dbm_to_v(dbm):
    return numpy.sqrt(10**(dbm/10.)/1000*50)

def v_to_dbm(v):
    return 10*numpy.log10(v*v/50.*1000)


