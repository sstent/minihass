import os

# Update requirements.txt
with open('requirements.txt', 'a') as f:
    f.write('adb-shell[rsa]==0.4.4\n')

# Read app.py
with open('app.py', 'r') as f:
    content = f.read()

# 1. Imports
content = content.replace(
    "from aiowebostv import WebOsClient, endpoints as ep",
    "from aiowebostv import WebOsClient, endpoints as ep\nfrom adb_shell.adb_device import AdbDeviceTcp\nfrom adb_shell.auth.keygen import keygen\nfrom adb_shell.auth.sign_pythonrsa import PythonRSASigner"
)

# 2. Config
old_config = """config = consul_config.get_json('config') or {
    'tplink_ip': os.environ.get('TPLINK_IP', '192.168.1.100'),
    'tv_ip': os.environ.get('TV_IP', '192.168.1.101'),
    'tv_mac': os.environ.get('TV_MAC', 'AA:BB:CC:DD:EE:FF')
}"""
new_config = """config = consul_config.get_json('config') or {
    'tplink_ip': os.environ.get('TPLINK_IP', '192.168.1.100'),
    'tv_ip': os.environ.get('TV_IP', '192.168.1.101'),
    'tv_mac': os.environ.get('TV_MAC', 'AA:BB:CC:DD:EE:FF'),
    'android_tv_1_ip': os.environ.get('ANDROID_TV_1_IP', '192.168.4.169'),
    'android_tv_2_ip': os.environ.get('ANDROID_TV_2_IP', '192.168.4.224')
}"""
content = content.replace(old_config, new_config)

# 3. Device states
old_states = """device_states = {
    'tplink': False,
    'tv': False,
    'last_update': 0
}"""
new_states = """device_states = {
    'tplink': False,
    'tv': False,
    'androidtv_1': False,
    'androidtv_2': False,
    'last_update': 0
}"""
content = content.replace(old_states, new_states)

# 4. AndroidTV class (insert after WebOSTV)
android_tv_class = """

class AndroidTV:
    \"\"\"Control Android TV using adb-shell\"\"\"
    
    def __init__(self, ip):
        self.ip = ip
        self.keys_dir = '/app/config/adb_keys'
        if not os.path.exists(self.keys_dir):
            try:
                os.makedirs(self.keys_dir, exist_ok=True)
            except Exception as e:
                logger.warning(f"Failed to create {self.keys_dir}: {e}. Falling back to adb_keys")
                self.keys_dir = 'adb_keys'
                os.makedirs(self.keys_dir, exist_ok=True)
                
        self.priv_key = os.path.join(self.keys_dir, 'adbkey')
        self.pub_key = self.priv_key + '.pub'
        
        # Generate keys if they don't exist
        if not os.path.exists(self.priv_key):
            keygen(self.priv_key)
            
        with open(self.priv_key, 'r') as f:
            self.priv = f.read()
        with open(self.pub_key, 'r') as f:
            self.pub = f.read()
            
        self.signer = PythonRSASigner(self.pub, self.priv)
        
    def _execute_command(self, cmd):
        device = AdbDeviceTcp(self.ip, 5555, default_transport_timeout_s=5.)
        try:
            device.connect(rsa_keys=[self.signer], auth_timeout_s=5.0)
            result = device.shell(cmd)
            device.close()
            return result
        except Exception as e:
            logger.error(f"Android TV ADB error on {self.ip}: {e}")
            return None

    def turn_screen_off(self):
        \"\"\"Turn off screen by launching a black screen app or using a keyevent sequence.\"\"\"
        # Note for Hisense: Using a generic black screen app intent as the most reliable software method.
        # An alternative is a macro: e.g. device.shell('input keyevent KEYCODE_MENU && sleep 1 && input keyevent KEYCODE_DPAD_DOWN ...')
        logger.debug(f"Turning off screen for {self.ip}")
        # Launching a hypothetical black screen app (com.example.blackscreen)
        res = self._execute_command("am start -n com.example.blackscreen/.MainActivity")
        return res is not None
        
    def turn_screen_on(self):
        \"\"\"Turn on screen by exiting the black screen.\"\"\"
        logger.debug(f"Turning on screen for {self.ip}")
        # Press BACK to exit black screen
        res = self._execute_command("input keyevent 4")
        return res is not None

    def get_power_state(self):
        \"\"\"Get approximate screen state.\"\"\"
        res = self._execute_command("dumpsys power | grep mWakefulness")
        if res:
            if "Asleep" in res:
                return False
            else:
                active_app = self._execute_command("dumpsys activity activities | grep mResumedActivity")
                if active_app and "com.example.blackscreen" in active_app:
                    return False
                return True
        return None

def update_device_state"""
content = content.replace("def update_device_state", android_tv_class)

# 5. API Route for Android TV
android_tv_route = """
@app.route('/api/androidtv/<device_id>/<action>')
def control_androidtv(device_id, action):
    \"\"\"Control Android TV\"\"\"
    if device_id not in ['1', '2']:
        return jsonify({'error': 'Invalid device ID'}), 400
        
    ip = config.get(f'android_tv_{device_id}_ip')
    if not ip:
        return jsonify({'error': 'Android TV IP not configured'}), 400
        
    state_key = f'androidtv_{device_id}'
    
    try:
        tv = AndroidTV(ip)
        
        if action == 'screen_on':
            if tv.turn_screen_on():
                update_device_state(state_key, True)
                return jsonify({'status': 'success', 'state': True})
            return jsonify({'error': 'Failed to turn screen on'}), 500
            
        elif action == 'screen_off':
            if tv.turn_screen_off():
                update_device_state(state_key, False)
                return jsonify({'status': 'success', 'state': False})
            return jsonify({'error': 'Failed to turn screen off'}), 500
            
        elif action == 'status':
            state = tv.get_power_state()
            if state is not None:
                update_device_state(state_key, state)
                return jsonify({'status': 'success', 'state': state})
            return jsonify({'error': 'Failed to get status'}), 500
            
        return jsonify({'error': 'Invalid action'}), 400
        
    except Exception as e:
        logger.error(f"Android TV {device_id} control error: {e}")
        return jsonify({'error': str(e)}), 500

# HTML template"""
content = content.replace("# HTML template", android_tv_route)

# 6. HTML Updates
# Inject UI blocks
html_webos_block = """        <div class="device">
            <div class="device-name">
                <span>📺</span>
                LG WebOS TV Screen
            </div>
            <label class="switch-container">
                <input type="checkbox" class="switch-input" id="tv-switch">
                <span class="switch"></span>
            </label>
            <div class="status off" id="tv-status">OFF</div>
        </div>"""
        
html_android_block = """
        <div class="device">
            <div class="device-name">
                <span>📺</span>
                Android TV 1 (Hisense)
            </div>
            <label class="switch-container">
                <input type="checkbox" class="switch-input" id="androidtv_1-switch">
                <span class="switch"></span>
            </label>
            <div class="status off" id="androidtv_1-status">OFF</div>
        </div>

        <div class="device">
            <div class="device-name">
                <span>📺</span>
                Android TV 2 (Hisense)
            </div>
            <label class="switch-container">
                <input type="checkbox" class="switch-input" id="androidtv_2-switch">
                <span class="switch"></span>
            </label>
            <div class="status off" id="androidtv_2-status">OFF</div>
        </div>"""
content = content.replace(html_webos_block, html_webos_block + html_android_block)

# Inject Config Inputs
html_config_webos = """            <div class="input-group">
                <label>WebOS TV IP</label>
                <input type="text" id="tv-ip" placeholder="192.168.1.101">
            </div>"""
html_config_android = """
            <div class="input-group">
                <label>Android TV 1 IP</label>
                <input type="text" id="android_tv_1_ip" placeholder="192.168.4.169">
            </div>
            
            <div class="input-group">
                <label>Android TV 2 IP</label>
                <input type="text" id="android_tv_2_ip" placeholder="192.168.4.224">
            </div>"""
content = content.replace(html_config_webos, html_config_webos + html_config_android)

# Inject JS loadConfig
js_load_webos = "document.getElementById('tv-ip').value = config.tv_ip || '';"
js_load_android = """                document.getElementById('android_tv_1_ip').value = config.android_tv_1_ip || '';
                document.getElementById('android_tv_2_ip').value = config.android_tv_2_ip || '';"""
content = content.replace(js_load_webos, js_load_webos + "\n" + js_load_android)

# Inject JS saveConfig
js_save_webos = "tv_ip: document.getElementById('tv-ip').value"
js_save_android = """,
                android_tv_1_ip: document.getElementById('android_tv_1_ip').value,
                android_tv_2_ip: document.getElementById('android_tv_2_ip').value"""
content = content.replace(js_save_webos, js_save_webos + js_save_android)

# Inject JS Event Listeners
js_event_tv = """        document.getElementById('tv-switch').addEventListener('change', async function() {
            const action = this.checked ? 'screen_on' : 'screen_off';
            const success = await controlDevice('tv', action);
            if (!success) {
                this.checked = !this.checked;
            }
        });"""
js_event_android = """
        document.getElementById('androidtv_1-switch').addEventListener('change', async function() {
            const action = this.checked ? 'screen_on' : 'screen_off';
            const success = await controlDevice('androidtv/1', action);
            if (success) {
                updateStatus('androidtv_1', this.checked);
            } else {
                this.checked = !this.checked;
            }
        });

        document.getElementById('androidtv_2-switch').addEventListener('change', async function() {
            const action = this.checked ? 'screen_on' : 'screen_off';
            const success = await controlDevice('androidtv/2', action);
            if (success) {
                updateStatus('androidtv_2', this.checked);
            } else {
                this.checked = !this.checked;
            }
        });"""
content = content.replace(js_event_tv, js_event_tv + js_event_android)

# Inject setInterval polling
js_interval_tv = "await controlDevice('tv', 'status');"
js_interval_android = """                await controlDevice('androidtv/1', 'status');
                await controlDevice('androidtv/2', 'status');"""
content = content.replace(js_interval_tv, js_interval_tv + "\n" + js_interval_android)

# Update controlDevice signature to handle androidtv/1 format updating correct UI element
js_control_device = """                    updateStatus(device, result.state);"""
js_control_device_new = """                    const ui_device = device.replace('/', '_');
                    updateStatus(ui_device, result.state);"""
content = content.replace(js_control_device, js_control_device_new)

with open('app.py', 'w') as f:
    f.write(content)

print("Modification complete.")
