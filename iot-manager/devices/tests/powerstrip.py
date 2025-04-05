from KasaSmartPowerStrip import SmartPowerStrip

power_strip = SmartPowerStrip('<your power strip ip>')

# get general system info
print(power_strip.get_system_info())

# get the name and other info of a plug; unless the Kasa app is used the plugs won't have a name by default
print(power_strip.get_plug_info(1))

# set the name of a plug
print(power_strip.set_plug_name(1, 'my plug'))

# toggle a plug by number (1-6)
print(power_strip.toggle_plug('off', plug_num=1))

# toggle a plug by name
print(power_strip.toggle_plug('on', plug_name='my plug'))

# toggle multiple plugs by number
print(power_strip.toggle_plugs('on', plug_num_list=[1, 3, 5]))

# toggle multiple plugs by name
print(power_strip.toggle_plugs('on', plug_name_list=['my plug', 'my plug 2']))

# toggle the leds for each relay on or off
print(power_strip.toggle_relay_leds('off'))

# get the current energy usage with mA, mV, mW and the total wh
print(power_strip.get_realtime_energy_info(plug_num=1))

# get a list with the watt hours for each day in the specified month/year
print(power_strip.get_historical_energy_info(month='10', year='2018', plug_num=1))

# reboot the power strip
# NOTE this will toggle all relays off/on but will preserve state after rebooting
# e.g. if it was off before rebooting it will remain off afterwards
print(power_strip.reboot(5))