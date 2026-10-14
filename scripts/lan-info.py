import re
import socket
import subprocess
import sys

def candidates():
    result=set()
    try:
        sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); sock.connect(("192.0.2.1",80)); result.add(sock.getsockname()[0]); sock.close()
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
    return sorted(ip for ip in result if not ip.startswith(("127.","169.254.")))
if __name__=="__main__":
    addresses=candidates(); hotspot_prefixes=("192.168.137.","172.20.10.","192.168.43.")
    print("Candidate URLs (port 8000):")
    print("  Local: http://localhost:8000")
    for ip in addresses:
        url=f"http://{ip}:8000"
        note=" (known mobile hotspot range)" if ip.startswith(hotspot_prefixes) else ""
        print(f"  {url}{note}")
        try:
            import qrcode
            qr=qrcode.QRCode(border=1); qr.add_data(url); qr.make(fit=True); qr.print_ascii(invert=True)
        except Exception: pass
    if addresses and not any(ip.startswith(hotspot_prefixes) for ip in addresses):
        print("Warning: the selected network may isolate Wi-Fi clients (common on campus/office networks).")
        print("If other devices can't connect: use your phone's hotspot or Windows Mobile Hotspot (192.168.137.1), then run scripts/open-firewall.ps1 as Administrator.")
    print("  Docs: http://localhost:8000/docs")
    if not addresses: print("No candidate LAN IPv4 address found; check network adapter and firewall.")
