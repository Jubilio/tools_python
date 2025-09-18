#!/user/bin/env python3

import subprocess


interface = input("Interface (eth0 or wlan0) >> ")
new_mac = input("New Mac Address >> ")

print('[+] Changing MAC address for ' + interface + " to " + new_mac)

subprocess.call(["ifconfig", interface, "down"])
subprocess.call(["ifconfig", interface, "hw", "ether", new_mac])
subprocess.call(["ifconfig", interface, "up"])
