#!/user/bin/env python3

import subprocess
import optparse
import re 


def get_arguments():
	parser = optparse.OptionParser(description='MAC Address Changer Tool v1.0')
	parser.add_option('-v', '--version', action='store_true', dest='version', help='Show version')
	parser.add_option("-i", "--interface", dest="interface", help="Interface to change MAC Address")
	parser.add_option("-m", "--mac", dest="new_mac", help="New MAC Address")
	(options, arguments) = parser.parse_args()

	if not options.interface:
		parser.error("[-] Please specify an interface, use --help for more info.")
	elif not options.new_mac:
		parser.error("[-] Please specify an interface, use --help for more info.")
	return options


def change_mac(interface, new_mac):
	print(f'[+] Changing MAC address for {interface } to {new_mac}')
	subprocess.call(["ifconfig", interface, "down"])
	subprocess.call(["ifconfig", interface, "hw", "ether", new_mac])
	subprocess.call(["ifconfig", interface, "up"])


def get_current_mac(interface):
	ifconfig_result = subprocess.check_output(['ifconfig', interface]).decode('utf-8')
	mac_address_search_result = re.search(r"\w\w:\w\w:\w\w:\w\w:\w\w:\w\w", ifconfig_result)

	if mac_address_search_result:
		return mac_address_search_result.group(0)
	else:
		print("[-] Could not read MAC Address")


options     = get_arguments()
current_mac = get_current_mac(options.interface)
print(f"Current MAC = {current_mac}")

change_mac(options.interface, options.new_mac)

current_mac = get_current_mac(options.interface)
if current_mac == options.new_mac:
	print(f"[+] MAC address was successfully changed to {current_mac}")
else:
	print("[-] MAC Address did not get changed.")