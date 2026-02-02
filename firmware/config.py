"""
Configuración para ESP32 - HERMES GCS v2
Mantiene la compatibilidad estricta con el hardware original (Legacy Pinout).
"""

# ========================
# INFO DEL DISPOSITIVO
# ========================
DEVICE_NAME = "HERMES_ROBOT_01"
LOCATION = "Lab-Principal"

# ========================
# WIFI & MQTT
# ========================
WIFI_SSID = "ROBMA"
WIFI_PASSWORD = "ROBMA2023"
WIFI_TIMEOUT = 30 

MQTT_BROKER = "192.168.2.103"
MQTT_PORT = 1883
MQTT_USER = None
MQTT_PASSWORD = None
MQTT_KEEPALIVE = 60

# Topics Hermes GCS v2
TOPIC_CONTROL = "hermes/control"        # Comandos (move:FORWARD, etc)
TOPIC_TELEMETRY = "hermes/status"       # Estado general
TOPIC_ENV = "hermes/sensors/environment" # CO2, Temp, Hum
TOPIC_POWER = "hermes/sensors/power"     # Voltaje, Corriente
TOPIC_IMU = "hermes/sensors/imu"         # MPU6050
TOPIC_RADAR = "hermes/radar"             # Ultrasonico (Array simulado)
TOPIC_GAS = "iot/sensor/mq2/data"        # Legacy topic support for gas
TOPIC_GAS_ALERT = "iot/sensor/mq2/alert" 

# ========================
# HARDWARE / PINS (LEGACY)
# ========================

# I2C Bus (SCD30, MPU6050, ADS1115, PCF8574, Motores)
PIN_I2C_SDA = 21
PIN_I2C_SCL = 22
I2C_FREQ = 100000

# Direcciones I2C Identificadas
ADDR_PCF_MOTORS_1 = 0x20 # Motores 1 y 2
ADDR_PCF_MOTORS_2 = 0x21 # Motores 3 y 4
ADDR_ULTRASONIC = 0x23   
ADDR_ADS1115 = 0x48      # MQ-2 ADC
ADDR_SCD30 = 0x61        # CO2
ADDR_MPU6050 = 0x68      # IMU

# Motores (PWM Directo + PCF8574 para dirección)
# PWM Pins
PIN_MOTOR_1 = 16
PIN_MOTOR_2 = 17
PIN_MOTOR_3 = 18
PIN_MOTOR_4 = 19
PWM_FREQ = 1000

# Mapa de bits PCF8574 para dirección
# (Copiado exactamente del archivo 'config (2).py')
PCF_CONTROL_BITS = {
    "m1_horario": 0b11110110,
    "m1_antihorario": 0b11111010,
    "m2_horario": 0b11100111,
    "m2_antihorario": 0b11011011,
    "m3_horario": 0b11111010,
    "m3_antihorario": 0b11110110, 
    "m4_horario": 0b11011011,
    "m4_antihorario": 0b11100111,
}

# Configuración MQ-2 (Gas)
MQ2_CHANNEL = 0   # Canal 0 del ADS1115
MQ2_RL_VALUE = 10.0
MQ2_RO_CLEAN_AIR_FACTOR = 9.83

# Configuración Ultrasonico (PCF8574 based)
ULTRASONIC_TRIG_BIT = 2
ULTRASONIC_ECHO_BIT = 1
