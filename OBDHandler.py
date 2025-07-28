import obd
import time

class OBDHandler():
    def __init__(self, simulate=False, port="COM4"): # Added simulate and port arguments
        self.simulate = simulate
        self.connection = None
        self.speed = 0  # mph
        self.rpm = 0

        if self.simulate:
            print("OBDHandler initialized in simulation mode.")
        else:
            try:
                print(f"Attempting to connect to OBD on port {port}...")
                self.connection = obd.OBD(port) 
                if not self.connection.is_connected():
                    print(f"Failed to connect to OBD on port {port}. Switching to simulation mode.")
                    self.simulate = True # Fallback to simulation
                    self.connection = None # Ensure connection is None
                else:
                    print(f"Successfully connected to OBD on port {port}.")
                    # Initialize with actual values if possible, or default to 0
                    self.rpm = self._query_rpm()
                    self.speed = self._query_speed()
            except Exception as e:
                print(f"Error connecting to OBD on port {port}: {e}. Switching to simulation mode.")
                self.simulate = True # Fallback to simulation
                self.connection = None # Ensure connection is None
    
    def _query_speed(self):
        """Helper to query actual speed from OBD device."""
        if self.connection and self.connection.is_connected():
            cmd = obd.commands.SPEED
            response = self.connection.query(cmd)
            if response and not response.is_null() and response.value is not None:
                return response.value.to("mph").magnitude
            else:
                print("Warning: OBD speed query returned null or no value.")
        return self.speed # Return current or default if query fails

    def _query_rpm(self):
        """Helper to query actual RPM from OBD device."""
        if self.connection and self.connection.is_connected():
            cmd = obd.commands.RPM
            response = self.connection.query(cmd)
            if response and not response.is_null() and response.value is not None:
                return response.value.magnitude
            else:
                print("Warning: OBD RPM query returned null or no value.")
        return self.rpm # Return current or default if query fails

    def get_speed(self):
        """Returns the current speed. In simulation mode, this is the simulated speed.
           In real mode, this is the last fetched speed."""
        return self.speed if self.speed is not None else 0

    def get_rpm(self):
        """Returns the current RPM. In simulation mode, this is the simulated RPM.
           In real mode, this is the last fetched RPM."""
        return self.rpm if self.rpm is not None else 0
    
    def refresh(self, sim_speed=None, sim_rpm=None):
        """
        Refreshes speed and RPM.
        In simulation mode, updates with provided sim_speed and sim_rpm.
        In real OBD mode, queries the OBD device.
        """
        if self.simulate:
            if sim_speed is not None:
                self.speed = sim_speed
            if sim_rpm is not None:
                self.rpm = sim_rpm
        else:
            if self.connection and self.connection.is_connected():
                self.rpm = self._query_rpm()
                self.speed = self._query_speed()
            else:
                # If connection lost or was never properly established
                # print("OBD not connected. Cannot refresh real data. Using last known values or 0.")
                # Values will remain as they are, or default to 0 if they were None
                if self.speed is None: self.speed = 0
                if self.rpm is None: self.rpm = 0
    
    def get_bass_volume(self):
        current_rpm = self.rpm if self.rpm is not None else 0
        bass_percent = current_rpm / 7000 if 7000 > 0 else 0
        bass_volume = min(bass_percent + 0.5, 1)
        return bass_volume
    
    def get_drums_volume(self):
        current_speed = self.speed if self.speed is not None else 0
        drums_percent = current_speed / 70 if 70 > 0 else 0
        drums_volume = max(min(drums_percent * 7 - 1, 1), 0)
        return drums_volume

    def get_other_volume(self):
        current_speed = self.speed if self.speed is not None else 0
        other_percent = current_speed / 70 if 70 > 0 else 0
        other_volume = max(min(other_percent * 7 - 2.5, 1), 0)
        return other_volume
    
    def get_vocals_volume(self): # Assuming this method exists as per your full file
        current_speed = self.speed if self.speed is not None else 0
        vocals_percent = current_speed / 70 if 70 > 0 else 0
        vocals_volume = max(min(vocals_percent * 7 - 4, 1), 0)
        return vocals_volume
    
    def get_volumes(self):
        volumes = [
            self.get_bass_volume(),
            self.get_drums_volume(),
            self.get_other_volume(),
            self.get_vocals_volume() # Assuming this exists
        ]
        return volumes

    def close_connection(self):
        """Closes the OBD connection if it's open."""
        if self.connection and self.connection.is_connected():
            self.connection.close()
            print("OBD connection closed.")