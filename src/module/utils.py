import os
import psutil

class Utils:
    @staticmethod
    def cpu_load() -> str:
        return str(int(psutil.cpu_percent())) + '%'

    @staticmethod
    def cpu_temp() -> str:
        """Read CPU temperature from sysfs — no gpiozero needed."""
        try:
            base = "/sys/class/thermal"
            zones = sorted(
                int(e.replace("thermal_zone", ""))
                for e in os.listdir(base)
                if e.startswith("thermal_zone")
            )
            if zones:
                path = f"{base}/thermal_zone{zones[0]}/temp"
                with open(path) as f:
                    millideg = int(f.read().strip())
                return f"{millideg // 1000}\u00B0C"
        except Exception:
            pass
        return "--\u00B0C"
    
    @staticmethod
    def memory_usage() -> str:
        return str(int(psutil.virtual_memory().percent)) + '%'
