import network
import ujson
import time
import uasyncio as asyncio
from machine import I2C, Pin, unique_id
import ubinascii
from umqtt.simple import MQTTClient

from config import *
from drivers import MotorDriver, MQ2Driver, UltrasonicDriver, SCD30Driver
from MPU6050 import MPU6050
from pid import PID

# ============================================================================
# CONSTANTS
# ============================================================================
PID_KP = 5.0
PID_KI = 0.0
PID_KD = 0.5

# ============================================================================
# GLOBAL STATE
# ============================================================================
class RobotState:
    def __init__(self):
        self.last_command_time = time.time()
        self.connected = False
        self.client_id = ubinascii.hexlify(unique_id()).decode()
        
        # Navigation
        self.active_command = "STOP"
        self.yaw = 0.0
        self.target_yaw = 0.0
        self.gyro_bias = 0.0

state = RobotState()

# ============================================================================
# SETUP HARDWARE
# ============================================================================
print("[BOOT] Initializing Hardware...")
i2c = I2C(0, scl=Pin(PIN_I2C_SCL), sda=Pin(PIN_I2C_SDA), freq=I2C_FREQ)

motors = MotorDriver(i2c)
mq2 = MQ2Driver(i2c)
ultrasonic = UltrasonicDriver(i2c)
scd30 = SCD30Driver(i2c)
try:
    mpu = MPU6050(bus=i2c)
    mpu_available = True
except:
    mpu_available = False
    print("[WARN] MPU6050 not found - PID Disabled")

pid_controller = PID(PID_KP, PID_KI, PID_KD)

# ============================================================================
# HELPERS
# ============================================================================
def calibrate_gyro():
    if not mpu_available: return
    print("[IMU] Calibrating Gyro...")
    sum_z = 0
    samples = 100
    for _ in range(samples):
        # MPU6050 lib returns dict {'x':..., 'y':..., 'z':...}
        g = mpu.read_gyro_data() 
        sum_z += g['z']
        time.sleep_ms(10)
    state.gyro_bias = sum_z / samples
    print(f"[IMU] Setup Complete. Bias Z: {state.gyro_bias:.2f}")

# ============================================================================
# WIFI & MQTT
# ============================================================================
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print(f"[WIFI] Connecting to {WIFI_SSID}...")
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        timeout = 0
        while not wlan.isconnected():
            if timeout > WIFI_TIMEOUT:
                print("[WIFI] Connection Failed")
                return False
            time.sleep(1)
            timeout += 1
    print(f"[WIFI] Connected: {wlan.ifconfig()[0]}")
    return True

def check_wifi():
    """Check WiFi connection and reconnect if needed."""
    wlan = network.WLAN(network.STA_IF)
    if not wlan.isconnected():
        print("[WIFI] Connection lost, reconnecting...")
        return connect_wifi()
    return True

def mqtt_callback(topic, msg):
    try:
        t = topic.decode()
        m = msg.decode()
        
        if t == TOPIC_CONTROL:
            state.last_command_time = time.time()
            cmd = "STOP"
            
            try:
                data = ujson.loads(m)
                cmd = data.get("command", "STOP")
            except:
                cmd = m
                
            # Logic for PID target locking
            if cmd == "FORWARD" and state.active_command != "FORWARD":
                # Lock current heading as target
                state.target_yaw = state.yaw
                pid_controller.reset()
                print(f"[PID] Target Locked: {state.target_yaw:.1f}")
                
            state.active_command = cmd
            motors.move(cmd)
                
    except Exception as e:
        print(f"[MQTT] Callback Error: {e}")

async def maintain_mqtt_connection(client):
    while True:
        try:
            # Check WiFi first
            if not check_wifi():
                state.connected = False
                motors.stop()
                await asyncio.sleep(5)
                continue
                
            if not state.connected:
                print(f"[MQTT] Connecting to {MQTT_BROKER}...")
                client.set_callback(mqtt_callback)
                client.connect()
                client.subscribe(TOPIC_CONTROL)
                state.connected = True
                print("[MQTT] Connected")
                client.publish(TOPIC_TELEMETRY, ujson.dumps({"status": "ONLINE", "ip": network.WLAN(network.STA_IF).ifconfig()[0]}))
            
            client.check_msg()
            
        except Exception as e:
            print(f"[MQTT] Error: {e}")
            state.connected = False
            motors.stop()
            await asyncio.sleep(5)
            
        await asyncio.sleep(0.01)

# ============================================================================
# NAVIGATION & PID TASK
# ============================================================================
async def task_navigation():
    last_time = time.ticks_ms()
    while True:
        now = time.ticks_ms()
        dt = time.ticks_diff(now, last_time) / 1000.0
        last_time = now
        
        if mpu_available and dt > 0:
            # 1. Integrate Gyro for Yaw
            g = mpu.read_gyro_data()
            gz_dps = g['z'] - state.gyro_bias
            # Simple integration approach
            state.yaw += gz_dps * dt
            
            # 2. Run PID if moving straight
            if state.active_command == "FORWARD":
                pid_controller.setpoint = state.target_yaw
                correction = pid_controller.compute(state.yaw)
                
                # Apply differential steering
                # If error is neg (drift left), output is neg.
                # Left Wheel = Base + (-output) = Speed Up
                # Right Wheel = Base + (-output) = Slow Down (Wait, logic check)
                
                # Turn Right Logic (to fix Left Drift): Left Faster, Right Slower.
                # Correct logic:
                # Left = Base - output
                # Right = Base + output
                
                motors.set_speed_differential(-correction, correction)
                
        await asyncio.sleep(0.02) # 50Hz Loop

# ============================================================================
# SENSOR TASKS (Telemetry)
# ============================================================================
async def task_sensors_fast(client):
    """ Read Power, IMU, MQ2 (Alerts) """
    while True:
        if state.connected:
            try:
                ppm, voltage = mq2.read_ppm()
                client.publish(TOPIC_GAS, ujson.dumps({
                    "sensor_data": {
                        "ppm": ppm, "voltage": voltage,
                        "alert_status": "critical" if ppm > 1000 else "normal" 
                    }
                }))
                
                if mpu_available:
                    acc = mpu.read_accel_data()
                    client.publish(TOPIC_IMU, ujson.dumps({
                        "accel_x": acc["x"], "accel_y": acc["y"], "accel_z": acc["z"],
                        "roll": 0, "pitch": 0, "yaw": state.yaw # Published fused yaw
                    }))
                    
            except Exception as e:
                print(f"[Sensors Fast] Error: {e}")
        await asyncio.sleep(0.1)

async def task_sensors_slow(client):
    while True:
        if state.connected:
            try:
                # SCD30
                if scd30.data_ready():
                    c, t, h = scd30.read_measurement()
                    client.publish(TOPIC_ENV, ujson.dumps({"co2": c, "temperature": t, "humidity": h}))
                
                # Simulated Radar
                dist = ultrasonic.get_distance_cm()
                if dist > 0:
                    d_array = [5.0] * 72 
                    for i in range(30, 42): d_array[i] = dist / 100.0
                    client.publish(TOPIC_RADAR, ujson.dumps({"distances": d_array}))
            except Exception as e:
                print(f"[Sensors Slow] Error: {e}")
        await asyncio.sleep(0.5)

async def task_safety_watchdog():
    while True:
        if time.time() - state.last_command_time > 2.0:
            if state.active_command != "STOP":
                print("[WATCHDOG] Auto-stop")
                state.active_command = "STOP"
                motors.stop()
        await asyncio.sleep(1)

# ============================================================================
# MAIN
# ============================================================================
async def main_loop():
    if not connect_wifi(): return
    
    mq2.calibrate()
    calibrate_gyro()
    scd30.start_continuous()

    client = MQTTClient(state.client_id, MQTT_BROKER, port=MQTT_PORT, 
                        user=MQTT_USER, password=MQTT_PASSWORD, keepalive=MQTT_KEEPALIVE)

    asyncio.create_task(maintain_mqtt_connection(client))
    asyncio.create_task(task_navigation()) # PID runs here
    asyncio.create_task(task_sensors_fast(client))
    asyncio.create_task(task_sensors_slow(client))
    asyncio.create_task(task_safety_watchdog())
    
    print("[SYSTEM] Running with PID Enabled...")
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        print("Stopped")
    except Exception as e:
        print(f"Main Error: {e}")
        motors.stop()
