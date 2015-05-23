import numpy, time, sys, logging

logger = logging.getLogger(__name__)

class Sfp_mezzanine_card(object):
    ''' An SFP+ mezzanine card as used on ROACH2s.i
        It has two Vitesse PHYs onboard.
    '''
    def __init__(self, fpga, slot):
        self.fpga = fpga
        self.slot = slot
        self.phys = [Sfp_phy(self, 0), Sfp_phy(self, 1)]

    def initialise(self):
        for p in self.phys:
            p.reset()
            p.check_connection()

    def select(self):
        self.fpga.write_int('sfp_mdio_sel', self.slot)  # select mezzanine card

    def mdio_enable_sw_control(self):
        '''Enable software control of SFP MDIOs.
        '''
        self.fpga.write_int('sfp_gpio_data_ded', 0x618)     # See SW enable status below:
        '''
        # mgt_gpio[11]  Unused 
        # ENABLE SW CONTROL => mgt_gpio[10]  SFP1: MDIO          MDIO data line
        # ENABLE SW CONTROL => mgt_gpio[9]   SFP1: MDC           MDIO clock line
        # mgt_gpio[8]   SFP1: PHY1 RESET    PHY reset when '1'
        
        # mgt_gpio[7]   SFP1: PHY0 RESET    PHY reset when '1'
        # mgt_gpio[6]   SFP1: MDIO Enable   Enable MDIO mode when '1'
        # mgt_gpio[5]   Unused 
        # ENABLE SW CONTROL => mgt_gpio[4]   SFP0: MDIO          MDIO data line
        
        # ENABLE SW CONTROL => mgt_gpio[3]   SFP0: MDC           MDIO clock line
        # mgt_gpio[2]   SFP0: PHY1 RESET    PHY reset when '1'
        # mgt_gpio[1]   SFP0: PHY0 RESET    PHY reset when '1'
        # mgt_gpio[0]   SFP0: MDIO Enable   Enable MDIO mode when '1'
        '''
        # set EMAC MDIO configuration clock divisor and enable MDIO
        self._mdio_sw_operation(operation = mdio_operations['conf_write'], address = 0x340, data = 0x7f)

    def mdio_sw_write(self, phy, channel, address, mapped_address, data):
        #print 'WRITE card(%i) phy(%i) chan(%i) address(0x%04x) mapped_address(0x%04x) data(0x%04x)' % (self.slot, phy, channel, address, mapped_address, data)
        #sys.stdout.flush()
        return self._mdio_sw_rw(phy = phy, channel = channel, address = address, mapped_address = mapped_address, writedata = data)
    
    def mdio_sw_read(self, phy, channel, address, mapped_address):
        #print 'READ card(%i) phy(%i) chan(%i) address(0x%04x) mapped_address(0x%04x)' % (self.slot, phy, channel, address, mapped_address)
        #sys.stdout.flush()
        return self._mdio_sw_rw(phy = phy, channel = channel, address = address, mapped_address = mapped_address, writedata = None)

    def _mdio_sw_rw(self, phy, channel, address, mapped_address, writedata = None):
        self.select()
        self.mdio_enable_sw_control()
        # set MDIO address addr x addr_offs  ie 1Ex0102
        phy_mdio_paddr = phy_channel_to_mdio_paddr[phy][channel]
        #print '\tcard(%i) phy(%i) channel(%i) address(0x%04x) mapped_address(0x%04x) phy_paddr(0x%04x) combo_address(0x%04x) %s' % (self.slot,
        #    phy, channel, address, mapped_address, phy_mdio_paddr, phy_mdio_paddr + address,
        #    ('' if writedata == None else 'writedata(0x%04x)' % writedata),)
        #sys.stdout.flush()
        self._mdio_sw_operation(operation = mdio_operations['address'], address = phy_mdio_paddr + address, data = mapped_address)
        if writedata != None:
            # write to MDIO address selected
            self._mdio_sw_operation(operation = mdio_operations['write'], data = writedata)
            return 0
        else:
            # read from MDIO address selected
            return self._mdio_sw_operation(operation = mdio_operations['read'])

    def _mdio_sw_operation(self, operation, address = None, data = None):
        '''
        Perform a basic MDIO software operation on the FPGA.
        '''
        self.fpga.write_int('sfp_op_type',  operation)
        if address != None:
            self.fpga.write_int('sfp_op_addr',  address)
        if data != None:  
            self.fpga.write_int('sfp_op_data',  data) 
        self.fpga.write_int('sfp_op_issue', 1)
        if operation == mdio_operations['read']:
            return self.fpga.read_int('sfp_op_result')
            
    def print_regs(self, slave_id, bytes_to_read):
        for phy in self.phys:
            for m in self.modules:
                m.print_channel_regs(slave_id = slave_id, bytes_to_read = bytes_to_read)

class Sfp_phy(object):
    '''A Vitesse VSC8488 phy on a mezzanine card.
    '''
    def __init__(self, card, phy_number):
        self.card = card
        self.id = phy_number
        self._probe_modules()

    def reset(self):
        ''' Reset this phy.
        '''
        phy = self.id
        phy_value = -1
        if phy == -1:
            phy_value = 0x186               # 0b0001 1000 0110
        else:
            if self.card.slot == 0:
                if phy == 0:
                    phy_value = 0x002       # 0b0000 0000 0010
                elif phy == 1:
                    phy_value = 0x004       # 0b0000 0000 0100
            elif self.card.slot == 1:
                if phy == 0:
                    phy_value = 0x080       # 0b0000 1000 0000
                elif phy == 1:
                    phy_value = 0x100       # 0b0001 0000 0000
        if phy_value == -1:
            raise ValueError('Mezzanine(%i), Phy(%i) produce invalid phy value.' % (self.card, phy))
        self.card.fpga.write_int('sfp_gpio_data_oe',  phy_value)   # Set Output Enable for all phy resets
        self.card.fpga.write_int('sfp_gpio_data_out', phy_value)   # Assert Reset high for all phys
        self.card.fpga.write_int('sfp_gpio_data_out', 0)           # Deassert Reset for all phys
        '''
        # mgt_gpio[11]  Unused 
        # mgt_gpio[10]  SFP1: MDIO          MDIO data line
        # mgt_gpio[9]   SFP1: MDC           MDIO clock line
        # ENABLE SW RESET => mgt_gpio[8]   SFP1: PHY1 RESET    PHY reset when '1'
        
        # ENABLE SW RESET => mgt_gpio[7]   SFP1: PHY0 RESET    PHY reset when '1'
        # mgt_gpio[6]   SFP1: MDIO Enable   Enable MDIO mode when '1'
        # mgt_gpio[5]   Unused 
        # mgt_gpio[4]   SFP0: MDIO          MDIO data line
    
        # mgt_gpio[3]   SFP0: MDC           MDIO clock line
        # ENABLE SW RESET => mgt_gpio[2]   SFP0: PHY1 RESET    PHY reset when '1'
        # ENABLE SW RESET => mgt_gpio[1]   SFP0: PHY0 RESET    PHY reset when '1'
        # mgt_gpio[0]   SFP0: MDIO Enable   Enable MDIO mode when '1'
        '''

    def mdio_sw_write(self, channel, address, mapped_address, data):
        return self.card.mdio_sw_write(phy = self.id, channel=channel, address=address, mapped_address=mapped_address, data=data)
    
    def mdio_sw_read(self, channel, address, mapped_address):
        return self.card.mdio_sw_read(phy = self.id, channel=channel, address=address, mapped_address=mapped_address)

    def check_connection(self):
        '''Read the global ID register, 1ex0000 - the default value is 0x8488 and we don't change it.
        '''
        testvals  = [[0xdead ^ self.card.slot, 0x5aa5 ^ self.card.slot], [0xa55a ^ self.card.slot, 0xbeef ^ self.card.slot]]
        test_address = 0x7fd5
        default_val = 0xff00
        # read the default value of the global ID register
        phy_val = self.mdio_sw_read(channel = 0, address = 0x1e, mapped_address = 0x0000)
        #print('card(%i) phy(%i) 1ex0000 value(0x%04x)' % (self.slot, self.id, phy_val))
        if not phy_val == 0x8488:
            raise RuntimeError('No connection to PHY %i: error reading from global ID register.' % self.id)
        # check that we can write by writing two different values to the temperature monitor threshold register
        phy_val = self.mdio_sw_read(channel = 0, address = 0x1e, mapped_address = test_address)
        #print('card(%i) phy(%i) 1ex%04x value(0x%04x)' % (self.slot, self.id, test_address, phy_val))
        if not phy_val == default_val:
            raise RuntimeError('No connection to PHY %i: error reading default from 0x%04x.' % (self.id, test_address))
        for ctr in range(0,2):
            self.mdio_sw_write(channel = 0, address = 0x1e, mapped_address = test_address, data = testvals[ctr][self.id])
            phy_val = self.mdio_sw_read(channel = 0, address = 0x1e, mapped_address = test_address)
            #print('card(%i) phy(%i) 1ex%04x test_val(0x%04x) value(0x%04x)' % (self.slot, self.id, test_address, testvals[ctr][self.id], phy_val))
            if not phy_val == testvals[ctr][self.id]:
                raise RuntimeError('No connection to PHY %i: error reading written value from 0x%04x.' % (self.id, test_address))
        # restore defaults
        self.mdio_sw_write(channel = 0, address = 0x1e, mapped_address = test_address, data = default_val)

    def read_link_status(self, channel):
        """
        PHY XS Status1 (4x0001) Transmit Link Status
        PCS Status: PCS Status 1 (3x0001) Receive Link Status
        """
        rv = {}
        regdata = self.mdio_sw_read(channel = channel, address = 3, mapped_address = 0x0001)
        rv['rx'] = (regdata >> 2) & 0x01
        regdata = self.mdio_sw_read(channel = channel, address = 4, mapped_address = 0x0001)
        rv['tx'] = (regdata >> 2) & 0x01
        return rv

    def read_temperature(self):
        '''
        Temperature is per phy - both channels will read the same value.
        '''
        self.mdio_sw_write(channel = 0, address = 0x1e, mapped_address = 0x7fd6, data = 1 << 12)
        self.mdio_sw_write(channel = 0, address = 0x1e, mapped_address = 0x7fd6, data = (1 << 11) | (1 << 12))
        regdata = self.mdio_sw_read(channel = 0, address = 0x1e, mapped_address = 0x7fd6)
        #print '(%i,%i): 0x%04x 0x%04x' % (phy, 0, regdata, regdata & 0xff00) 
        while regdata & (1 << 10) != (1 << 10):
            regdata = self.self.mdio_sw_read(channel = 0, address = 0x1e, mapped_address = 0x7fd6)
        return ((regdata & 0xff) * -1.081) + 233.5

    def _probe_modules(self):
        self.modules = []
        for ctr in range(2):
            module = Sfp_module(self, ctr)
            if module is not None:
                self.modules.append(module)

    '''
    SFP I2C operations
    '''
    def sfp_i2c_enable_gpio(self, force = False):
        '''Set up I2C bus to the SFP modules.
        '''
        if True:
        #if (not self._i2c_bus_enabled) or force:
            self.mdio_sw_write(channel = 0, address = 0x1e, mapped_address = 0x0108, data = 8404)  # set pin as SDA bus#0
            self.mdio_sw_write(channel = 0, address = 0x1e, mapped_address = 0x010a, data = 8404)  # set pin as SCL bus#0
            self.mdio_sw_write(channel = 0, address = 0x1e, mapped_address = 0x012c, data = 8404)  # set pin as SDA bus#1
            self.mdio_sw_write(channel = 0, address = 0x1e, mapped_address = 0x012e, data = 8404)  # set pin as SCL bus#1
            #self._i2c_bus_enabled = True

    def sfp_i2c_check_busy(self, channel = 0, max_attempts = 5, timeout = -1, sleep_time = 0):
        '''Check the status of the MDIO/I2C command status - we want 0 on bits 3:2 of SFP register 1ex8000.
        '''
        attempt_ctr = 0
        timed_out = False
        time_start = time.time()
        res = self.mdio_sw_read(channel = channel, address = 0x1e, mapped_address = 0x8000) & 0xc
        while (res != 0) and not timed_out:
            #print 'sfp_i2c_check_busy(%i,%i) attempt_ctr(%i)' % (phy, channel, attempt_ctr)
            res = self.mdio_sw_read(channel = channel, address = 0x1e, mapped_address = 0x8000) & 0xc
            attempt_ctr += 1
            timed_out = ((timeout > 0) and (time.time() - time_start > timeout)) or (attempt_ctr >= max_attempts)
            if (sleep_time > 0) and not timed_out:
                time.sleep(sleep_time)
        if timed_out:
            if attempt_ctr == max_attempts:
                logger.info('sfp_i2c_check_busy: max attempts, %i, reached with bus still busy.' % max_attempts)
            else:
                logger.info('sfp_i2c_check_busy: timed out after %3.3fs with bus still busy.' % timeout)
            return True
        return False

    def set_rx_leds(self):
        """ # Table 152.
        # VSC8488-15 Datasheet
        # Registers
        # GPIO_1 Config/Status (1Ex0102) (continued)
        # Bit 15 Traditional GPIO_1 Output Controls whether the pin is in input or output 
        # Tri-state Control mode. Bit usage applies only when the GPIO 
        #                   pin is configured as a traditional GPIO pin (bits 
        #                   2:0=000) 
        #                   0: Output mode
        #                   1: Input mode 
        # Bit 2-0:
        # Selection 000: Traditional GPIO behavior 
        #           001: PCS Activity LED output 
        #           010: WIS Interrupt Output 
        #           011: Transmit internal signals 
        #           100-111: Reserved for future use.
        """
        self.mdio_sw_write(channel = 0, address = 0x1e, mapped_address = 0x102, data = 1)
        self.mdio_sw_write(channel = 0, address = 0x1e, mapped_address = 0x126, data = 1)
    
    def set_tx_leds(self):
        """ Table 152.
        # VSC8488-15 Datasheet
        # Registers
        # GPIO_1 Config/Status (1Ex0102) (continued)
        # Bit 15 Traditional GPIO_1 Output Controls whether the pin is in input or output 
        # Tri-state Control mode. Bit usage applies only when the GPIO 
        #                   pin is configured as a traditional GPIO pin (bits 
        #                   2:0=000) 
        #                   0: Output mode
        #                   1: Input mode 
        # Bit 2-0:
        # Selection 000: Traditional GPIO behavior 
        #           001: PCS Activity LED output 
        #           010: WIS Interrupt Output 
        #           011: Transmit internal signals 
        #           100-111: Reserved for future use.
        """
        self.mdio_sw_write(channel = 0, address = 0x1e, mapped_address = 0x104, data = 1)

    def fec_enable_check(self):
        fec_en = {}
        for module in self.modules:
            regdata = self.mdio_sw_read(channel = module.id, address = 1, mapped_address = 0x00aa)
            regdata = regdata & 0x03
            fec_en[module.id] = {}
            fec_en[module.id]['value'] = regdata
            fec_en[module.id]['supported'] = (regdata & 0x01) == 0x01
            fec_en[module.id]['error_reporting'] = (regdata & 0x02) == 0x02
            if regdata == 3:
                rv = fec_en[module.id]['locked'] = self._fec_enable(module.id)
            #else:
            #    print 'ERROR: PHY(%i) channel(%i): supports FEC: %i, supports FEC error reporting: %i, 1x00aa(0x%04x)' % (phy, channel, regdata & 0x01, (regdata & 0x02) >> 1, regdata)
        return fec_en

    def _fec_enable(self, channel_number):
        # enable FEC and error reporting
        self.mdio_sw_write(channel = channel_number, address = 1, mapped_address = 0x00ab, data = 3)
        # reset FEC counters
        self.mdio_sw_write(channel = channel_number, address = 1, mapped_address = 0x8300, data = 1)
        self.mdio_sw_write(channel = channel_number, address = 1, mapped_address = 0x8300, data = 0)
        # wait for the FEC to achieve lock
        tries = 0
        regdata = 0
        while (regdata != 0x02) and (tries < 10):
            regdata = self.mdio_sw_read(channel = channel_number, address = 1, mapped_address = 0x8300)
            regdata = regdata & 0x02
            tries += 1
        #print '\tGot result for FEC enable in %i tries - 0x%04x' % (tries, regdata)
        if tries == 10:
            #print 'ERROR: PHY(%i) channel(%i): FEC not locking' % (phy, channel)
            return False
        else:
            #print 'PHY(%i) channel(%i): FEC locked' % (phy, channel)
            return True

    def fec_read_counts(self, fec_capabilities = {}):
        """
        See tables 205-8 for details.
        KR FEC Corrected Lower (1x00AC)
        KR FEC Corrected Upper (1x00AD)
        KR FEC Uncorrected Lower (1x00AE)
        KR FEC Uncorrected Upper (1x00AF)
        """
        if len(fec_capabilities) == 0:
            fec_capabilities = self.fec_enable_check()
        fec_counters = {}
        for module in self.modules:
            fec_counters[module.id] = {'corrected': -1, 'uncorrected': -1}
            if fec_capabilities[module.id]['value'] == 0x03:
                corrdata_lower =    self.mdio_sw_read(channel = module.id, address = 1, mapped_address = 0x00ac)
                corrdata_upper =    self.mdio_sw_read(channel = module.id, address = 1, mapped_address = 0x00ad)
                uncorrdata_lower =  self.mdio_sw_read(channel = module.id, address = 1, mapped_address = 0x00ae)
                uncorrdata_upper =  self.mdio_sw_read(channel = module.id, address = 1, mapped_address = 0x00af)
                fec_counters[module.id]['corrected'] = (corrdata_upper << 8) + corrdata_lower
                fec_counters[module.id]['uncorrected'] = (uncorrdata_upper << 8) + uncorrdata_lower
        return fec_counters

class Sfp_module(object):
    ''' An SFP module plugged into a Sfp+ mezzanine card, connected to one of the two Vitesse SFP PHYs.
    '''
    def __init__(self, phy, module_id):
        self.phy = phy
        self.id = module_id

    def read_module_regs(self, slave_id = 0x0050, slave_address = 0x0000, num_bytes_to_read = 0x0020):
        '''
        # Table 152.
        # VSC8488-15 Datasheet
        30x8001: slave device ID, using 7-bit addressing, default 0x50 for slave ID 0xA0, 0x51 for slave ID 0xA1
        30x8002: starting slave device memory location, default 0x0000
        30x8003: number of registers to be read, default 0x0020 (32)
        30x8004: starting on-device register address to store read data, default 0x8010
        30x8005: write register, default 0x0000
        The user can write to 30x8000 to start two-wire serial (master) operation:
        30x8000.15: two-wire serial speed, 0: 400 kHz; 1: 100 kHZ
        30x8000.14: Interface, 0: MDIO/two-wire serial slave; 1: uP
        30x8000.13: reserved, should be 0x0
        30x8000.12: disable reset sequence, 0: enable reset sequence; 1: disable reset
           sequence
        30x8000.11:5: reserved, should be 0x0
        30x8000.4: read or write action, 0: read, 1: write
        30x8000.3:2: instruction status for MDIO/two-wire serial slave interfaces, 00: idle;
           01: command completed successfully; 10: command in progress; 11: command
          failed.
        30x8000.1:0: instruction status for uP interface, 00: idle; 01: command completed
           successfully; 10: command in progress; 11: command failed.
        '''
        '''
        The per channel two-wire serial bus interface pins SDA and SCL available for connection
        to SFP/SFP+ modules may be used as general purpose I/O (GPIO) when the two-wire
        serial (master) function is not needed. Registers 30x012C, 30x012E, 30x0104,
        30x0106, 30x0118, 30x011A, 30x010C, 30x010E program whether the pins function as
        two-wire serial interface pins or GPIO
        '''
        self.phy.sfp_i2c_enable_gpio()  
        if slave_address >= 96:
            #raise RuntimeError('SFP registers 96 and above are vendor-specific, so we do not want to be doing anything there.')
            placeholder = True
        elif slave_address > 63:
            #print 'SFP registers from 64 to 95 are extended. Are you sure they are implemented?'
            placeholder = 0
        #print 'want %i bytes, %i words from address 0x%04x, slave_id(0x%02x)' % (num_bytes_to_read, num_bytes_to_read/2, slave_address, slave_id)
        # You can only read 16 words of data at a time, 32 bytes, so break up larger amounts into multiple reads
        if num_bytes_to_read % 2 != 0:
            num_bytes_to_read += 1
        # set the slave id
        self.phy.mdio_sw_write(channel = self.id, address = 0x1e, mapped_address = 0x8001, data = slave_id)
        # get the data
        words_left = num_bytes_to_read / 2
        saddress = slave_address
        words = []
        while words_left > 0:
            get_words = min(16, words_left)
            words_left -= get_words
            #print 'reading %i words from 0x%04x, %i left to get' % (get_words, saddress, words_left)
            self.phy.mdio_sw_write(channel = self.id, address = 0x1e, mapped_address = 0x8002, data = saddress)
            self.phy.mdio_sw_write(channel = self.id, address = 0x1e, mapped_address = 0x8003, data = get_words * 2)
            saddress += (get_words*2)
            # read command - see description for register 1ex8000
            self.phy.mdio_sw_write(channel = self.id, address = 0x1e, mapped_address = 0x8000, data = 0x0000)
            # is the device still busy?
            if self.phy.sfp_i2c_check_busy(channel = self.id):
                logger.info('SFP still busy - want to carry on?')
            # read the data from the interface
            for offset in range(0, get_words):
                word = self.phy.mdio_sw_read(channel = self.id, address = 0x1e, mapped_address = 0x8010 + offset)
                words.append(word)
        rv = numpy.uint8(numpy.zeros(num_bytes_to_read))
        for ctr, word in enumerate(words):
            rv[ctr*2] = numpy.uint8(word & 0xff)
            rv[(ctr*2) + 1] = numpy.uint8(word >> 8)
        return rv

    def write_module_regs(self, phy, channel = 0, slave_id = 0x0050, slave_start_address = 0x0000, bytes_to_write = [], check_write = False):
        """    # Table 152.
        # VSC8488-15 Datasheet
        30x8001: slave device ID, using 7-bit addressing, default 0x50 (for slave ID A0)
        30x8002: starting slave device memory location, default 0x0000
        30x8003: number of registers to be read, default 0x0020 (32)
        30x8004: starting on-device register address to store read data, default 0x8010
        30x8005: write register, default 0x0000
        The user can write to 30x8000 to start two-wire serial (master) operation:
        30x8000.15: two-wire serial speed, 0: 400 kHz; 1: 100 kHZ
        30x8000.14: Interface, 0: MDIO/two-wire serial slave; 1: uP
        30x8000.13: reserved, should be 0x0
        30x8000.12: disable reset sequence, 0: enable reset sequence; 1: disable reset
           sequence
        30x8000.11:5: reserved, should be 0x0
        30x8000.4: read or write action, 0: read, 1: write
        30x8000.3:2: instruction status for MDIO/two-wire serial slave interfaces, 00: idle;
           01: command completed successfully; 10: command in progress; 11: command
          failed.
        30x8000.1:0: instruction status for uP interface, 00: idle; 01: command completed
           successfully; 10: command in progress; 11: command failed.
           """
        """
        The per channel two-wire serial bus interface pins SDA and SCL available for connection
        to SFP/SFP+ modules may be used as general purpose I/O (GPIO) when the two-wire
        serial (master) function is not needed. Registers 30x012C, 30x012E, 30x0104,
        30x0106, 30x0118, 30x011A, 30x010C, 30x010E program whether the pins function as
        two-wire serial interface pins or GPIO
        """
        raise NotImplementedError('Not used, untested...')
        self.phy.mdio_sw_write(phy = phy, channel = channel, address = 0x1e, mapped_address = 0x8001, data = slave_id)
        
        if isinstance(bytes_to_write, list):
            bytes_to_write = numpy.uint8(bytes_to_write)
        if bytes_to_write.size % 2 != 0:
            raise RuntimeError('Byte array of size %i was passed to function. Must be a multiple of two to fit 16-bit words.' % bytes_to_write.size)
        
        # write all the data required
        for word_ctr in range(0, bytes_to_write.size/2):
            address_to_write = slave_start_address + word_ctr
            data_to_write = (bytes_to_write[(word_ctr*2)+1] << 8) + (bytes_to_write[word_ctr*2] & 0xff) 
            print 'Writing SFP register data(0x%04x) to slave address(0x%04x). ' % (data_to_write, address_to_write)
            self.phy.mdio_sw_write(channel = channel, address = 0x1e, mapped_address = 0x8002, data = address_to_write)
            # is the device still busy?
            print 'Checking busy 0...'
            if self.phy.sfp_i2c_check_busy(channel = channel):
                print 'SFP still busy - want to carry on?'
            # the actual data
            print 'loading data...'
            self.phy.mdio_sw_write(channel = channel, address = 0x1e, mapped_address = 0x8005, data = data_to_write)
            print 'Checking busy 1...'
            if self.phy.sfp_i2c_check_busy(channel = channel):
                print 'SFP still busy - want to carry on?'
            # write command - see description for register 1ex8000
            print 'write command'
            self.phy.mdio_sw_write(channel = channel, address = 0x1e, mapped_address = 0x8000, data = 0x0010)
            # is the device still busy?
            print 'Checking busy 2...'
            if self.phy.sfp_i2c_check_busy(channel = channel):
                print 'SFP still busy - want to carry on?'
            print '\n----------------\n'
        # check if required
        write_errors = -1
        if check_write:
            write_errors = 0
            read_back = self.read_sfp_module_regs(phy = phy, channel = channel, slave_id = slave_id, slave_address = slave_start_address, num_bytes_to_read = bytes_to_write.size)
            for word_ctr in range(0, bytes_to_write.size / 2):
                wrote = (bytes_to_write[(word_ctr*2)+1] << 8) + (bytes_to_write[word_ctr*2] & 0xff)
                read = (read_back[(word_ctr*2)+1] << 8) + (read_back[word_ctr*2] & 0xff)
                print 'address(0x%08x) wrote(0x%04x) read(0x%04x)' % (slave_start_address + word_ctr, wrote, read)
                if wrote != read:
                    write_errors += 1
        return write_errors

    def print_module_regs(self, slave_id, bytes_to_read = 16):
        print 'PHY(%02i) channel(%02i) slave_id(0x%02x):' % (self.phy.id, self.id, slave_id)
        regdata = self.read_module_regs(slave_id = slave_id, num_bytes_to_read = bytes_to_read)
        if slave_id == 0x50: slave_id = 0xa0
        elif slave_id == 0x51: slave_id = 0xa2
        for reg in range(bytes_to_read):
            print '\treg(%02i)-' % reg,
            try:
                if sfp_module_reg[slave_id][reg]['type'] == 'value':
                    print '%s' % sfp_module_reg[slave_id][reg][regdata[reg]]
                elif sfp_module_reg[slave_id][reg]['type'] == 'bit':
                    print '%s' % sfp_module_reg[slave_id][reg][regdata[reg]]
                elif sfp_module_reg[slave_id][reg]['type'] == 'register':
                    print '%s(0x%04x)' % (sfp_module_reg[slave_id][reg]['description'], regdata[reg])
                else:
                    print 'unknown/undocumented register?'
            except:
                print 'Exception: unknown/undocumented register?'

    def check_diagnostic_support(self, phy, channel):
        regdata = self.read_module_regs(slave_id = 0x50, slave_address = 92, num_bytes_to_read = 4)
        return (int(regdata[0]) & 104) == 104

    def read_temp(self):
        regdata = self.read_module_regs(slave_id = 0x51, slave_address = 96, num_bytes_to_read = 4)
        channel_temp = int(regdata[0])
        if regdata[0] & 128 == 0:
            channel_temp += regdata[1]/256.0
        else:
            channel_temp -= regdata[1]/256.0
        return channel_temp, 'Temp: %.5fC' % channel_temp

    def read_voltage(self):
        regdata = self.read_module_regs(slave_id = 0x51, slave_address = 98, num_bytes_to_read = 4)
        adc_val = ((regdata[1]) << 8) + regdata[0]
        return_volt = adc_val * 100.0/1e6  # LSB = 100uV
        return return_volt, 'Voltage: %.5fV' % return_volt
    
    def read_tx_bias_current(self):
        regdata = self.read_module_regs(slave_id = 0x51, slave_address = 100, num_bytes_to_read = 4)
        adc_val = ((regdata[1]) << 8) + regdata[0]
        return_mA = adc_val * 2.0/1e6  # LSB = 2uA
        return return_mA, 'TX bias current: %.5fA' % return_mA
    
    def read_tx_power(self):
        regdata = self.read_module_regs(slave_id = 0x51, slave_address = 102, num_bytes_to_read = 4)
        adc_val = ((regdata[1]) << 8) + regdata[0]
        return_mW = adc_val * 0.1/1e6  # LSB = 0.1uW
        return return_mW, 'TX power: %.5fmW' % return_mW
    
    def read_rx_power(self):
        regdata = self.read_module_regs(slave_id = 0x51, slave_address = 104, num_bytes_to_read = 4)
        adc_val = ((regdata[1]) << 8) + regdata[0]
        return_mW = adc_val * 0.1/1e6  # LSB = 0.1uW
        return return_mW, 'RX power: %.5fmW' % return_mW
    
    def read_stat(self):
        regdata = self.read_module_regs(slave_id = 0x51, slave_address = 110, num_bytes_to_read = 4)
        return_string = 'read_stat: 0x%04x' % regdata[0]
        #for bit in range(8):
        #    bitval = regdata[0] & (0x01 << bit)
        #    return_string += '%02i: %01i : %s\n' % (bit, bitval >> bit, sfp_module_reg[0xa2][110][bitval])
        return regdata[0], return_string

    def read_vendor_name(self):
        regdata = self.read_module_regs(slave_id = 0x50, slave_address = 20, num_bytes_to_read = 16)
        vname = ''
        for i in range(16):
            vname += chr(regdata[i])
        return vname
    
    def read_serial_number(self):
        regdata = self.read_module_regs(slave_id = 0x50, slave_address = 68, num_bytes_to_read = 16)
        vname = ''
        for i in range(16):
            vname += chr(regdata[i])
        return vname

'''
MDIO definitions
'''    
mdio_operations = {
                   # LSB signifies EMAC configuration or not.
                   # Bits 2:1 are the MDIO opcodes as described in Table 82
                   # MDIO opcodes
                   'address':      0, # 0b000 - 0 << 1
                   'write':        2, # 0b010 - 1 << 1    
                   'rd_addr_inc':  4, # 0b100 - 2 << 1
                   'read':         6, # 0b110 - 3 << 1
                   # EMAC configuration
                   'conf_write':   3, # 0b011
                   'conf_read':    5, # 0b101
                   }

'''
map phy numbers to phys and channels
phy num 0 = phy 0, channel 0
phy num 1 = phy 0, channel 1
phy num 2 = phy 1, channel 0
phy num 3 = phy 1, channel 1
'''
phy_num_to_phy_and_channel = {0:(0,0), 
                              1:(0,1),
                              2:(1,0),
                              3:(1,1),}
phy_num_to_mdio_paddr = {0: 0x0000,
                         1: 0x0100,
                         2: 0x1e00,
                         3: 0x1f00,}
phy_channel_to_mdio_paddr = {0: {0: 0x0000, 1: 0x0100},
                             1: {0: 0x1e00, 1: 0x1f00},}

'''
SFP module register descriptions - use dictionaries
'''
sfp_module_reg = {}
sfp_module_reg[0xa0] = {}
sfp_module_reg[0xa2] = {}
sfp_module_reg[0xa0][0] = {
                           'type': 'value',
                           0x0  : 'Unknown or unspecified',
                           0x1  : 'GBIC',
                           0x2  : 'Module soldered to motherboard (ex: SFF)',
                           0x3  : 'SFP or SFP Plus',
                           0x4  : 'Reserved for sfp_module_i2c_a0_byte1 = <300 pin XBI devices',
                           0x5  : 'Reserved for Xenpak devices',
                           0x6  : 'Reserved for XFP devices',
                           0x7  : 'Reserved for XFF devices',
                           0x8  : 'Reserved for XFP-E devices',
                           0x9  : 'Reserved for XPak devices',
                           0xa  : 'Reserved for X2 devices',
                           0xb  : 'Reserved for DWDM-SFP devices',
                           0xc  : 'Reserved for QSFP devices',
                           0x80 : 'Reserved, unallocated'}
sfp_module_reg[0xa0][1] = {
                            'type': 'value',
                            0x00 : 'GBIC definition is not specified or the GBIC definition is not compliant with a defined MOD_DEF. See product specification for details.',
                            0x01 : 'GBIC is compliant with MOD_DEF 1',
                            0x02 : 'GBIC is compliant with MOD_DEF 2',
                            0x03 : 'GBIC is compliant with MOD_DEF 3',
                            0x04 : 'GBIC/SFP function is defined by two-wire interface ID only',
                            0x05 : 'GBIC is compliant with MOD_DEF 5',
                            0x06 : 'GBIC is compliant with MOD_DEF 6',
                            0x07 : 'GBIC is compliant with MOD_DEF 7',
                            0x08 : 'Unallocated'}
sfp_module_reg[0xa0][2] = {
                           'type': 'value',
                            0x00 : 'Unknown or unspecified',
                            0x01 : 'SC',
                            0x02 : 'Fibre Channel Style 1 copper connector',
                            0x03 : 'Fibre Channel Style 2 copper connector',
                            0x04 : 'BNC/TNC',
                            0x05 : 'Fibre Channel coaxial headers',
                            0x06 : 'FiberJack',
                            0x07 : 'LC',
                            0x08 : 'MT-RJ',
                            0x09 : 'MU',
                            0x0A : 'SG',
                            0x0B : 'Optical pigtail',
                            0x0C : 'MPO Parallel Optic',
                            0x20 : 'HSSDC II',
                            0x21 : 'Copper pigtail',
                            0x22 : 'RJ45',
                            0x23 : 'Unallocated',
                            0x80 : 'Vendor specific'}
sfp_module_reg[0xa0][3] = {
                           'type': 'value',
                            # 10G Ethernet Compliance Codes
                            128 : '10G Base-ER',
                            64  : '10G Base-LRM',
                            32  : '10G Base-LR',
                            16  : '10G Base-SR',
                            # Infiniband Compliance Codes
                            8 : '1X SX',
                            4 : '1X LX',
                            2 : '1X Copper Active',
                            1 : '1X Copper Passive'}
sfp_module_reg[0xa0][4] = {
                           'type': 'value',
                            # ESCON & SONET Compliance Codes
                            0 : 'N/A'}
sfp_module_reg[0xa0][5] = {
                           'type': 'value',
                            # ESCON & SONET Compliance Codes
                            0 : 'N/A'}
sfp_module_reg[0xa0][6] = {
                           'type': 'bit',
                            # Ethernet Compliance Codes
                            128 : 'BASE-PX 3',
                            64  : 'BASE-BX10 3',
                            32  : '100BASE-FX',
                            16  : '100BASE-LX/LX10',
                            8 : '1000BASE-T',
                            4 : '1000BASE-CX',
                            2 : '1000BASE-LX 3',
                            1 : '1000BASE-SX'}
sfp_module_reg[0xa0][7] = {
                           'type': 'bit',
                            # Fibre Channel Link Length
                            128 : 'very long distance (V)',
                            64  : 'short distance (S)',
                            32  : 'intermediate distance (I)',
                            16  : 'long distance (L)',
                            8 : 'medium distance (M)',
                            # Fibre Channel Technology
                            4 : 'Shortwave laser, linear Rx (SA)',
                            2 : 'Longwave laser (LC)',
                            1 : 'Electrical inter-enclosure (EL)'}
sfp_module_reg[0xa0][8] = {
                           'type': 'bit',
                            # Fibre Channel Technology
                            128 : 'Electrical intra-enclosure (EL)',
                            64  : 'Shortwave laser w/o OFC (SN)',
                            32  : 'Shortwave laser with OFC4 (SL)',
                            16  : 'Longwave laser (LL)',
                            # SFP+ Cable Technology
                            8 : 'Active Cable',
                            4 : 'Passive Cable',
                            2 : 'Unallocated',
                            1 : 'Unallocated'}
sfp_module_reg[0xa0][9] = {
                           'type': 'bit',
                            # Fibre Channel Transmission Media
                            128 : 'Twin Axial Pair (TW)',
                            64  : 'Twisted Pair (TP)',
                            32  : 'Miniature Coax (MI)',
                            16  : 'Video Coax (TV)',
                            8 : 'Multimode, 62.5um (M6)',
                            4 : 'Multimode, 50um (M5, M5E)',
                            2 : 'Unallocated',
                            1 : 'Single Mode (SM)'}
sfp_module_reg[0xa0][10] = {
                            'type': 'bit',
                            # Fibre Channel Speed
                            128 : '1200 MBytes/sec',
                            64  : '800 MBytes/sec',
                            32  : '1600 MBytes/sec',
                            16  : '400 MBytes/sec',
                            8 : 'Unallocated',
                            4 : '200 MBytes/sec',
                            2 : 'Unallocated',
                            1 : '100 MBytes/sec',
                            0 : 'Unallocated'}
sfp_module_reg[0xa0][11] = {
                            'type': 'value',
                            # Description of encoding mechanism
                            0x00 : 'Unspecified',
                            0x01 : '8B/10B',
                            0x02 : '4B/5B',
                            0x03 : 'NRZ',
                            0x04 : 'Manchester',
                            0x05 : 'SONET Scrambled',
                            0x06 : '64B/66B',
                            0x07 : 'Unallocated'}
sfp_module_reg[0xa0][12] = {
                            'type': 'register',
                            'description'   :   'The nominal bit (signaling) rate (BR, nominal) is specified in units of 100 MBd.'}
sfp_module_reg[0xa0][13] = {
                            'type': 'value',
                            0x00 : 'Unspecified',
                            0x01 : 'Defined for SFF-8079 (4/2/1G Rate_Select & AS0/AS1)',
                            0x02 : 'Defined for SFF-8431 (8/4/2G Rx Rate_Select only)',
                            0x03 : 'Unspecified',
                            0x04 : 'Defined for SFF-8431 (8/4/2G Tx Rate_Select only)',
                            0x05 : 'Unspecified',
                            0x06 : 'Defined for SFF-8431 (8/4/2G Independent Rx & Tx Rate_select)',
                            0x07 : 'Unspecified',
                            0x08 : 'Defined for FC-PI-5 (16/8/4G Rx Rate_select only) High=16G only, Low=8G/4G',
                            0x09 : 'Unspecified',
                            0x0A : 'Defined for FC-PI-5 (16/8/4G Independent Rx, Tx Rate_select) High=16G only, Low=8G/4G'}
sfp_module_reg[0xa0][14] = {
                            'type': 'register',
                            'description'   :   'Supported single-mode fiber link length, in km.'}
sfp_module_reg[0xa0][15] = {
                            'type': 'register',
                            'description'   :   'Unknown.'}
sfp_module_reg[0xa2][110] = {
                            128 : 'TX Disable',
                            64  : 'Soft TX Disable',
                            32  : 'RS(1) State',
                            16  : 'Rate_Select State',
                            8 : 'Soft Rate_Select',
                            4 : 'TX Fault State',
                            2 : 'Rx_LOS State',
                            1 : 'Data_Ready_Bar State'}

'''
PHY register descriptions- from page 203 of the datasheet
'''
'''
reg_device_id = {'name' : 'Device ID',
                 'base_address' :   0x1e,
                 'mapped_address':  0x0000,
                 'fields': {'device_product_number': (15,0)}
                 }
reg_device_revision = {'name' : 'Device revision',
                 'base_address' :   0x1e,
                 'mapped_address':  0x0001,
                 'fields': {'reserved0':            (15,4),
                            'device_revision_id':   (3,0)}
                 }
reg_software_reset = {'name' : 'Block level software reset',
                 'base_address' :   0x1e,
                 'mapped_address':  0x0002,
                 'fields': {'reserved0':                (15,14),
                            'software_reset_edc_1':     (13,13),
                            'software_reset_edc_0':     (12,12),
                            'reserved1':                (11,10),
                            'software_reset_chan_1':    (9,9),
                            'software_reset_chan_0':    (8,8),
                            'software_reset_mcu':       (7,7),
                            'software_reset_biu':       (6,6),
                            'software_reset_tws_slave': (5,5),
                            'software_reset_tws':       (4,4),
                            'software_reset_mdio':      (3,3),
                            'software_reset_uart':      (2,2),
                            'global_reg_reset':         (1,1),
                            'software_reset_chip':      (0,0)}
                 }
'''
