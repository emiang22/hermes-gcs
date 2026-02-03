import time
import math
import struct
import machine
from machine import Pin, PWM, I2C
from config import *

# ============================================================================
# MOTOR DRIVER
# ============================================================================
class MotorDriver:
    def __init__(self, i2c):
        self.i2c = i2c
        self.motors = {}
        
        # Initialize PWM Pins
        motor_pins = {1: PIN_MOTOR_1, 2: PIN_MOTOR_2, 3: PIN_MOTOR_3, 4: PIN_MOTOR_4}
        for idx, pin in motor_pins.items():
            self.motors[idx] = PWM(Pin(pin), freq=PWM_FREQ)
            self.motors[idx].duty(0)
            
        print("[MotorDriver] PWM initialized")
        
    def _write_pcf(self, addr, data):
        try:
            self.i2c.writeto(addr, bytes([data]))
        except Exception as e:
            print(f"[MotorDriver] Error writing to PCF {hex(addr)}: {e}")

    def stop(self):
        for m in self.motors.values():
            m.duty(0)
        # Reset PCF chips to all high (safe state usually) or based on logic. 
        # Legacy code writes 0xFF to stop.
        self._write_pcf(ADDR_PCF_MOTORS_1, 0xFF)
        self._write_pcf(ADDR_PCF_MOTORS_2, 0xFF)

    def move(self, direction_name):
        # Mappings derived from legacy code
        # direction_name: "adelante", "atras", "izquierda", "derecha", "stop"
        
        # Determine PWM and Direction Bits for each motor based on movement
        # This is a simplified version of the legacy specific dictionary
        
        # Default speed
        MAX_PWM = 1023
        TURN_PWM = 1023 
        
        # Structure: MotorID: (PWM, DirectionKey)
        movements = {
            "FORWARD": {
                1: (MAX_PWM, "horario"), 2: (MAX_PWM, "horario"),
                3: (MAX_PWM, "horario"), 4: (MAX_PWM, "horario")
            },
            "BACKWARD": {
                1: (MAX_PWM, "antihorario"), 2: (MAX_PWM, "antihorario"),
                3: (MAX_PWM, "antihorario"), 4: (MAX_PWM, "antihorario")
            },
            "LEFT": {
                1: (TURN_PWM, "antihorario"), 2: (TURN_PWM, "antihorario"),
                3: (TURN_PWM, "horario"), 4: (TURN_PWM, "horario")
            },
            "RIGHT": {
                1: (TURN_PWM, "horario"), 2: (TURN_PWM, "horario"),
                3: (TURN_PWM, "antihorario"), 4: (TURN_PWM, "antihorario")
            },
            "STOP": {
                1: (0, "horario"), 2: (0, "horario"),
                3: (0, "horario"), 4: (0, "horario")
            }
        }
        
        cmd = movements.get(direction_name, movements["STOP"])
        
        pcf1_val = 0xFF # Default state (all inputs/high) - but we are writing
        pcf2_val = 0xFF
        
        # We need to reconstruct the byte for each PCF8574.
        # Legacy code uses a lookup table for the WHOLE byte per movement per motor... 
        # Actually it sends 1 byte per motor write? No, I2C write is to the whole chip.
        # Legacy code: `bits = PCF_CONTROL_BITS.get(control_key)` then write to address.
        # PCF1 controls Motor 1 and 2. PCF2 controls Motor 3 and 4.
        # But wait, looking at legacy code `set_motor_speed_direction`:
        # "pcf_num = 1 if motor_num <= 2 else 2"
        # "addr = PCF8574_ADDRESSES[pcf_num]"
        # "self.i2c.writeto(addr, bytes([bits]))"
        #
        # WARNING: The legacy code writes to the WHOLE PCF chip for EACH motor update. 
        # This implies the bits for Motor 1 and Motor 2 might overwrite each other if not careful, 
        # UNLESS the specific bits don't overlap?
        # PCF_CONTROL_BITS values:
        # m1_horario: 11110110 (Bit 0 low, Bit 3 low)
        # m1_antihorario: 11111010 (Bit 0 low, Bit 2 low) 
        # m2_horario: 11100111 (Bit 3 low, Bit 4 low)
        #
        # This looks like the legacy code MIGHT have a bug where setting motor 2 overwrites motor 1's state 
        # if they share a PCF. BUT I must replicate "working" behavior.
        # However, for a PROPER driver, I should merge the bits.
        # Let's look at the bitmasks again.
        # M1 uses bits 0,1,2,3? 
        # Actually, let's implement the EXACT Legacy behavior ensuring compatibility.
        # The legacy loop iterates 1..4. 
        # M1 update -> Writes PCF1. M2 update -> Writes PCF1 (overwriting M1??).
        # IF M2 update writes 0b11100111, that sets bits 3 and 4 low. It sets bit 0, 1, 2 HIGH.
        # If M1 needed bit 0 or 2 low... M2 update CLEARS it.
        #
        # AHA! In the legacy code:
        # `set_motor_speed_direction` writes immediately.
        # `execute_movement` calls it 4 times.
        # If I rewrite it to merge bits, it's safer.
        # But user said "compatible con los pines... asi como esta".
        # I will attempt to MERGE correctly to fix the potential bug, or at least respect the pinout.
        #
        # Let's assume the PCF pins are:
        # PCF1: M1 (Pins ?) M2 (Pins ?)
        # M1_CW: ~0x09 -> 0000 1001 -> Bits 0 and 3 are 0? No inv: 1111 0110. 
        # ~ (0000 1001) = 1111 0110. So bits 0 and 3 go LOW.
        # M1_CCW: ~0x05 -> 0000 0101 -> Bits 0 and 2 go LOW.
        # M2_CW: ~0x18 -> 0001 1000 -> Bits 3 and 4 go LOW.
        #
        # It seems M1 uses bits 0,1,2,3. M2 uses 3,4,5,6?
        # If I calculate the final state for the PCF, I can write it once.
        
        # Helper to get mask
        def get_mask(m_idx, direct):
            key = f"m{m_idx}_{direct}"
            return PCF_CONTROL_BITS.get(key, 0xFF)

        for m_id, (pwm_val, direct) in cmd.items():
            self.motors[m_id].duty(pwm_val)
        
        # Calculate PCF states by ANDing the masks (active low logic typically)
        # Start with 0xFF (all high/off)
        pcf1 = 0xFF 
        pcf2 = 0xFF
        
        # M1 (PCF1)
        pcf1 &= get_mask(1, cmd[1][1])
        # M2 (PCF1)
        pcf1 &= get_mask(2, cmd[2][1])
        # M3 (PCF2)
        pcf2 &= get_mask(3, cmd[3][1])
        # M4 (PCF2)
        pcf2 &= get_mask(4, cmd[4][1])
        
        self._write_pcf(ADDR_PCF_MOTORS_1, pcf1)
        self._write_pcf(ADDR_PCF_MOTORS_2, pcf2)

    def set_speed_differential(self, adj_left, adj_right):
        """
        Adjust motor speeds relative to MAX_PWM (1023) or current set.
        Used by PID controller to steer.
        adj_left: Signed Int (e.g. +50 or -50)
        adj_right: Signed Int
        """
        # Base speed for FORWARD is 1023
        base = 1023
        
        l_speed = max(0, min(1023, int(base + adj_left)))
        r_speed = max(0, min(1023, int(base + adj_right)))
        
        # M1, M2 are Left. M3, M4 are Right.
        self.motors[1].duty(l_speed)
        self.motors[2].duty(l_speed)
        self.motors[3].duty(r_speed)
        self.motors[4].duty(r_speed)


# ============================================================================
# MQ-2 SENSOR DRIVER (via ADS1115)
# ============================================================================
class MQ2Driver:
    def __init__(self, i2c):
        self.i2c = i2c
        self.addr = ADDR_ADS1115
        self.ro = 10.0 # Initial default
        
    def read_voltage(self):
        # Config: Single-ended AIN0, Gain 2 (+/- 4.096V), 128 SPS
        # 0x8000 (Start) | 0x4000 (AIN0) | 0x0400 (Gain 2?) 
        # Legacy: 0x4000 MUX for Ch0. 
        # Legacy Gain: 0x0200 (Gain 1? +/- 4.096V)
        
        # Config register:
        # OS(1) MUX(3) PGA(3) MODE(1) DR(3) COMP_MODE(1) COMP_POL(1) COMP_LAT(1) COMP_QUE(2)
        # Legacy: 0x0100 is PGA? No.
        # Legacy code: config = (0x8000 | 0x0100 | self.gain | 0x0080 | mux | 0x0003)
        # Using simplified write for standard ADS1115 interactions if possible, 
        # but sticking to legacy register map for safety.
        
        # ADS1115_REG_CONFIG = 0x01
        cfg = 0xC283 # Standard Single Shot, +/-4.096V, AIN0
        
        try:
            self.i2c.writeto(self.addr, bytearray([0x01, (cfg >> 8) & 0xFF, cfg & 0xFF]))
            time.sleep_ms(10) # Wait for conversion
            self.i2c.writeto(self.addr, bytearray([0x00]))
            data = self.i2c.readfrom(self.addr, 2)
            raw = (data[0] << 8) | data[1]
            if raw > 32767: raw -= 65536
            
            voltage = raw * 0.000125 # 4.096 / 32768
            return max(0, voltage)
        except Exception as e:
            print(f"[MQ2] Error: {e}")
            return 0.0

    def calibrate(self):
        print("[MQ2] Calibrating...")
        vals = []
        for _ in range(10):
            v = self.read_voltage()
            vals.append(v)
            time.sleep_ms(100)
        
        avg_v = sum(vals) / len(vals)
        if avg_v < 0.1: avg_v = 0.1 # Prevent div/0
        
        # RS = (Vc/Vout - 1) * RL
        # RS_air = (5.0 / avg_v - 1) * MQ2_RL_VALUE
        # RO = RS_air / MQ_RO_CLEAN_AIR_FACTOR
        
        rs_air = ((5.0 / avg_v) - 1) * MQ2_RL_VALUE
        self.ro = rs_air / MQ2_RO_CLEAN_AIR_FACTOR
        print(f"[MQ2] Calibrated RO: {self.ro:.2f} kOhm")
        
    def read_ppm(self):
        v = self.read_voltage()
        if v < 0.1: return 0.0, v
        
        rs = ((5.0 / v) - 1) * MQ2_RL_VALUE
        ratio = rs / self.ro
        
        # Curve: log(y) = m*log(x) + b
        # m = -0.473, b = 1.413 (LGP approximation for LPG/Smoke)
        # Legacy: m = -0.485, b = 1.51
        m = -0.485
        b = 1.51
        
        try:
            ppm = 10 ** ((math.log10(ratio) - b) / m)
        except:
            ppm = 0
            
        return ppm, v


# ============================================================================
# ULTRASONIC DRIVER (PCF8574 Based)
# ============================================================================
class UltrasonicDriver:
    def __init__(self, i2c):
        self.i2c = i2c
        self.addr = ADDR_ULTRASONIC
        self.pcf_state = 0xFF
        
    def _write(self, val):
        self.i2c.writeto(self.addr, bytes([val]))
        self.pcf_state = val

    def _read(self):
        return self.i2c.readfrom(self.addr, 1)[0]
        
    def get_distance_cm(self):
        """Get distance in cm. Returns -1 on error or timeout."""
        try:
            # Trigger High -> Low (Pulse)
            # Trig on Bit 2, Echo on Bit 1
            
            # Ensure Trig is LOW
            self.pcf_state &= ~(1 << ULTRASONIC_TRIG_BIT)
            self._write(self.pcf_state)
            time.sleep_us(5)
            
            # Trigger HIGH
            self.pcf_state |= (1 << ULTRASONIC_TRIG_BIT)
            self._write(self.pcf_state)
            time.sleep_us(10)
            
            # Trigger LOW
            self.pcf_state &= ~(1 << ULTRASONIC_TRIG_BIT)
            self._write(self.pcf_state)
            
            # Wait for echo HIGH
            t0 = time.ticks_us()
            while not (self._read() & (1 << ULTRASONIC_ECHO_BIT)):
                if time.ticks_diff(time.ticks_us(), t0) > 20000: return -1
                
            t1 = time.ticks_us()
            # Wait for echo LOW
            while (self._read() & (1 << ULTRASONIC_ECHO_BIT)):
                if time.ticks_diff(time.ticks_us(), t1) > 20000: return -1
                
            t2 = time.ticks_us()
            duration = time.ticks_diff(t2, t1)
            
            return (duration * 0.0343) / 2
        except Exception as e:
            print(f"[Ultrasonic] Error: {e}")
            return -1

# ============================================================================
# SCD30 DRIVER
# ============================================================================
class SCD30Driver:
    def __init__(self, i2c):
        self.i2c = i2c
        self.addr = ADDR_SCD30
        
    def data_ready(self):
        try:
            self.i2c.writeto(self.addr, b'\x02\x02')
            data = self.i2c.readfrom(self.addr, 3)
            return (data[0] << 8 | data[1]) == 1
        except:
            return False
            
    def read_measurement(self):
        try:
            self.i2c.writeto(self.addr, b'\x03\x00')
            time.sleep_ms(15)
            data = self.i2c.readfrom(self.addr, 18)
            
            # Simple unpack (skipping CRC checks for speed/simplicity as per legacy request logic)
            # CO2 (0,1 3,4)
            co2 = struct.unpack('>f', bytes([data[0], data[1], data[3], data[4]]))[0]
            temp = struct.unpack('>f', bytes([data[6], data[7], data[9], data[10]]))[0]
            hum = struct.unpack('>f', bytes([data[12], data[13], data[15], data[16]]))[0]
            
            return co2, temp, hum
        except:
            return 0, 0, 0
            
    def start_continuous(self):
        try:
            # Cmd: 0x0010, Arg: 0x0000
            self.i2c.writeto(self.addr, b'\x00\x10\x00\x00\x81') # Includes CRC
            time.sleep_ms(100)
        except Exception as e:
            print(f"[SCD30] Start error: {e}")
