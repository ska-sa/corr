#!/usr/bin/env python

#'192.168.14.89'
#'192.168.64.229'

import argparse, corr, sfp_mdio, time, sys

parser = argparse.ArgumentParser(description='Print information about the SFP+ mezzanine cards plugged into a ROACH2.')
parser.add_argument('host', type=str, action='store', nargs=1, help='the hostname or IP for the ROACH2 you wish to query')
args = parser.parse_args()

fpga = corr.katcp_wrapper.FpgaClient(args.host[0])
time.sleep(1)
if not fpga.is_connected():
    raise RuntimeError('FPGA not connected?')

sfp_cards = []
for c in range(2):
    card = sfp_mdio.Sfp_mezzanine_card(fpga, c)
    card.initialise()
    sfp_cards.append(card)

for card in sfp_cards:
    print 'Mezzanine card', card.slot, ':'
    for phy in card.phys:
        phy.reset()
        phy.check_connection()
        temperature = phy.read_temperature()
        modules = []
        for m in phy.modules:
            vendor_name = m.read_vendor_name()
            serial_number = m.read_serial_number()
            modules.append({'vendor': vendor_name, 'serial': serial_number})
        print '\tPhy %i:\n\t\ttemperature(%.3fC)' % (phy.id, temperature, )
        for ctr, module in enumerate(modules):
            print '\t\tModule %i: vendor(%s) - s/n(%s)' % (ctr, module['vendor'], module['serial'], )

    print '\tFEC summary:'
    for phy in card.phys:
        fec_capabilities = phy.fec_enable_check()
        fec_counts = phy.fec_read_counts(fec_capabilities = fec_capabilities)
        for m in phy.modules:
            print '\t\tPhy(%i) channel(%i): supported(%i) error_reporting(%i) locked(%i), error counters: corrected(%i) uncorrected(%i)' % (phy.id, m.id,
                           fec_capabilities[m.id]['supported'],
                           fec_capabilities[m.id]['error_reporting'],
                           fec_capabilities[m.id]['locked'],
                           fec_counts[m.id]['corrected'],
                           fec_counts[m.id]['uncorrected'],)

    print '\tLink status:'
    for phy in card.phys:
        for m in phy.modules:
            link_status = phy.read_link_status(m.id)
            print "\t\tPhy(%i) channel(%i): TX_up(%i) RX_up(%i)" % (phy.id, m.id, link_status['tx'], link_status['rx'])
    
    print '\tI2C information:'
    for phy in card.phys:
        for m in phy.modules:
            print '\t\tPhy(%i) channel(%i):' % (phy.id, m.id),
            print m.read_temp()[1],
            print m.read_voltage()[1],
            print m.read_tx_bias_current()[1],
            print m.read_tx_power()[1],
            print m.read_rx_power()[1],
            print m.read_stat()[1]
            
    print '\tMore:'
    for phy in card.phys:
        for m in phy.modules:
            m.print_module_regs(0x50)
            m.print_module_regs(0x51)
    print '\n'
