import iniparse, exceptions, socket, struct, numpy, os, logging, corr
"""
Library for parsing CASPER correlator configuration files

Author: Jason Manley
"""
"""
Revs:
2011-07-28: PVP Added mode support so we can load different params for wideband, narrowband,
                as well as common params. The 'correlator' section of the config file must
                include a mode parameter now. See code for modes.
2011-05-11: JRM changed n_bls to be 4x bigger (single pol is now assumed)
                n_stokes removed
                added threshold for adc_input low levels
2010-08-05: JRM changed adc_clk to integer Hz (from float GHz)
                added calc of timestamp scaling factors and misc other bits
2010-06-28: JRM Added support for reconfigurable F engines (ie ROACH)
2009-12-10: JRM Changed IP address formats to input strings, but return integers.
                Added __setitem__, though it's volatile.
                added calculation of n_bls, bandwidth, integration time etc.
2008-02-08: JRM Replaced custom tokeniser with string.split
                Changed EQ to EQ_polys
                Changed max_payload_len to rx_buffer_size

"""
LISTDELIMIT = ','
PORTDELIMIT = ':'

VAR_RUN = '/var/run/corr'

MODE_WB  = 'wbc'
MODE_NB  = 'nbc'
MODE_DDC = 'ddc'


class CorrConf:    
    def __init__(self, config_file,log_handler=None,log_level=logging.INFO):
        self.logger = logging.getLogger('cn_conf')
        self.log_handler = log_handler if log_handler != None else corr.log_handlers.DebugLogHandler(100)
        self.logger.addHandler(self.log_handler)
        self.logger.setLevel(log_level)

        self.config_file = config_file
        self.config_file_name = os.path.split(self.config_file)[1]
        self.logger.info('Trying to open log file %s.'%self.config_file)
        self.cp = iniparse.INIConfig(open(self.config_file, 'rb'))
        self.config = dict()
        self.read_mode()
        available_modes = [MODE_WB, MODE_NB, MODE_DDC]
        if self.config['mode'] == MODE_WB:
            self.logger.info('Found a wideband correlator.')
            self.read_wideband()
        elif self.config['mode'] == MODE_NB:
            self.logger.info('Found a narrowband correlator.')
            self.read_narrowband()
        elif self.config['mode'] == MODE_DDC:
            self.logger.info('Found a correlator with a DDC.')
            self.read_narrowband_ddc()
        else:
            self.logger.error("Mode %s not understood."%(self.config['mode']))
            raise RuntimeError('Unknown correlator mode %s.'%self.config['mode'])
        self.read_common()
        self.read_bf()

    def __getitem__(self, item):
        if item == 'sync_time':
            fp = open(VAR_RUN + '/' + item + '.' + self.config_file_name, 'r')
            val = float(fp.readline())
            fp.close()
            return val
        elif item == 'antenna_mapping':
            fp = open(VAR_RUN + '/' + item + '.' + self.config_file_name, 'r')
            val = (fp.readline()).split(LISTDELIMIT)
            fp.close()
            return val
        else:
            return self.config[item]

    def __setitem__(self,item,value):
        self.config[item]=value

    def file_exists(self):
        try:
            #f = open(self.config_file)
            f = open(self.config_file, 'r')
        except IOError:
            exists = False
            self.logger.error('Error opening config file at %s.'%self.config_file)
            raise RuntimeError('Error opening config file at %s.'%self.config_file)
        else:
            exists = True
            f.close()

        # check for runtime files and create if necessary:
        if not os.path.exists(VAR_RUN):
            os.mkdir(VAR_RUN)
            #os.chmod(VAR_RUN,0o777)
        for item in ['antenna_mapping', 'sync_time']:
            if not os.path.exists(VAR_RUN + '/' + item + '.' + self.config_file_name):
                f = open(VAR_RUN + '/' + item + '.' + self.config_file_name, 'w')
                f.write(chr(0))
                f.close()
                #os.chmod(VAR_RUN+'/' + item,0o777)
        return exists

    def _get_ant_mapping_list(self):
        ant_list = self['antenna_mapping']
        if len(ant_list) < self.config['n_inputs']:
            #there's no current mapping or the mapping is bad... set default:
            ant_list=[]
            for a in range(self.config['n_ants']):
                for p in self.config['pols']:
                    ant_list.append('%i%c'%(a,p))
        return ant_list[0:self.config['n_inputs']]

    def map_ant_to_input(self,ant_str):
        """Maps an antenna string to an input number."""
        try:
            input_n = self._get_ant_mapping_list().index(ant_str)
            return input_n
        except:
            raise RuntimeError('Unable to map antenna')
        
    def map_input_to_ant(self,input_n):
        """Maps an input number to an antenna string."""
        return self._get_ant_mapping_list()[input_n]

    def calc_int_time(self):
        self.config['n_accs'] = self.config['acc_len'] * self.config['xeng_acc_len']
        self.config['int_time'] = float(self.config['n_chans']) * self.config['n_accs'] / self.config['bandwidth']

    def read_wideband(self):
        if not self.file_exists():
            raise RuntimeError('Error opening config file or runtime variables.')
        self.read_int('correlator', 'fft_shift')

    def read_narrowband(self):
        if not self.file_exists():
            raise RuntimeError('Error opening config file or runtime variables.')
        self.read_int('correlator', 'fft_shift_fine')
        self.read_int('correlator', 'fft_shift_coarse')
        self.read_int('correlator', 'coarse_chans')
        self.config['current_coarse_chan'] = 0

    def read_narrowband_ddc(self):
        if not self.file_exists():
            raise RuntimeError('Error opening config file or runtime variables.')

    def read_mode(self):
        if not self.file_exists():
            raise RuntimeError('Error opening config file or runtime variables.')
        self.read_str('correlator', 'mode')

    def read_common(self):
        if not self.file_exists():
            raise RuntimeError('Error opening config file or runtime variables.')

        self.config['pol_map']={'x':0,'y':1}
        self.config['rev_pol_map']={0:'x',1:'y'}
        self.config['pols']=['x','y']
        #self.config['n_pols']=2
        self.config['xeng_sample_bits']=32

        #get the server stuff
        self.read_int('katcp','katcp_port')
        if len(self.cp.katcp.servers_f.strip()) > 0:
          self.config['servers_f'] = self.cp.katcp.servers_f.strip().split(LISTDELIMIT)
        else:
          print "Warning, no F-engine servers found in config file."
          self.config['servers_f'] = []
        if len(self.cp.katcp.servers_x.strip()) > 0:
          self.config['servers_x'] = self.cp.katcp.servers_x.strip().split(LISTDELIMIT)
        else:
          print "Warning, no X-engine servers found in config file."
          self.config['servers_x'] = []
        self.config['bitstream_f'] = self.cp.katcp.bitstream_f
        self.config['bitstream_x'] = self.cp.katcp.bitstream_x

        #get the correlator config stuff:
        self.read_int('correlator','pcnt_bits')
        self.read_int('correlator','mcnt_bits')
        self.read_int('correlator','n_chans')
        self.read_int('correlator','n_ants')
        self.read_int('correlator','acc_len')
        self.read_int('correlator','adc_clk')
#        self.read_int('correlator','n_stokes')
        self.read_int('correlator','x_per_fpga')
        self.read_int('correlator','n_ants_per_xaui')
        self.read_int('correlator','xeng_acc_len')
        self.read_float('correlator','ddc_mix_freq')
        self.read_int('correlator','ddc_decimation')
        self.read_int('correlator','10gbe_port')
        self.read_int('correlator','10gbe_pkt_len')
        self.read_int('correlator','feng_bits')
        self.read_int('correlator','feng_fix_pnt_pos')
        self.read_int('correlator','xeng_clk')
        self.read_str('correlator','feng_out_type')
        self.read_str('correlator','xeng_format')
        self.read_int('correlator','n_xaui_ports_per_xfpga')
        self.read_int('correlator','n_xaui_ports_per_ffpga')
        self.read_int('correlator','adc_bits')
        self.read_int('correlator','adc_levels_acc_len')
        self.read_int('correlator','feng_sync_period')
        self.read_int('correlator','feng_sync_delay')
        #self.read_int('correlator','sync_time') #moved to /var/run/...
        self.config['10gbe_ip']=struct.unpack('>I',socket.inet_aton(self.get_line('correlator','10gbe_ip')))[0]
        #print '10GbE IP address is %i'%self.config['10gbe_ip']

        #sanity checks:
        if self.config['n_ants']%len(self.config['servers_f']) != 0:
            raise RuntimeError("You have %i antennas, but %i F boards. That can't be right."%(self.config['n_ants'],len(self.config['servers_f'])))

        if self.config['feng_out_type'] != '10gbe' and self.config['feng_out_type'] != 'xaui':
            raise RuntimeError("F engine must have output type of '10gbe' or 'xaui'.")

        if self.config['xeng_format'] != 'inter' and self.config['xeng_format'] != 'cont':
            raise RuntimeError("X engine output format must be either inter or cont.")

        self.config['n_ffpgas'] = len(self.config['servers_f'])
        self.config['n_xfpgas'] = len(self.config['servers_x'])
        self.config['n_xeng']=self.config['x_per_fpga']*self.config['n_xfpgas']
        #n_feng is usually the number of dual-pol fengines in the design
        self.config['n_feng']=self.config['n_ants']
        self.config['n_inputs']=self.config['n_ants']*2 #self.config['n_pols']
        self.config['f_per_fpga']=self.config['n_feng']/self.config['n_ffpgas']
        self.config['f_inputs_per_fpga']=self.config['f_per_fpga']*2
        self.config['n_bls']=(self.config['n_ants']*(self.config['n_ants']+1)/2)*4
        self.config['n_chans_per_x'] = (self.config['n_chans']/self.config['n_xeng']) if self.config['n_xeng'] > 0 else 0

        # determine the bandwidth the system is processing
        self.config['rf_bandwidth'] = self.config['adc_clk'] / 2.
        # is a DDC being used in the F engine?
        if self.config['ddc_mix_freq'] > 0:
            if self.config['mode'] == MODE_WB:
                self.config['bandwidth'] = float(self.config['adc_clk']) / self.config['ddc_decimation']
                self.config['center_freq'] = float(self.config['adc_clk']) * self.config['ddc_mix_freq']
            else:
                raise RuntimeError("Undefined for other modes.")
        else:
            if self.config['mode'] == MODE_WB:
                self.config['bandwidth'] = self.config['adc_clk'] / 2.
                self.config['center_freq'] = self.config['bandwidth'] / 2.
            elif self.config['mode'] == MODE_NB:
                self.config['bandwidth'] = (self.config['adc_clk'] / 2.) / self.config['coarse_chans']
                self.config['center_freq'] = self.config['bandwidth'] / 2.
            else:
                raise RuntimeError("Undefined for other modes.")

        self.calc_int_time()

        self.read_str('correlator','adc_type')
        if self.config['adc_type'] == 'katadc':
            self.config['adc_demux'] = 4
            self.config['adc_n_bits'] = 8
            self.config['adc_v_scale_factor']=1/184.3
            self.config['adc_low_level_warning']=-32
            self.config['adc_high_level_warning']=0
            for input_n in range(self.config['n_inputs']):
                try:
                    ant_rf_gain = self.read_int('equalisation','rf_gain_%i'%(input_n))
                except: raise RuntimeError('ERR rf_gain_%i'%(input_n))
        elif self.config['adc_type'] == 'iadc':
            self.config['adc_demux'] = 4
            self.config['adc_n_bits'] = 8
            self.config['adc_v_scale_factor']=1/368.
            self.config['adc_low_level_warning']=-35
            self.config['adc_high_level_warning']=0
        else:
            raise RuntimeError("adc_type not understood. expecting katadc or iadc.")

        self.config['feng_clk'] = self.config['adc_clk'] / self.config['adc_demux']
        self.config['mcnt_scale_factor'] = self.config['feng_clk']
        self.config['pcnt_scale_factor'] = self.config['bandwidth'] / self.config['xeng_acc_len']

        #get the receiver section:
        self.config['receiver'] = dict()
        self.read_int('receiver','rx_udp_port')
        self.read_str('receiver','out_type')
        self.read_int('receiver','rx_pkt_payload_len')
        #self.read_int('receiver','instance_id')
        self.config['rx_udp_ip_str']=self.get_line('receiver','rx_udp_ip')
        self.config['rx_udp_ip']=struct.unpack('>I',socket.inet_aton(self.get_line('receiver','rx_udp_ip')))[0]
        self.config['rx_meta_ip_str']=self.get_line('receiver','rx_meta_ip')
        self.config['rx_meta_ip']=struct.unpack('>I',socket.inet_aton(self.get_line('receiver','rx_meta_ip')))[0]
        self.read_int('receiver','sig_disp_port')
        self.config['sig_disp_ip_str']=self.get_line('receiver','sig_disp_ip')
        self.config['sig_disp_ip']=struct.unpack('>I',socket.inet_aton(self.get_line('receiver','sig_disp_ip')))[0]
        #print 'RX UDP IP address is %i'%self.config['rx_udp_ip']
        if self.config['out_type'] != '10gbe' and self.config['out_type'] != 'ppc': raise RuntimeError('Output type must be ppc or 10gbe')

        spead_flavour=self.get_line('receiver','spead_flavour')
        self.config['spead_flavour'] = tuple([int(i) for i in spead_flavour.split(LISTDELIMIT)])
        if self.config['spead_flavour'][1]<(48-numpy.log2(self.config['n_chans'])): 
            self.config['spead_timestamp_scale_factor']=(self.config['pcnt_scale_factor']/self.config['n_chans'])
        else: 
            self.config['spead_timestamp_scale_factor']=(int(self.config['pcnt_scale_factor'])<<int(numpy.log2(self.config['n_chans']) - (48-self.config['spead_flavour'][1])))/float(self.config['n_chans'])

        #equalisation section:
        self.read_str('equalisation','eq_default')
        self.read_str('equalisation','eq_type')
        self.read_int('equalisation','eq_decimation')
        #self.read_int('equalisation','eq_brams_per_pol_interleave')
        
        if not self.config['eq_default'] in ['poly','coeffs']: raise RuntimeError('ERR invalid eq_default')

        if self.config['eq_default'] == 'poly':
            for input_n in range(self.config['n_inputs']):
                try:
                    ant_eq_str=self.get_line('equalisation','eq_poly_%i'%(input_n))
                    self.config['eq_poly_%i'%(input_n)]=[int(coef) for coef in ant_eq_str.split(LISTDELIMIT)]
                except: 
                    raise RuntimeError('ERR eq_poly_%i'%(input_n))

        #we need to try to read eq_coeffs every time so that this info is available to corr_functions even if it's not how we default program the system.
        elif self.config['eq_default'] == 'coeffs':
            n_coeffs = self.config['n_chans']/self.config['eq_decimation']
            for input_n in range(self.config['n_inputs']):
                try:
                    ant_eq_str=self.get_line('equalisation','eq_coeffs_%i'%(input_n))
                    self.config['eq_coeffs_%s'%(input_n)]=eval(ant_eq_str)
                    if len(self.config['eq_coeffs_%i'%(input_n)]) != n_coeffs:
                        raise RuntimeError('ERR eq_coeffs_%i... incorrect number of coefficients. Expecting %i, got %i.'%(input_n,n_coeffs,len(self.config['eq_coeffs_%i'%(input_n)])))
                except: raise RuntimeError('ERR eq_coeffs_%i'%(input_n))

    def read_bf(self):
        try:
            self.read_int('beamformer', 'bf_n_beams')
            self.read_str('beamformer', 'bf_register_prefix')
            self.read_int('beamformer', 'bf_be_per_fpga')
            self.read_int('beamformer', 'bf_n_beams_per_be')
            self.read_str('beamformer', 'bf_data_type')
            self.read_int('beamformer', 'bf_bits_out')
            self.read_str('beamformer', 'bf_cal_type')
            self.read_int('beamformer', 'bf_cal_n_bits')
            self.read_int('beamformer', 'bf_cal_bin_pt')
            
            for beam_n in range(self.config['bf_n_beams']):

                self.read_int('beamformer', 'bf_centre_frequency_beam%i'%beam_n)
                self.read_int('beamformer', 'bf_bandwidth_beam%i'%beam_n)

                self.read_str('beamformer', 'bf_name_beam%i'%(beam_n))
                self.read_int('beamformer', 'bf_location_beam%i'%(beam_n))

                #ip destination for data
                udp_ip_str=self.get_line('beamformer','bf_rx_udp_ip_str_beam%i'%beam_n)
                self.config['bf_rx_udp_ip_str_beam%i'%(beam_n)]=udp_ip_str
                self.config['bf_rx_udp_ip_beam%i'%(beam_n)]=struct.unpack('>I',socket.inet_aton(udp_ip_str))[0]
                #port destination for data
                self.read_int('beamformer', 'bf_rx_udp_port_beam%i'%(beam_n))

                #ip destination for spead meta data
                meta_ip_str=self.get_line('beamformer','bf_rx_meta_ip_str_beam%i'%(beam_n))
                self.config['bf_rx_meta_ip_str_beam%i'%(beam_n)]=meta_ip_str
                self.config['bf_rx_meta_ip_beam%i'%(beam_n)]=struct.unpack('>I',socket.inet_aton(meta_ip_str))[0] 
                #port destination for spead meta data
                self.read_int('beamformer', 'bf_rx_meta_port_beam%i'%(beam_n))

                #calibration

                n_coeffs = self.config['n_chans']
	        for input_n in range(self.config['n_ants']):
		    try:
		        cal_default=self.get_line('beamformer', 'bf_cal_default_input%i_beam%i'%(input_n, beam_n))
			self.config['bf_cal_default_input%i_beam%i'%(input_n, beam_n)]=cal_default
                    except:
                        raise RuntimeError('ERR reading bf_cal_default_input%i_beam%i'%(input_n, beam_n))
		    if cal_default == 'poly': 
		        try:
			    ant_cal_str=self.get_line('beamformer','bf_cal_poly_input%i_beam%i'%(input_n, beam_n))
			    self.config['bf_cal_poly_input%i_beam%i'%(input_n, beam_n)]=[int(coef) for coef in ant_cal_str.split(LISTDELIMIT)]
		        except: raise RuntimeError('ERR bf_cal_coeffs_input%i_beam%i'%(input_n, beam_n))
		    elif cal_default == 'coeffs':
		        try:
			    ant_cal_str=self.get_line('beamformer','bf_cal_coeffs_input%i_beam%i'%(input_n, beam_n))
			    self.config['bf_cal_coeffs_input%i_beam%i'%(input_n, beam_n)]=eval(ant_cal_str)
			    if len(self.config['bf_cal_coeffs_input%i_beam%i'%(input_n, beam_n)]) != n_coeffs:
			        raise RuntimeError('ERR bf_cal_coeffs_input%i_beam%i... incorrect number of coefficients. Expecting %i, got %i.'%(input_n, beam_n, n_coeffs,len(self.config['eq_cal_coeffs_input%i_beam%i'%(input_n, beam_n)])))
		        except: raise RuntimeError('ERR bf_cal_coeffs_input%i_beam%i'%(input_n, beam_n))
		    else:
		        raise RuntimeError('ERR bf_cal_default_input%i_beam%i not poly or coeffs'%(input_n, beam_n))
            
            self.logger.info('%i beam beamformer found in this design outputting %s data.'%(self.config['bf_n_beams'], self.config['bf_data_type']))
        except Exception:
            self.logger.info('No beamformer found in this design')
            return
    
    def write(self,section,variable,value):
        print 'Writing to the config file. Mostly, this is a bad idea. Mostly. Doing nothing.'
        return
        self.config[variable] = value
        self.cp[section][variable] = str(value)
        fpw=open(self.config_file, 'w')
        print >>fpw,self.cp
        fpw.close()

    def write_var(self, filename, value):
        fp=open(VAR_RUN + '/' + filename + '.' + self.config_file_name, 'w')
        fp.write(value)
        fp.close()

    def write_var_list(self, filename, list_to_store):
        fp=open(VAR_RUN + '/' + filename + '.' + self.config_file_name, 'w')
        for v in list_to_store:
            fp.write(v + LISTDELIMIT)
        fp.close()

    def get_line(self,section,variable):
        return self.cp[section][variable]

    def read_int(self,section,variable):
        self.config[variable]=int(self.cp[section][variable])

    def read_bool(self,section,variable):
        self.config[variable]=(self.cp[section][variable] != '0')

    def read_str(self,section,variable):
        self.config[variable]=self.cp[section][variable]

    def read_float(self,section,variable):
        self.config[variable]=float(self.cp[section][variable])
