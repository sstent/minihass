#!/usr/bin/env python3
"""
Lightweight Smart Home Controller - Docker Edition
A simple Flask app to control TP-Link switches and Android TVs
"""

from flask import Flask, render_template, request, jsonify
import asyncio
import json
import socket
import struct
import logging
import consul
from threading import Lock
import time
import os
import sys

from androidtvremote2 import AndroidTVRemote, CannotConnect, ConnectionClosed, InvalidAuth

# Configure logging for container
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-this')

logger = logging.getLogger(__name__)

# Consul configuration
CONSUL_HOST = 'consul.service.dc1.consul'
CONSUL_PORT = 8500
CONSUL_BASE_KEY = 'MiniHass/'

class ConsulConfigManager:
    """Manage configuration using Consul KV store"""
    
    def __init__(self, host=CONSUL_HOST, port=CONSUL_PORT, base_key=CONSUL_BASE_KEY):
        self.client = consul.Consul(host=host, port=port)
        self.base_key = base_key
        
    def get(self, key):
        """Get value from Consul"""
        _, data = self.client.kv.get(f"{self.base_key}{key}")
        return data['Value'].decode() if data else None
        
    def put(self, key, value):
        """Store value in Consul"""
        return self.client.kv.put(f"{self.base_key}{key}", value)
        
    def get_json(self, key):
        """Get JSON value from Consul"""
        value = self.get(key)
        return json.loads(value) if value else None
        
    def put_json(self, key, value):
        """Store JSON value in Consul"""
        return self.put(key, json.dumps(value))

# Initialize Consul config manager
consul_config = ConsulConfigManager()

# Load configuration from Consul
config = consul_config.get_json('config') or {
    'tplink_ip': os.environ.get('TPLINK_IP', '192.168.1.100'),
    'tv_bedroom_ip': '192.168.4.206',
    'tv_dining_ip': '192.168.4.224',
    'tv_living_ip': '192.168.4.169'
}

# Thread lock for state updates
state_lock = Lock()
device_states = {
    'tplink': False,
    'last_update': 0
}

class TPLinkDevice:
    """Control TP-Link Kasa devices using the local protocol"""
    
    @staticmethod
    def encrypt(string):
        key = 171
        result = struct.pack('>I', len(string))
        for char in string:
            a = key ^ ord(char)
            key = a
            result += bytes([a])
        return result

    @staticmethod
    def decrypt(data):
        key = 171
        result = ""
        for byte in data:
            a = key ^ byte
            key = byte
            result += chr(a)
        return result

    @staticmethod
    def send_command(ip, command, port=9999, timeout=5):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((ip, port))
            sock.send(TPLinkDevice.encrypt(json.dumps(command)))
            data = sock.recv(2048)
            sock.close()
            response = TPLinkDevice.decrypt(data[4:])
            return json.loads(response)
        except Exception as e:
            logger.error(f"TP-Link command error for {ip}: {e}")
            return None

    @staticmethod
    def get_info(ip):
        return TPLinkDevice.send_command(ip, {"system": {"get_sysinfo": {}}})

    @staticmethod
    def turn_on(ip):
        return TPLinkDevice.send_command(ip, {"system": {"set_relay_state": {"state": 1}}})

    @staticmethod
    def turn_off(ip):
        return TPLinkDevice.send_command(ip, {"system": {"set_relay_state": {"state": 0}}})


class AndroidTVManager:
    """Manage Android TV and handle pairing"""
    
    def __init__(self, tv_id, ip):
        self.tv_id = tv_id
        self.ip = ip
        self.consul_prefix = f'tv_credentials/{tv_id}/'
        
        self.cert = consul_config.get(f'{self.consul_prefix}cert')
        self.key = consul_config.get(f'{self.consul_prefix}key')
        
        # Temp files for library
        self.cert_file = f'/tmp/{tv_id}_cert.pem'
        self.key_file = f'/tmp/{tv_id}_key.pem'
        
        if self.cert and self.key:
            with open(self.cert_file, 'w') as f: f.write(self.cert)
            with open(self.key_file, 'w') as f: f.write(self.key)
        else:
            with open(self.cert_file, 'w') as f: f.write("")
            with open(self.key_file, 'w') as f: f.write("")
            
        self.client = AndroidTVRemote(
            client_name="MiniHass",
            certfile=self.cert_file,
            keyfile=self.key_file,
            host=self.ip
        )
        
    async def save_certs(self):
        with open(self.cert_file, 'r') as f:
            consul_config.put(f'{self.consul_prefix}cert', f.read())
        with open(self.key_file, 'r') as f:
            consul_config.put(f'{self.consul_prefix}key', f.read())

    async def start_pairing(self):
        await self.client.async_generate_cert_if_missing()
        await self.save_certs()
        await self.client.async_start_pairing()

    async def finish_pairing(self, code):
        await self.client.async_finish_pairing(code)
        
    async def execute_macro(self, macro):
        await self.client.async_connect()
        try:
            if macro == 'audio_only':
                self.client.send_key_command("MUTE")
                await asyncio.sleep(0.1)
                self.client.send_key_command("MUTE")
            elif macro == 'power_on':
                self.client.send_key_command("DPAD_CENTER")
            await asyncio.sleep(0.5) # Flush buffer
        finally:
            self.client.disconnect()


def update_device_state(device, state):
    with state_lock:
        device_states[device] = state
        device_states['last_update'] = time.time()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/health')
def health_check():
    consul_ok = True
    try:
        consul_config.get('healthcheck')
    except Exception as e:
        consul_ok = False
    
    return jsonify({
        'status': 'healthy',
        'timestamp': time.time(),
        'config': config,
        'services': {
            'consul_connected': consul_ok
        }
    })

@app.route('/api/config', methods=['GET', 'POST'])
def handle_config():
    global config
    if request.method == 'POST':
        data = request.get_json()
        config.update(data)
        consul_config.put_json('config', config)
        return jsonify({'status': 'success', 'message': 'Configuration updated and saved to Consul'})
    return jsonify(config)

@app.route('/api/status')
def get_status():
    return jsonify(device_states)

@app.route('/api/tplink/<action>')
def control_tplink(action):
    ip = config.get('tplink_ip')
    if not ip:
        return jsonify({'error': 'TP-Link IP not configured'}), 400
    try:
        if action == 'on':
            result = TPLinkDevice.turn_on(ip)
            if result and 'system' in result:
                update_device_state('tplink', True)
                return jsonify({'status': 'success', 'state': True})
        elif action == 'off':
            result = TPLinkDevice.turn_off(ip)
            if result and 'system' in result:
                update_device_state('tplink', False)
                return jsonify({'status': 'success', 'state': False})
        elif action == 'status':
            result = TPLinkDevice.get_info(ip)
            if result and 'system' in result:
                state = result['system']['get_sysinfo']['relay_state'] == 1
                update_device_state('tplink', state)
                return jsonify({'status': 'success', 'state': state})
        return jsonify({'error': 'Command failed'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tv/<tv_id>/pair/start', methods=['POST'])
def tv_pair_start(tv_id):
    ip = config.get(f'tv_{tv_id}_ip')
    if not ip: return jsonify({'error': 'TV IP not configured'}), 400
    try:
        tv = AndroidTVManager(tv_id, ip)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(tv.start_pairing())
        loop.close()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tv/<tv_id>/pair/finish', methods=['POST'])
def tv_pair_finish(tv_id):
    ip = config.get(f'tv_{tv_id}_ip')
    code = request.get_json().get('code')
    if not ip: return jsonify({'error': 'TV IP not configured'}), 400
    if not code: return jsonify({'error': 'Pairing code required'}), 400
    try:
        tv = AndroidTVManager(tv_id, ip)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(tv.finish_pairing(code))
        loop.close()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tv/<tv_id>/action', methods=['POST'])
def tv_action(tv_id):
    ip = config.get(f'tv_{tv_id}_ip')
    action = request.get_json().get('action')
    if not ip: return jsonify({'error': 'TV IP not configured'}), 400
    try:
        tv = AndroidTVManager(tv_id, ip)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(tv.execute_macro(action))
        loop.close()
        return jsonify({'status': 'success'})
    except InvalidAuth:
        return jsonify({'error': 'needs_pairing'}), 401
    except Exception as e:
        return jsonify({'error': str(e)}), 500


HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Smart Home Controller</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, sans-serif; background: linear-gradient(135deg, #667eea, #764ba2); min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }
        .container { background: rgba(255, 255, 255, 0.95); backdrop-filter: blur(10px); border-radius: 20px; padding: 40px; box-shadow: 0 20px 40px rgba(0,0,0,0.1); max-width: 500px; width: 100%; text-align: center; }
        h1 { margin-bottom: 30px; font-size: 28px; }
        .device { margin-bottom: 20px; padding: 20px; background: #f9f9f9; border-radius: 15px; text-align: left; position: relative;}
        .device-name { font-size: 18px; font-weight: 600; margin-bottom: 10px; }
        .btn { background: #667eea; color: white; border: none; padding: 10px 15px; border-radius: 8px; cursor: pointer; margin-right: 5px; font-weight: 500;}
        .btn:hover { background: #5a6cd6; }
        .btn-audio { background: #4CAF50; }
        .btn-audio:hover { background: #45a049; }
        
        .switch-container { position: absolute; right: 20px; top: 20px; width: 60px; height: 30px; }
        .switch { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background: #ddd; border-radius: 30px; transition: .3s; }
        .switch:before { position: absolute; content: ""; height: 22px; width: 22px; left: 4px; top: 4px; background: white; border-radius: 50%; transition: .3s; }
        .switch-input { opacity: 0; width: 0; height: 0; }
        .switch-input:checked + .switch { background: #4CAF50; }
        .switch-input:checked + .switch:before { transform: translateX(30px); }
        
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); align-items: center; justify-content: center; z-index: 1000;}
        .modal-content { background: white; padding: 30px; border-radius: 15px; width: 300px; text-align: center;}
        .modal input { width: 100%; padding: 10px; margin: 15px 0; border: 1px solid #ddd; border-radius: 8px; font-size: 18px; text-align: center;}
        
        .config-section { margin-top: 30px; padding: 20px; background: #f1f1f1; border-radius: 10px; text-align: left; }
        .input-group { margin-bottom: 10px; }
        .input-group label { display: block; font-size: 14px; margin-bottom: 5px; }
        .input-group input { width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 5px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🏠 Smart Home</h1>
        
        <div class="device">
            <div class="device-name">💡 TP-Link Switch</div>
            <label class="switch-container">
                <input type="checkbox" class="switch-input" id="tplink-switch">
                <span class="switch"></span>
            </label>
        </div>

        <div class="device" id="tv-bedroom">
            <div class="device-name">📺 Bedroom TV</div>
            <button class="btn" onclick="tvAction('bedroom', 'power_on')">Turn ON</button>
            <button class="btn btn-audio" onclick="tvAction('bedroom', 'audio_only')">Audio Only Macro</button>
        </div>
        
        <div class="device" id="tv-dining">
            <div class="device-name">📺 Dining Room TV</div>
            <button class="btn" onclick="tvAction('dining', 'power_on')">Turn ON</button>
            <button class="btn btn-audio" onclick="tvAction('dining', 'audio_only')">Audio Only Macro</button>
        </div>
        
        <div class="device" id="tv-living">
            <div class="device-name">📺 Living Room TV</div>
            <button class="btn" onclick="tvAction('living', 'power_on')">Turn ON</button>
            <button class="btn btn-audio" onclick="tvAction('living', 'audio_only')">Audio Only Macro</button>
        </div>

        <div class="config-section">
            <h3>⚙️ Configuration</h3>
            <div class="input-group"><label>TP-Link IP</label><input type="text" id="tplink-ip"></div>
            <div class="input-group"><label>Bedroom TV IP</label><input type="text" id="tv-bedroom-ip"></div>
            <div class="input-group"><label>Dining Room TV IP</label><input type="text" id="tv-dining-ip"></div>
            <div class="input-group"><label>Living Room TV IP</label><input type="text" id="tv-living-ip"></div>
            <button class="btn" style="width: 100%; margin-top: 10px;" onclick="saveConfig()">Save Settings</button>
        </div>
    </div>

    <div class="modal" id="pair-modal">
        <div class="modal-content">
            <h3>Pair TV</h3>
            <p>Please enter the 6-digit code shown on your TV.</p>
            <input type="text" id="pair-code" placeholder="123456" maxlength="6">
            <button class="btn" id="pair-submit">Pair</button>
            <button class="btn" onclick="document.getElementById('pair-modal').style.display='none'" style="background: #ccc;">Cancel</button>
        </div>
    </div>

    <script>
        let currentPairingTvId = null;

        async function loadConfig() {
            try {
                const res = await fetch('/api/config');
                const conf = await res.json();
                document.getElementById('tplink-ip').value = conf.tplink_ip || '';
                document.getElementById('tv-bedroom-ip').value = conf.tv_bedroom_ip || '';
                document.getElementById('tv-dining-ip').value = conf.tv_dining_ip || '';
                document.getElementById('tv-living-ip').value = conf.tv_living_ip || '';
            } catch (e) { console.error('Failed to load config'); }
        }

        async function saveConfig() {
            const conf = {
                tplink_ip: document.getElementById('tplink-ip').value,
                tv_bedroom_ip: document.getElementById('tv-bedroom-ip').value,
                tv_dining_ip: document.getElementById('tv-dining-ip').value,
                tv_living_ip: document.getElementById('tv-living-ip').value
            };
            try {
                await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(conf)
                });
                console.log('Saved!');
            } catch (e) { console.error('Save failed'); }
        }

        document.getElementById('tplink-switch').addEventListener('change', async function() {
            const action = this.checked ? 'on' : 'off';
            const res = await fetch(`/api/tplink/${action}`);
            if (!res.ok) this.checked = !this.checked;
        });

        async function pollStatus() {
            try {
                const res = await fetch('/api/tplink/status');
                const data = await res.json();
                if (data.status === 'success') {
                    document.getElementById('tplink-switch').checked = data.state;
                }
            } catch (e) {}
        }

        async function tvAction(tvId, action) {
            try {
                const res = await fetch(`/api/tv/${tvId}/action`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: action })
                });
                
                if (res.status === 401) {
                    startPairing(tvId);
                } else if (!res.ok) {
                    console.error('Action failed');
                }
            } catch (e) {
                console.error('Connection error');
            }
        }

        async function startPairing(tvId) {
            currentPairingTvId = tvId;
            try {
                const res = await fetch(`/api/tv/${tvId}/pair/start`, { method: 'POST' });
                if (res.ok) {
                    document.getElementById('pair-code').value = '';
                    document.getElementById('pair-modal').style.display = 'flex';
                } else {
                    console.error('Could not start pairing on TV. Ensure IP is correct.');
                }
            } catch (e) {
                console.error('Network error initiating pairing');
            }
        }

        document.getElementById('pair-submit').addEventListener('click', async () => {
            const code = document.getElementById('pair-code').value;
            if (code.length < 6) return console.warn('Enter full code');
            
            try {
                const res = await fetch(`/api/tv/${currentPairingTvId}/pair/finish`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ code: code })
                });
                if (res.ok) {
                    document.getElementById('pair-modal').style.display = 'none';
                    console.log('Paired successfully!');
                } else {
                    console.error('Pairing failed. Incorrect code?');
                }
            } catch (e) {
                console.error('Pairing error');
            }
        });

        loadConfig();
        setInterval(pollStatus, 30000);
    </script>
</body>
</html>'''

def create_template_file():
    template_dir = 'templates'
    if not os.path.exists(template_dir):
        os.makedirs(template_dir)
    with open(os.path.join(template_dir, 'index.html'), 'w') as f:
        f.write(HTML_TEMPLATE)

if __name__ == '__main__':
    create_template_file()
    debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'
    print("🚀 Starting Flask server...")
    app.run(host='0.0.0.0', port=5000, debug=debug_mode, use_reloader=False)
