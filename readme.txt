* Deployment Check list * Troubleshooting steps *

Deployment Check list:

    1. Set origins = ["http://localhost:8000"] in main.py at line 109.
    2. Set var socket = new WebSocket("ws://localhost:8000/wss/" + user_id); in index.html at line 106.
    3. Set url: "http://localhost:8000/get_instructions", in admin.html at line 71.

    And Comment out all other local variables.

    A. Make sure to add host IP to Database firewall.
    B. Change model to respective instance or client name in greetings.py at line 77.

    Select API call endpoints in tools.py at line 26.

Troubleshooting steps:

    A. Database TCP/IP error
        - Make sure to add host IP to Database firewall.

* Frontend * REACT * 

for node modules - npm install or  npm i 
for dist folder - npm run build
for running react code in local - npm run dev

Required System Dependices for PDFs:
    1. Tesseract --- https://github.com/UB-Mannheim/tesseract/wiki
    