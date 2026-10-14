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
    addresses=candidates(); print("Local: http://localhost:8000")
    for ip in addresses:
        note=" (likely hotspot network)" if ip.startswith(("192.168.137.","172.20.10.","192.168.43.")) else ""
        print(f"Share: http://{ip}:8000{note}")
    print("Docs: http://localhost:8000/docs")
    if not addresses: print("No candidate LAN IPv4 address found; check network adapter and firewall.")
