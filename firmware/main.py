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

# ============================================================================
# GLOBAL STATE
# ============================================================================
class RobotState:
    def __init__(self):
        self.last_command_time = time.time()
        self.connected = False
        self.client_id = ubinascii.hexlify(unique_id()).decode()

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
    print("[WARN] MPU6050 not found")

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

def mqtt_callback(topic, msg):
    try:
        t = topic.decode()
        m = msg.decode()
        print(f"[MQTT] Msg: {t} -> {m}")
        
        if t == TOPIC_CONTROL:
            state.last_command_time = time.time()
            # Command format: "move:FORWARD" or just "FORWARD"? 
            # GCS sends "move:FORWARD" typically via HTTP params?
            # Let's standardize on JSON or simple string.
            # GCS v2 `mqtt.publish_command` will send JSON: {"command": "FORWARD", "val": 0}
            try:
                data = ujson.loads(m)
                cmd = data.get("command", "STOP")
                # val = data.get("val", 0) # e.g. speed
                motors.move(cmd)
            except:
                # Fallback purely text
                motors.move(m)
                
    except Exception as e:
        print(f"[MQTT] Callback Error: {e}")

async def maintain_mqtt_connection(client):
    while True:
        try:
            if not state.connected:
                print(f"[MQTT] Connecting to {MQTT_BROKER}...")
                client.set_callback(mqtt_callback)
                client.connect()
                client.subscribe(TOPIC_CONTROL)
                state.connected = True
                print("[MQTT] Connected")
                # Indicate connection
                client.publish(TOPIC_TELEMETRY, ujson.dumps({"status": "ONLINE", "ip": network.WLAN(network.STA_IF).ifconfig()[0]}))
            
            # Non-blocking check for messages
            client.check_msg()
            
        except Exception as e:
            print(f"[MQTT] Error: {e}")
            state.connected = False
            motors.stop()
            await asyncio.sleep(5)
            
        await asyncio.sleep(0.01) # Yield

# ============================================================================
# SENSOR TASKS
# ============================================================================
async def task_sensors_fast(client):
    """ Read Power, IMU, MQ2 (Alerts) """
    while True:
        if state.connected:
            try:
                # 1. MQ-2 (Gas)
                ppm, voltage = mq2.read_ppm()
                # Publish Data
                client.publish(TOPIC_GAS, ujson.dumps({
                    "sensor_data": {
                        "ppm": ppm, 
                        "voltage": voltage,
                        "alert_status": "CRITICAL" if ppm > 1000 else "Normal" 
                    }
                }))
                
                # 2. Power (Simulated Current for now or derived)
                client.publish(TOPIC_POWER, ujson.dumps({
                    "voltage": 12.4, # TODO: Add voltage divider reading if hardware exists
                    "current": 0.5
                }))
                
                # 3. IMU
                if mpu_available:
                    acc = mpu.read_accel_data()
                    gyro = mpu.read_gyro_data()
                    # Mapping to standard GCS format
                    client.publish(TOPIC_IMU, ujson.dumps({
                        "accel_x": acc["x"], "accel_y": acc["y"], "accel_z": acc["z"],
                        "roll": 0, "pitch": 0, "yaw": 0 # TODO: fusion
                    }))
                    
            except Exception as e:
                print(f"[Sensors Fast] Error: {e}")
                
        await asyncio.sleep(0.1) # 10Hz

async def task_sensors_slow(client):
    """ Read Environment, Ultrasonic """
    scd30.start_continuous()
    
    while True:
        if state.connected:
            try:
                # 1. SCD30 (CO2, Temp, Hum)
                if scd30.data_ready():
                    c, t, h = scd30.read_measurement()
                    client.publish(TOPIC_ENV, ujson.dumps({
                        "co2": c, "temperature": t, "humidity": h
                    }))
                
                # 2. Ultrasonic (Simulated Radar Array for GCS)
                dist = ultrasonic.get_distance_cm()
                if dist > 0:
                    # GCS expects "distances" array of 72 points for radar view
                    # We only have one sensor. We'll simulate a front cone.
                    # Index 36 is front? 
                    # Let's just send single value or standard array?
                    # GCS `on_mqtt_message` checks `payload["distances"]`.
                    # Let's create a dummy array where front is `dist`.
                    d_array = [5.0] * 72 # Max range 5m
                    # Front sector (indices 30-42)
                    for i in range(30, 42):
                        d_array[i] = dist / 100.0 # Convert cm to m
                    
                    client.publish(TOPIC_RADAR, ujson.dumps({
                        "distances": d_array
                    }))
                    
            except Exception as e:
                print(f"[Sensors Slow] Error: {e}")
                
        await asyncio.sleep(0.5) # 2Hz

async def task_safety_watchdog():
    while True:
        if time.time() - state.last_command_time > 2.0:
            # No commands for 2 seconds -> STOP
            # Only print once to avoid spam
            # motors.stop() 
            pass # re-enable if needed, for now just passive
        await asyncio.sleep(1)

# ============================================================================
# MAIN
# ============================================================================
async def main_loop():
    if not connect_wifi():
        print("[FATAL] No WiFi")
        return

    # Init specific sensors
    mq2.calibrate()

    client = MQTTClient(state.client_id, MQTT_BROKER, port=MQTT_PORT, 
                        user=MQTT_USER, password=MQTT_PASSWORD, keepalive=MQTT_KEEPALIVE)

    # Schedule tasks
    asyncio.create_task(maintain_mqtt_connection(client))
    asyncio.create_task(task_sensors_fast(client))
    asyncio.create_task(task_sensors_slow(client))
    asyncio.create_task(task_safety_watchdog())
    
    print("[SYSTEM] Running...")
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        print("Stopped by User")
    except Exception as e:
        print(f"Main Error: {e}")
        motors.stop()
