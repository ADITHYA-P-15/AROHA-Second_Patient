import re
import socket
import subprocess
import sys
from urllib.request import urlopen

def candidates():
    result=set(); route_ip=None
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1",80)); route_ip=sock.getsockname()[0]; result.add(route_ip)
    except OSError: pass
    if sys.platform=="win32":
        try:
            output=subprocess.check_output(["ipconfig","/all"],text=True,errors="ignore")
            blocks=re.split(r"(?m)^(?=[^\r\n].*adapter .*:)" , output)
            ignored=re.compile(r"docker|wsl|vEthernet|vmware|virtualbox|loopback|teredo|bluetooth|hyper-v",re.I)
            for block in blocks:
                heading=block.splitlines()[0] if block.splitlines() else ""
                if not ignored.search(heading): result.update(re.findall(r"IPv4 Address[^:]*:\s*([\d.]+)",block))
        except OSError: pass
    else:
        try:
            result.update(re.findall(r"inet ([\d.]+)/",subprocess.check_output(["ip","-4","addr"],text=True,errors="ignore")))
        except OSError: pass
    addresses=sorted(ip for ip in result if not ip.startswith(("127.","169.254.")))
    return ([route_ip] if route_ip in addresses else []) + [ip for ip in addresses if ip != route_ip]
if __name__=="__main__":
    addresses=candidates(); hotspot_prefixes=("192.168.137.","172.20.10.","192.168.43.")
    print("Current LAN URLs (port 8000); use the address on the same Wi-Fi/hotspot as your phone:")
    print("  Local: http://localhost:8000")
    for index,ip in enumerate(addresses):
        url=f"http://{ip}:8000"
        note=" (current network route)" if index == 0 else ""
        note += " (known mobile hotspot range)" if ip.startswith(hotspot_prefixes) else ""
        try:
            with urlopen(f"{url}/api/health", timeout=2) as response:
                note += f" (laptop self-check: HTTP {response.status})"
        except Exception:
            note += " (not reachable from this laptop)"
        print(f"  {url}{note}")
        try:
            import qrcode
            qr=qrcode.QRCode(border=1); qr.add_data(url); qr.make(fit=True); qr.print_ascii(invert=True)
        except Exception: pass
    if addresses and not any(ip.startswith(hotspot_prefixes) for ip in addresses):
        print("Warning: the selected network may isolate Wi-Fi clients (common on campus/office networks).")
    if sys.platform=="win32":
        try:
            rule=subprocess.check_output(["powershell","-NoProfile","-Command","(Get-NetFirewallRule -DisplayName 'The Second Patient LAN (TCP 8000)' -ErrorAction SilentlyContinue).Enabled"],text=True,stderr=subprocess.DEVNULL).strip()
            if rule.lower() != "true":
                print("Windows firewall rule is missing. Run scripts\\open-firewall.ps1 from PowerShell as Administrator and approve the UAC prompt.")
        except OSError: pass
    print("If your phone still cannot connect, confirm both devices share this Wi-Fi/hotspot and that the network allows device-to-device traffic.")
    print("  Docs: http://localhost:8000/docs")
    if not addresses: print("No candidate LAN IPv4 address found; check network adapter and firewall.")
