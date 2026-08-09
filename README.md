Webkit with RCE only (NO KERNEL YET), this should work on 9.00-13.60.

   1) launch exploit by using your server.
   2) run on cmd/powershell ws_sever.py with python.
   3) send file with : send payloads/xxx.js.

PS : send_payload.py is optional for testing, if you don't need it, don't use it.

If you want to use your IP adress you need to change on exploit.js file : const RCE_PC_IP = [192, 168, 1, 180] by const RCE_PC_IP = [YOUR IP ADRESS]

AND also for RCE, change on remote.js file :

const PC_IP = (typeof RCE_PC_IP !== "undefined") ? RCE_PC_IP.join(".") : "192.168.1.180"; by const PC_IP = (typeof RCE_PC_IP !== "undefined") ? RCE_PC_IP.join(".") : "YOUR IP ADRESS​";



THX TO JORDY FOR THE EXPLOIT !!
