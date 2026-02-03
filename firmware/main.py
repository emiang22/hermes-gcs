"""
ESP32 Robot Controller + Multi-Sensor System + MQ-2 - MicroPython
** VERSION ASINCRONA OPTIMIZADA (V2.1) **
Sistema Unificado: Robot + PID + MPU6050 + Ultrasónico + SCD30 + MQ-2 (Gas/Humo)
"""

import network
import time
import json
import gc
import struct
import math
import uasyncio as asyncio
import ubinascii
from machine import I2C, Pin, PWM, reset, unique_id
from umqtt.simple import MQTTClient

# Importar configuración
try:
    from config import *
    print("Config cargada correctamente")
except ImportError as e:
    print(f" Error importando config.py: {e}")
    SAFE_START = True

# Importar librería MPU6050
try:
    from MPU6050 import MPU6050
    MPU6050_AVAILABLE = True
except ImportError:
    MPU6050_AVAILABLE = False
    print(" MPU6050 no disponible")

# Importar PID
try:
    from pid import PID
    PID_AVAILABLE = True
except ImportError:
    PID_AVAILABLE = False
    print(" PID lib no disponible (Usando dummy)")
    class PID:
        def __init__(self, kp, ki, kd, setpoint=0): pass
        def compute(self, val): return 0
        def reset(self): pass

# ========================
# CLASE ADS1115 (Para MQ-2)
# ========================
class ADS1115:
    def __init__(self, i2c, addr=None, gain=None):
        self.i2c = i2c
        self.addr = addr or ADS1115_ADDR
        self.gain = gain or MQ2_GAIN
    
    def read_adc(self, channel):
        if channel > 3: return 0
        try:
            config = (0x8000 | 0x0100 | self.gain | 0x0080 | 
                     ADS1115_MUX_CONFIG[channel] | 0x0003)
            self.i2c.writeto(self.addr, bytes([ADS1115_REG_CONFIG, config >> 8, config & 0xFF]))
            time.sleep_ms(10) # Blocking sleep is minimal info for ADC
            self.i2c.writeto(self.addr, bytes([ADS1115_REG_CONVERSION]))
            data = self.i2c.readfrom(self.addr, 2)
            result = (data[0] << 8) | data[1]
            return result if result < 32768 else result - 65536
        except:
            return 0

# ========================
# CLASE SENSOR MQ-2
# ========================
class MQ2Sensor:
    def __init__(self, i2c_bus):
        self.i2c = i2c_bus
        self.ads = None
        self.available = False
        self.alert_status = "normal"
        self.read_errors = 0
        self.r0_calibrated = False
        self.r0_value = 1.0 
        
        try:
            if ADS1115_ADDR in self.i2c.scan():
                self.ads = ADS1115(self.i2c)
                self.available = True
                self._calibrate_r0()
                print(" [HARDWARE] MQ-2 OK")
            else:
                print(" [HARDWARE] MQ-2 no encontrado")
        except:
            self.available = False
    
    def _calibrate_r0(self):
        try:
            samples = []
            for i in range(10):
                adc_value = self.ads.read_adc(MQ2_CHANNEL)
                if adc_value > 0:
                    voltage = (adc_value * SAFETY_CONFIG["voltage_reference"]) / 32767.0
                    rs = (MQ2_VOLTAGE_SUPPLY - voltage) / voltage
                    samples.append(rs)
                time.sleep_ms(20)
            if samples:
                avg_rs = sum(samples) / len(samples)
                self.r0_value = avg_rs / MQ2_RO_CLEAN_AIR
                self.r0_calibrated = True
        except: pass
    
    def _calculate_ppm(self, voltage):
        try:
            rs = (MQ2_VOLTAGE_SUPPLY - voltage) / voltage
            rs_r0_ratio = rs / self.r0_value
            if rs_r0_ratio <= 0: return 0.0
            log_rs_r0 = math.log10(rs_r0_ratio)
            log_ppm = (log_rs_r0 - MQ2_SMOKE_B) / MQ2_SMOKE_M
            return max(0.0, math.pow(10, log_ppm))
        except: return 0.0
    
    def read_sensor(self):
        if not self.available or not self.r0_calibrated: return None
        try:
            adc_value = self.ads.read_adc(MQ2_CHANNEL)
            voltage = (adc_value * SAFETY_CONFIG["voltage_reference"]) / 32767.0
            ppm = self._calculate_ppm(voltage)
            
            if ppm >= SMOKE_THRESHOLDS["critico"]: self.alert_status = "critico"
            elif ppm >= SMOKE_THRESHOLDS["peligro"]: self.alert_status = "peligro"
            elif ppm >= SMOKE_THRESHOLDS["advertencia"]: self.alert_status = "advertencia"
            else: self.alert_status = "normal"
            
            return {"adc_value": adc_value, "voltage": round(voltage, 3), "ppm": round(ppm, 2), "alert_status": self.alert_status}
        except:
            return None

# ========================
# CLASE SCD30
# ========================
class SCD30:
    CMD_CONTINUOUS_MEASUREMENT = 0x0010
    CMD_SET_MEASUREMENT_INTERVAL = 0x4600
    CMD_GET_DATA_READY = 0x0202
    CMD_READ_MEASUREMENT = 0x0300
    
    def __init__(self, i2c, address=0x61):
        self.i2c = i2c
        self.address = address
        self.CO2, self.temp, self.hum = 0, 0, 0
        
    def begin(self):
        try:
            self.i2c.writeto(self.address, b'\x00\x10\x00\x00\x81')
            time.sleep_ms(40)
            return True
        except: return False
    
    def data_ready(self):
        try:
            self.i2c.writeto(self.address, b'\x02\x02')
            data = self.i2c.readfrom(self.address, 3)
            return (data[0] << 8 | data[1]) == 1
        except: return False
    
    def read(self):
        try:
            self.i2c.writeto(self.address, b'\x03\x00')
            time.sleep_ms(5)
            data = self.i2c.readfrom(self.address, 18)
            # Simple unpack check CRC skipped for speed in async
            self.CO2 = struct.unpack('>f', bytes([data[0], data[1], data[3], data[4]]))[0]
            self.temp = struct.unpack('>f', bytes([data[6], data[7], data[9], data[10]]))[0]
            self.hum = struct.unpack('>f', bytes([data[12], data[13], data[15], data[16]]))[0]
            return True
        except: return False

# ========================
# CLASE SENSOR ULTRASÓNICO (Async Optimized)
# ========================
class UltrasonicSensor:
    def __init__(self, i2c_bus):
        self.i2c = i2c_bus
        self.addr = ULTRASONIC_ADDR
        self.trig = TRIG_BIT
        self.echo = ECHO_BIT
        self.pcf_state = 0xFF
        
    def _write(self, val):
        try:
            self.i2c.writeto(self.addr, bytes([val]))
            self.pcf_state = val
        except: pass
    
    def _read(self):
        try:
            return self.i2c.readfrom(self.addr, 1)[0]
        except: return 0xFF
    
    async def measure_distance_async(self):
        try:
            # Trigger Pulse
            self.pcf_state &= ~(1 << self.trig)
            self._write(self.pcf_state)
            await asyncio.sleep_ms(1)
            
            self.pcf_state |= (1 << self.trig)
            self._write(self.pcf_state)
            await asyncio.sleep_ms(1)
            
            self.pcf_state &= ~(1 << self.trig)
            self._write(self.pcf_state)
            
            # Wait for Echo (Async with timeout)
            t0 = time.ticks_us()
            while not (self._read() & (1 << self.echo)):
                if time.ticks_diff(time.ticks_us(), t0) > 30000: return None
                await asyncio.sleep_ms(1) # Yield
                
            t1 = time.ticks_us()
            while (self._read() & (1 << self.echo)):
                if time.ticks_diff(time.ticks_us(), t1) > 30000: return None
                await asyncio.sleep_ms(1) # Yield
                
            duration = time.ticks_diff(time.ticks_us(), t1)
            return (duration * 0.0343) / 2
        except: return None

# ========================
# CLASE MOTOR CONTROLLER + PID
# ========================
class MotorController:
    def __init__(self, i2c_bus):
        self.i2c = i2c_bus
        self.current_movement = "stop"
        self.emergency_stop_active = False
        
        # Initialize PWM
        self.motors = {}
        for num, pin in MOTOR_PINS.items():
            self.motors[num] = PWM(Pin(pin), freq=PWM_FREQUENCY)
            self.motors[num].duty(0)
            
        print(" [HARDWARE] Motores OK")

    def _update_pcf(self, motor_cfgs):
        pcf_maps = {0x20: 0xFF, 0x24: 0xFF}
        
        for m_num, cfg in motor_cfgs.items():
             # Get PCF address
            addr = PCF8574_ADDRESSES[1 if m_num <= 2 else 2]
            
            # Get Mask
            key = f"m{m_num}_{cfg['direction']}"
            mask = PCF_CONTROL_BITS.get(key, 0xFF)
            
            pcf_maps[addr] &= mask
            
        try:
            for addr, val in pcf_maps.items():
                self.i2c.writeto(addr, bytes([val]))
        except: pass

    def set_speeds(self, m1, m2, m3, m4, direction):
        if self.emergency_stop_active:
            m1=m2=m3=m4=0
            
        # Clip PWM
        m1 = max(0, min(1023, int(m1)))
        m2 = max(0, min(1023, int(m2)))
        m3 = max(0, min(1023, int(m3)))
        m4 = max(0, min(1023, int(m4)))
        
        self.motors[1].duty(m1)
        self.motors[2].duty(m2)
        self.motors[3].duty(m3)
        self.motors[4].duty(m4)
        
        # Resolve Direction for PCF chips
        # Assumes standard movement pattern based on requested direction
        # If STOP, direction doesn't matter much (PWM is 0)
        
        if direction not in ROBOT_MOVEMENTS and direction != "differential":
             pass # Manual control?
        
        if direction in ROBOT_MOVEMENTS:
            mov = ROBOT_MOVEMENTS[direction]
            # Just extract direction strings to send to PCF
            cfgs = {}
            for i in range(1, 5):
                cfgs[i] = {"direction": mov[f"M{i}"]["direction"]}
            self._update_pcf(cfgs)

    def stop(self):
        for i in range(1,5): self.motors[i].duty(0)
        self.current_movement = "stop"

# ========================
# SISTEMA PRINCIPAL (ASYNC)
# ========================
class HermesSystem:
    def __init__(self):
        print("="*40)
        print(f" HERMES {DEVICE_NAME} INIT")
        print("="*40)
        
        # I2C SETUP
        self.i2c = I2C(0, scl=Pin(I2C_SCL_PIN), sda=Pin(I2C_SDA_PIN), freq=I2C_FREQUENCY)
        print(f" [I2C] Scan: {[hex(x) for x in self.i2c.scan()]}")
        
        # DRIVERS
        self.wifi = None
        self.mqtt = None
        self.motors = MotorController(self.i2c)
        self.mq2 = MQ2Sensor(self.i2c)
        self.scd30 = SCD30(self.i2c, SCD30_ADDRESS)
        self.ultrasonic = UltrasonicSensor(self.i2c)
        
        # MPU6050 & PID
        self.mpu = None
        self.pid = None
        self.gyro_bias = 0.0
        self.yaw = 0.0
        self.target_yaw = 0.0
        
        if MPU6050_AVAILABLE:
            try:
                self.mpu = MPU6050(self.i2c)
                print(" [HARDWARE] MPU6050 OK")
                self.pid = PID(kp=2.0, ki=0.5, kd=0.1) # Tuning default
            except: print(" [ERROR] MPU6050 init fail")
            
        if self.scd30.begin(): print(" [HARDWARE] SCD30 OK")

        # STATE
        self.connected = False
        self.active_command = "stop"
        self.last_cmd_time = time.time()
        
    async def task_wifi_mqtt(self):
        """Mantiene conexión WiFi y MQTT robusta"""
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        
        client_id = ubinascii.hexlify(unique_id()).decode()
        self.mqtt = MQTTClient(client_id, MQTT_BROKER, port=MQTT_PORT, 
                               user=MQTT_USER, password=MQTT_PASSWORD, keepalive=60)
        
        def mqtt_cb(topic, msg):
            asyncio.create_task(self.handle_command(msg))

        self.mqtt.set_callback(mqtt_cb)

        while True:
            try:
                if not wlan.isconnected():
                    print(" [WIFI] Connecting...")
                    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
                    await asyncio.sleep(5)
                    continue
                
                if not self.connected:
                    try:
                        print(" [MQTT] Connecting...")
                        self.mqtt.connect()
                        self.mqtt.subscribe(TOPIC_COMMAND)
                        self.connected = True
                        print(" [MQTT] Connected!")
                        self.mqtt.publish(TOPIC_STATUS, json.dumps({"status": "online", "msg": "Reconnected"}))
                    except:
                        print(" [MQTT] Fail")
                        await asyncio.sleep(2)
                
                self.mqtt.check_msg()
                
            except:
                self.connected = False
            
            await asyncio.sleep_ms(50) # Yield często

    async def handle_command(self, msg):
        try:
            payload = json.loads(msg)
            cmd = payload.get("command", "").lower()
            cmd = COMMAND_MAPPING.get(cmd, cmd)
            
            self.last_cmd_time = time.time()
            
            if cmd == "adelante" and self.active_command != "adelante":
                self.target_yaw = self.yaw # Lock heading
                if self.pid: self.pid.reset()
                
            self.active_command = cmd
            
            if cmd not in ROBOT_MOVEMENTS:
                self.motors.stop()
            
        except: pass

    async def task_navigation(self):
        """Control Loop: PID + Motores (50Hz)"""
        last_ticks = time.ticks_ms()
        
        while True:
            now = time.ticks_ms()
            dt = time.ticks_diff(now, last_ticks) / 1000.0
            last_ticks = now
            
            if self.mpu and dt > 0:
                # INTEGRATE YAW
                g = self.mpu.read_gyro_data()
                gz = g['z'] - self.gyro_bias
                if abs(gz) > 0.5: # Deadband
                    self.yaw += gz * dt
            
            # CONTROL LOGIC
            if self.motors.emergency_stop_active:
                self.motors.stop()
                
            elif self.active_command == "adelante" and self.mpu:
                # PID CORRECTION
                self.pid.setpoint = self.target_yaw
                correction = self.pid.compute(self.yaw)
                
                # Differential Steering
                base = 1023
                # Left (M1,M2) - Right (M3,M4)
                # If drifting Left (Yaw < Target), Error is Pos. Correction Pos.
                # Need to Turn Right: Left Faster, Right Slower
                m_left = base + correction
                m_right = base - correction
                
                self.motors.set_speeds(m_left, m_left, m_right, m_right, "adelante")
                
            elif self.active_command in ROBOT_MOVEMENTS:
                # OPEN LOOP
                mov = ROBOT_MOVEMENTS[self.active_command]
                
                m1 = mov["M1"]["pwm"]
                m2 = mov["M2"]["pwm"]
                m3 = mov["M3"]["pwm"]
                m4 = mov["M4"]["pwm"]
                
                self.motors.set_speeds(m1, m2, m3, m4, self.active_command)
            else:
                self.motors.stop()
                
            await asyncio.sleep_ms(20)

    async def task_sensors_fast(self):
        """IMU + MQ2 (10Hz)"""
        while True:
            if self.connected:
                # MQ2
                data_mq2 = self.mq2.read_sensor()
                if data_mq2:
                    # Check criticality
                    if data_mq2["alert_status"] in ["peligro", "critico"]:
                        if SAFETY_CONFIG["gas_emergency_stop"] and not self.motors.emergency_stop_active:
                             self.motors.emergency_stop_active = True
                             self.active_command = "stop"
                             self.mqtt.publish(TOPIC_MQ2_ALERT, json.dumps({"msg": "PARADA DE EMERGENCIA - GAS DETECTADO"}))
                    else:
                        if self.motors.emergency_stop_active:
                             self.motors.emergency_stop_active = False

                    self.mqtt.publish(TOPIC_MQ2_DATA, json.dumps({"sensor_data": data_mq2}))
                
                # IMU
                if self.mpu:
                    acc = self.mpu.read_accel_data()
                    msg = {
                        "accelerometer": acc,
                        "orientation": {"yaw": self.yaw}
                    }
                    self.mqtt.publish(TOPIC_MPU_DATA, json.dumps(msg))
                    
            await asyncio.sleep_ms(100)

    async def task_sensors_slow(self):
        """SCD30 + Ultrasonic (2Hz)"""
        while True:
            if self.connected:
                # SCD30
                if self.scd30.data_ready():
                    if self.scd30.read():
                         msg = {"co2": self.scd30.CO2, "temperature": self.scd30.temp, "humidity": self.scd30.hum}
                         self.mqtt.publish(TOPIC_SCD30_DATA, json.dumps(msg))
                
                # ULTRASONIC
                dist = await self.ultrasonic.measure_distance_async()
                if dist and dist > 0:
                     # Obstacle avoidance override
                     if dist < SAFETY_CONFIG["obstacle_distance"] and self.active_command == "adelante":
                          self.active_command = "stop"
                     
                     self.mqtt.publish(TOPIC_ULTRASONIC, json.dumps({"distance_cm": dist}))
                     
            await asyncio.sleep_ms(500)

    async def task_watchdog(self):
        """Safety Watchdog"""
        while True:
            if self.active_command != "stop":
                 if time.time() - self.last_cmd_time > 2.0:
                      print(" [WATCHDOG] Safety Stop")
                      self.active_command = "stop"
                      self.motors.stop()
            await asyncio.sleep(1)

    def calibrate_imu(self):
        if not self.mpu: return
        print(" [CALIBRATION] Calibrating Gyro...")
        bias = 0
        for _ in range(50):
            d = self.mpu.read_gyro_data()
            bias += d['z']
            time.sleep_ms(10)
        self.gyro_bias = bias / 50.0
        print(f" [CALIBRATION] Done. Bias: {self.gyro_bias:.3f}")

    async def start(self):
        self.calibrate_imu()
        
        asyncio.create_task(self.task_wifi_mqtt())
        asyncio.create_task(self.task_navigation())
        asyncio.create_task(self.task_sensors_fast())
        asyncio.create_task(self.task_sensors_slow())
        asyncio.create_task(self.task_watchdog())
        
        while True:
            await asyncio.sleep(1)

# BOOTSTRAP
if __name__ == "__main__":
    sys = HermesSystem()
    try:
        asyncio.run(sys.start())
    except:
        reset()
