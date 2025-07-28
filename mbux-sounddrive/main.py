import pygame
import os
import time
import math # Added for vehicle physics
from AudioLoop import AudioLoop
from OBDHandler import OBDHandler

# Pygame GUI constants
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (255, 0, 0)
GREEN = (0, 200, 0)
BLUE = (0, 0, 255)
BACKGROUND_COLOR = (60, 60, 60)
FONT_SIZE = 30
FPS = 60

# Simulation parameters from OBD context
MAX_RPM_OUTPUT = 7000
MAX_SPEED_OUTPUT = 80 # MPH
MIN_RPM_OUTPUT = 0 # Technically engine can stall, but for audio, 0 is fine.
IDLE_RPM_OUTPUT = 800

# Vehicle physics constants
VEHICLE_MAX_SPEED_PIXELS = 6.0
VEHICLE_ACCELERATION_RATE = 0.015 # Base acceleration rate
VEHICLE_BRAKING_DECELERATION = 0.025
VEHICLE_TURN_SPEED_DEG = 3.5
VEHICLE_FRICTION = 0.003

# --- Gearbox Simulation Constants ---
GEAR_MAX = 5
# Factors to determine how quickly RPM rises with speed for each gear. Higher factor = lower gear (RPM rises faster for given speed).
# This simulates the gear ratio's effect on engine RPM relative to wheel speed.
GEAR_SPEED_RPM_FACTORS = [2.9, 2.1, 1.6, 1.2, 0.95]  # For gears 1-5 respectively
# Acceleration multiplier per gear (higher = more torque/acceleration)
ACCELERATION_FACTOR_PER_GEAR = [1.7, 1.4, 1.1, 0.9, 0.75] # For gears 1-5
# RPM thresholds to consider an upshift FROM the current gear (index 0 for gear 1, etc.)
UPSHIFT_RPM_THRESHOLDS = [5200, 5000, 4800, 4600, MAX_RPM_OUTPUT + 1] # Gear 5 doesn't upshift
# RPM thresholds to consider a downshift FROM the current gear
DOWNSHIFT_RPM_THRESHOLDS = [IDLE_RPM_OUTPUT -1, 1800, 2000, 2200, 2400] # Gear 1 doesn't downshift further
# Minimum speed (MPH) required to comfortably operate IN a gear (index 0 for G1, 1 for G2 etc.)
# Used to check if a target lower gear is viable during downshift.
MIN_SPEED_FOR_GEAR_OPERATION = [0, 10, 22, 35, 50]
# Minimum speed (MPH) to consider an upshift FROM the current gear
MIN_SPEED_FOR_UPSHIFT_FROM_GEAR = [8, 18, 30, 45, MAX_SPEED_OUTPUT + 1] # G5 never upshifts


class Vehicle(pygame.sprite.Sprite):
    def __init__(self, x, y, angle=0.0):
        super().__init__()
        self.original_image = pygame.Surface([40, 20], pygame.SRCALPHA)
        self.original_image.fill(GREEN)
        pygame.draw.polygon(self.original_image, RED, [(40, 0), (40, 20), (30, 10)])
        self.image = self.original_image
        self.rect = self.image.get_rect(center=(x, y))

        self.position = pygame.math.Vector2(x, y)
        self.velocity = pygame.math.Vector2(0, 0)
        self.angle = angle
        
        self.is_accelerating = False
        self.is_braking = False
        self.turn_direction = 0

        # Gearbox state
        self.current_gear = 1
        # Assign constants to instance for easier access if needed, though direct use is fine
        self.gear_speed_rpm_factors = GEAR_SPEED_RPM_FACTORS
        self.acceleration_factor_per_gear = ACCELERATION_FACTOR_PER_GEAR
        self.upshift_rpm_thresholds = UPSHIFT_RPM_THRESHOLDS
        self.downshift_rpm_thresholds = DOWNSHIFT_RPM_THRESHOLDS
        self.min_speed_for_gear_operation = MIN_SPEED_FOR_GEAR_OPERATION
        self.min_speed_for_upshift_from_gear = MIN_SPEED_FOR_UPSHIFT_FROM_GEAR


    def update(self, dt=1):
        # --- Handle Turning ---
        if self.turn_direction != 0:
            self.angle += self.turn_direction * VEHICLE_TURN_SPEED_DEG * dt
            self.angle %= 360

        # --- Handle Acceleration/Braking ---
        effective_accel_rate = 0
        if self.is_accelerating:
            # Apply gear-based acceleration modification
            effective_accel_rate = VEHICLE_ACCELERATION_RATE * self.acceleration_factor_per_gear[self.current_gear-1]
        
        rad_angle = math.radians(self.angle)
        forward_vector = pygame.math.Vector2(math.cos(rad_angle), math.sin(rad_angle))
        self.velocity += forward_vector * effective_accel_rate * dt

        if self.is_braking:
            if self.velocity.length() > 0.01:
                brake_val = VEHICLE_BRAKING_DECELERATION * dt
                if self.velocity.length() < brake_val: self.velocity.xy = (0,0)
                else: self.velocity -= self.velocity.normalize() * brake_val
            else: self.velocity.xy = (0,0)

        # --- Apply Friction ---
        if not self.is_accelerating and self.velocity.length() > 0:
            friction_force = self.velocity.length() * VEHICLE_FRICTION * dt
            if self.velocity.length() < friction_force: self.velocity.xy = (0,0)
            else: self.velocity -= self.velocity.normalize() * friction_force
        
        if self.velocity.length() > VEHICLE_MAX_SPEED_PIXELS:
            self.velocity.scale_to_length(VEHICLE_MAX_SPEED_PIXELS)

        self.position += self.velocity * dt
        
        # Screen Wrap
        if self.position.x > SCREEN_WIDTH: self.position.x = 0
        if self.position.x < 0: self.position.x = SCREEN_WIDTH
        if self.position.y > SCREEN_HEIGHT: self.position.y = 0
        if self.position.y < 0: self.position.y = SCREEN_HEIGHT
        
        # --- Automatic Gear Shifting ---
        current_speed_mph = self.get_speed_mph() # Speed after physics update
        # Use a "raw" RPM for shifting logic, without the cosmetic acceleration bonus
        raw_rpm_for_shifting = self._get_raw_rpm_for_logic(current_speed_mph)

        # Upshifting
        if self.current_gear < GEAR_MAX and \
           raw_rpm_for_shifting > self.upshift_rpm_thresholds[self.current_gear - 1] and \
           current_speed_mph > self.min_speed_for_upshift_from_gear[self.current_gear - 1]:
            self.current_gear += 1
            # print(f"Shifted UP to G{self.current_gear} at RPM {raw_rpm_for_shifting:.0f}, Speed {current_speed_mph:.0f}")

        # Downshifting
        elif self.current_gear > 1:
            rpm_too_low_for_current_gear = raw_rpm_for_shifting < self.downshift_rpm_thresholds[self.current_gear - 1]
            # Check if the speed is appropriate for the TARGET lower gear (current_gear - 1)
            # Target gear index is self.current_gear - 2
            speed_ok_for_target_lower_gear = current_speed_mph >= self.min_speed_for_gear_operation[self.current_gear - 2]

            if rpm_too_low_for_current_gear and speed_ok_for_target_lower_gear:
                self.current_gear -= 1
                # print(f"Shifted DOWN to G{self.current_gear} at RPM {raw_rpm_for_shifting:.0f}, Speed {current_speed_mph:.0f}")
        
        self.image = pygame.transform.rotate(self.original_image, -self.angle)
        self.rect = self.image.get_rect(center=self.position)

    def get_speed_mph(self):
        if VEHICLE_MAX_SPEED_PIXELS == 0: return 0
        normalized_pixel_speed = self.velocity.length() / VEHICLE_MAX_SPEED_PIXELS
        return normalized_pixel_speed * MAX_SPEED_OUTPUT

    def _get_raw_rpm_for_logic(self, speed_mph_param=None):
        """Calculates RPM based purely on speed and gear, for shifting logic."""
        current_speed_mph = speed_mph_param if speed_mph_param is not None else self.get_speed_mph()

        if current_speed_mph < 0.5: # Consistent with get_rpm's idle condition
            return IDLE_RPM_OUTPUT

        # Factor determines how quickly RPM rises with speed for this gear.
        # Higher factor = lower gear (RPM rises faster for given speed).
        gear_idx = self.current_gear - 1
        gear_factor = self.gear_speed_rpm_factors[gear_idx]
        
        # RPM calculation:
        # normalized_speed_in_gear_context represents how "far" into the RPM range the current speed is,
        # considering the gear's specific RPM-to-speed relationship.
        # If gear_factor = 1.0, at MAX_SPEED_OUTPUT, normalized_speed = 1.0.
        # If gear_factor = 2.0 (lower gear), at MAX_SPEED_OUTPUT/2.0, normalized_speed = 1.0.
        normalized_speed_in_gear_context = (current_speed_mph * gear_factor) / MAX_SPEED_OUTPUT
        
        rpm = IDLE_RPM_OUTPUT + normalized_speed_in_gear_context * (MAX_RPM_OUTPUT - IDLE_RPM_OUTPUT)
        
        # Clamp for logic, allow slight over-rev possibility before final clamping in get_rpm
        rpm = min(max(rpm, MIN_RPM_OUTPUT), MAX_RPM_OUTPUT + 500) 
        if current_speed_mph < 0.5: rpm = IDLE_RPM_OUTPUT # Ensure idle at very low speed
        return rpm

    def get_rpm(self): # This is the RPM value used by OBDHandler for audio modulation
        current_speed_mph = self.get_speed_mph()
        # Get base RPM from speed and current gear
        rpm = self._get_raw_rpm_for_logic(current_speed_mph)

        # Add a flare/bonus to RPM when accelerating, scaled by gear's torque
        if self.is_accelerating and current_speed_mph < MAX_SPEED_OUTPUT * 0.98 and rpm < MAX_RPM_OUTPUT:
            accel_rpm_bonus_max = 700 
            # More bonus if RPM is lower, less if near redline
            rpm_headroom_factor = max(0, (MAX_RPM_OUTPUT - rpm)) / (MAX_RPM_OUTPUT - IDLE_RPM_OUTPUT + 1) # Avoid div by zero
            gear_torque_factor = self.acceleration_factor_per_gear[self.current_gear-1]
            
            bonus = accel_rpm_bonus_max * rpm_headroom_factor * gear_torque_factor
            rpm += bonus

        # Simulate RPM dip when braking
        if self.is_braking and current_speed_mph > 1.0:
             rpm = max(IDLE_RPM_OUTPUT * 0.85, rpm * 0.92) # Allow RPM to dip more significantly
        
        # Final clamping for display/audio output
        final_rpm = min(max(rpm, MIN_RPM_OUTPUT), MAX_RPM_OUTPUT)
        
        # Ensure RPM is at idle if stopped and not accelerating
        if current_speed_mph < 0.5 and not self.is_accelerating:
             final_rpm = IDLE_RPM_OUTPUT
        
        return final_rpm


def main():
    pygame.init()
    pygame.mixer.init() 
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("Carmony - 2D Driving Sim w/ Gearbox")
    font = pygame.font.Font(None, FONT_SIZE)
    clock = pygame.time.Clock()

    songname = input("Enter song folder name (e.g., 'mysong'): ")
    path = os.path.join("wavs", songname)
    
    if not os.path.isdir(path):
        print(f"Error: Directory '{path}' not found.")
        pygame.quit()
        return

    file_paths = [os.path.join(path, file) for file in os.listdir(path) if file.lower().endswith(".wav")]
    if not file_paths:
        print(f"No .wav files found in '{path}'.")
        pygame.quit()
        return
    
    print(f"Found audio files: {file_paths}")
    try:
        loop = AudioLoop(file_paths)
        loop.start()
        loop.adjust_volumes([0,0,0,0])
    except Exception as e:
        print(f"Error initializing AudioLoop: {e}")
        pygame.quit()
        return

    sim_mode_input = input("Run in simulation mode? (yes/no) [yes]: ").strip().lower()
    simulation_active_choice = sim_mode_input != 'no'

    if simulation_active_choice:
        print("Running in Simulation Mode.")
        handler = OBDHandler(simulate=True)
    else:
        print("Attempting to connect to OBD...")
        obd_port_input = input(f"Enter OBD port (e.g., COM4 or blank for default): ").strip()
        handler = OBDHandler(simulate=False, port=obd_port_input if obd_port_input else "COM4")
        
    simulation_active = handler.simulate

    player_vehicle = Vehicle(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2, angle=-90)
    all_sprites = pygame.sprite.Group()
    all_sprites.add(player_vehicle)

    running = True
    try:
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                if simulation_active:
                    if event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_UP: player_vehicle.is_accelerating = True
                        elif event.key == pygame.K_DOWN: player_vehicle.is_braking = True
                        elif event.key == pygame.K_LEFT: player_vehicle.turn_direction = -1
                        elif event.key == pygame.K_RIGHT: player_vehicle.turn_direction = 1
                    if event.type == pygame.KEYUP:
                        if event.key == pygame.K_UP: player_vehicle.is_accelerating = False
                        elif event.key == pygame.K_DOWN: player_vehicle.is_braking = False
                        elif event.key == pygame.K_LEFT and player_vehicle.turn_direction == -1: player_vehicle.turn_direction = 0
                        elif event.key == pygame.K_RIGHT and player_vehicle.turn_direction == 1: player_vehicle.turn_direction = 0
            
            if simulation_active:
                all_sprites.update() 
                sim_speed = player_vehicle.get_speed_mph()
                sim_rpm = player_vehicle.get_rpm()
                handler.refresh(sim_speed=sim_speed, sim_rpm=sim_rpm)
            else:
                handler.refresh() 

            volume_list = handler.get_volumes()
            loop.adjust_volumes(volume_list)

            screen.fill(BACKGROUND_COLOR)
            if simulation_active:
                all_sprites.draw(screen)
            
            display_speed = handler.get_speed()
            display_rpm = handler.get_rpm()

            speed_text_surface = font.render(f"Speed: {display_speed:.0f} MPH", True, WHITE)
            rpm_text_surface = font.render(f"RPM: {display_rpm:.0f}", True, WHITE)
            screen.blit(speed_text_surface, (20, 20))
            screen.blit(rpm_text_surface, (20, 60))

            if simulation_active:
                gear_text_surface = font.render(f"Gear: {player_vehicle.current_gear}", True, WHITE)
                screen.blit(gear_text_surface, (20, 100)) # Adjusted Y position

            mode_y_pos = 140 if simulation_active else 100
            mode_text_str = "Mode: Sim (Vehicle w/ Gearbox)" if simulation_active else "Mode: OBD"
            mode_color = WHITE
            if not simulation_active:
                if handler.connection and handler.connection.is_connected():
                    mode_text_str += " (Connected)"
                    mode_color = GREEN
                else:
                    mode_text_str += " (Disconnected)"
                    mode_color = RED
            
            mode_surface = font.render(mode_text_str, True, mode_color)
            screen.blit(mode_surface, (20, mode_y_pos))

            if simulation_active:
                instr_surface = font.render("Controls: Arrow Keys", True, WHITE)
                screen.blit(instr_surface, (20, SCREEN_HEIGHT - 40))
            
            pygame.display.flip()
            clock.tick(FPS)

    except KeyboardInterrupt:
        print("\nExiting program...")
    finally:
        print("Cleaning up...")
        if 'loop' in locals() and hasattr(loop, 'stop'):
             loop.stop() 
        if 'handler' in locals() and hasattr(handler, 'close_connection'):
            handler.close_connection()
        pygame.quit()
        print("Cleanup complete. Exited.")

if __name__ == "__main__":
    main()