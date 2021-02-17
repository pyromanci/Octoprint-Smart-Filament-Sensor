# coding=utf-8
#### Python ####
from __future__ import absolute_import
import logging
#import auxiliary_module
from time import sleep
import flask
from enum import Enum

#### Raspberry ####
import RPi.GPIO as GPIO

#### Octoprint ####
import octoprint.plugin
from octoprint.events import Events

#### Smartfilamentsensor Plugin
from octoprint_smart_filament_sensor.data.SfsController import SfsController

class DetectionMethod(Enum):
    TIMEOUT_DETECTION = 0
    DISTANCE_DETECTION = 1

class GpioModes(Enum):
    BOARD_MODE = 0
    BCM_MODE = 1

class SmartFilamentSensor(octoprint.plugin.StartupPlugin,
                                 octoprint.plugin.EventHandlerPlugin,
                                 octoprint.plugin.TemplatePlugin,
                                 octoprint.plugin.SettingsPlugin,
                                 octoprint.plugin.AssetPlugin,
                                 octoprint.plugin.SimpleApiPlugin):

    def initialize(self):
        self.init_logging()
        self._logger.info("Running RPi.GPIO version '{0}'".format(GPIO.VERSION))
        if GPIO.VERSION < "0.6":       # Need at least 0.6 for edge detection
            raise Exception("RPi.GPIO must be greater than 0.6")
        GPIO.setwarnings(True)        # Enable GPIO warnings

        # Constants      
        self._controller = SfsController(self._logger, self.motion_sensor_detection_distance, True, 
            pCbUpdateUI=self.updateToUi, pCbPausePrinter=self.pausePrinter)
    
        if(len(self.extruders) == 0):
            self.extruders = self.addExtruder(-1)
        else:
            self._controller.loadExtruders(self.extruders)

#Properties
    @property
    def motion_sensor_pause_print(self):
        return self._settings.get_boolean(["motion_sensor_pause_print"])

    @property
    def detection_method(self):
        return int(self._settings.get(["detection_method"]))

    @property
    def pause_command(self):
        return self._settings.get(["pause_command"])

    @property
    def extruders(self):
        return self._settings.get(["extruders"])

    @extruders.setter
    def extruders(self, value):
        self._settings.set(["extruders"], value)

#Distance detection
    @property
    def motion_sensor_detection_distance(self):
        return int(self._settings.get(["motion_sensor_detection_distance"]))

#Timeout detection
    @property
    def motion_sensor_max_not_moving(self):
        return int(self._settings.get(["motion_sensor_max_not_moving"]))

#General Properties
    @property
    def mode(self):
        return int(self._settings.get(["mode"]))

# Initialization methods
    def _setup_sensor(self):
        # Clean up before intializing again, because ports could already be in use
        #GPIO.cleanup()

        if(self.mode == GpioModes.BOARD_MODE.value):
            self._logger.info("Using Board Mode")
            GPIO.setmode(GPIO.BOARD)
        else:
            self._logger.info("Using BCM Mode")
            GPIO.setmode(GPIO.BCM)

        #GPIO.setup(self.motion_sensor_pin, GPIO.IN)
        #self.init_gpio_pins()
        #self.init_sensor_event_callback()
        self.is_one_sensor_enabled(logging=True)
        
        self._controller.filament_moving = False

        self.load_smart_filament_sensor_controller()

    def init_gpio_pins(self):
        for extr in self._controller.extruders:
            pin = extr.pin
            GPIO.setup(pin, GPIO.IN)
            self._logger.info("Setup input pin: %r" % (pin))

    def init_sensor_event_callback(self):
        # Add reset_distance if detection_method is distance_detection
        if (self.detection_method == DetectionMethod.DISTANCE_DETECTION.value):
            # Remove event first, because it might been in use already
            for extr in self._controller.extruders:
                pin = extr.pin
                try:
                    GPIO.remove_event_detect(pin)
                except:
                    self._logger.warn("Pin " + str(pin) + " not used before")

                GPIO.add_event_detect(pin, GPIO.BOTH, callback=self.reset_distance)

    def is_one_sensor_enabled(self, logging=False):
        enabled = False
        for extr in self._controller.extruders:
            if extr.is_enabled == True:
                enabled = True
            elif logging == True and extr.is_enabled == False:
                self._logger.info("Motion sensor pin %r is deactivated" % (extr.pin))           

        return enabled

    def load_smart_filament_sensor_controller(self):
        self._controller.remaining_distance = self.motion_sensor_detection_distance

    def on_after_startup(self):
        self._logger.info("Smart Filament Sensor started")
        self._setup_sensor()

    def get_settings_defaults(self):
        return dict(
            #Motion sensor
            mode=0, #GpioModes.BOARD_MODE
            detection_method = 0, #DetectionMethod.TIMEOUT_DETECTION

            # Distance detection
            motion_sensor_detection_distance = 15, # Recommended detection distance from Marlin would be 7

            # Timeout detection
            motion_sensor_max_not_moving=45,  # Maximum time no movement is detected - default continously
            pause_command="M600",
            extruders=[]
        )

    def on_settings_save(self, data):
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
        self._setup_sensor()

    def get_template_configs(self):
        return [dict(type="settings", custom_bindings=True)]

    def get_assets(self):
        return dict(js=["js/smartfilamentsensor_sidebar.js", "js/smartfilamentsensor_settings.js"])

#### Logging ####      
    def init_logging(self):
        # setup customized logger
        from octoprint.logging.handlers import CleaningTimedRotatingFileHandler

        self._logger = logging.getLogger('sfs')
        sfs_logging_handler = CleaningTimedRotatingFileHandler(
            self._settings.get_plugin_logfile_path(),
            when="D",
            backupCount=3,
        )
        sfs_logging_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(module)s.%(funcName)s] %(levelname)s: %(message)s")
        )
        sfs_logging_handler.setLevel(logging.DEBUG)

        self._logger.addHandler(sfs_logging_handler)
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = False

# Sensor methods
    # Starts the motion sensor if the sensors are enabled
    def motion_sensor_start(self):
        #self._logger.debug("Sensor enabled: " + str(self.motion_sensor_enabled))
        
        if self.is_one_sensor_enabled():
            if (self.mode == GpioModes.BOARD_MODE.value):
                self._logger.debug("GPIO mode: Board Mode")
            else:
                self._logger.debug("GPIO mode: BCM Mode")

            for extr in self._controller.extruders:
                self._logger.debug("GPIO pin: " + str(extr.pin))

            # Distance detection            
            if (self.detection_method == DetectionMethod.DISTANCE_DETECTION.value):
                self._logger.info("Motion sensor started: Distance detection")
                self._logger.debug("Detection Mode: Distance detection")
                self._logger.debug("Distance: " + str(self.motion_sensor_detection_distance))
                self._controller.startDistanceDetection()

            # Timeout detection
            elif (self.detection_method == DetectionMethod.TIMEOUT_DETECTION.value):
                self._controller.startTimeoutDetection(self.motion_sensor_max_not_moving)

            self._controller.send_pause_code = False
            self._controller.filament_moving = True

# Sensor callbacks
    # Reset the distance, if the remaining distance is smaller than the new value
    def reset_distance (self, pPin):
        self._logger.debug("Motion sensor detected movement")
        self._controller.send_pause_code = False
        self._controller.extruders[self._controller.tool].reset_distance()

    def updateToUi(self, pObject=None):
        self._logger.debug("Refresh UI")
        if(pObject is not None):
            self._plugin_manager.send_plugin_message(self._identifier, pObject.toJSON())
        else:
            self._plugin_manager.send_plugin_message(self._identifier, self._controller.toJSON())

    def pausePrinter(self):
        self._printer.commands(self.pause_command)

    # Remove motion sensor thread if the print is paused
    def print_paused(self, pEvent=""):
        self._controller.print_started = False
        self._logger.info("%s: Pausing filament sensors." % (pEvent))
        if self.is_one_sensor_enabled() and self.detection_method == DetectionMethod.TIMEOUT_DETECTION.value:
            self._controller.stopTimeoutDetection()

# Events
    def on_event(self, event, payload):     
        if event is Events.PRINT_STARTED:
            self._controller.stopConnectionTest()
            self._controller.print_started = True
            if(self.detection_method == DetectionMethod.DISTANCE_DETECTION.value):
                self._controller.resetDistanceDetectionForAll()

        elif event is Events.PRINT_RESUMED:
            self._controller.print_started = True

            # If distance detection is used reset the remaining distance, because otherwise the print is not resuming anymore
            if(self.detection_method == DetectionMethod.DISTANCE_DETECTION.value):
                self._controller.extruders[self._controller.tool].reset_remaining_distance()

            self.motion_sensor_start()

        # Start motion sensor on first G1 command
        elif event is Events.Z_CHANGE:
            if(self._controller.print_started):
                self.motion_sensor_start()

                # Set print_started to False to prevent that the starting command is called multiple times
                self._controller.print_started = False         

        # Disable sensor
        elif event in (
            Events.PRINT_DONE,
            Events.PRINT_FAILED,
            Events.PRINT_CANCELLED,
            Events.ERROR
        ):
            self._logger.info("%s: Disabling filament sensors." % (event))
            self._controller.print_started = False
            if self.is_one_sensor_enabled() and self.detection_method == DetectionMethod.TIMEOUT_DETECTION.value:
                self._controller.stopTimeoutDetection()

        # Disable motion sensor if paused
        elif event is Events.PRINT_PAUSED:
            self.print_paused(event)
        
        elif event is Events.USER_LOGGED_IN:
            self.updateToUi()

        elif event is Events.SETTINGS_UPDATED:
            self._controller.loadExtruders(self.extruders)

# API commands
    def get_api_commands(self):
        return dict(
            startConnectionTest=[],
            stopConnectionTest=[]
        )

    def on_api_command(self, command, data):
        self._logger.info("API: " + command)
        if(command == "startConnectionTest"):
            self._controller.startConnectionTest()
            return flask.make_response("Started connection test", 204)
        elif(command == "stopConnectionTest"):
            self._controller.stopConnectionTest()
            return flask.make_response("Stopped connection test", 204)
        else:
            return flask.make_response("Not found", 404)

# Plugin update methods
    def update_hook(self):
        return dict(
            smartfilamentsensor=dict(
                displayName="Smart Filament Sensor",
                displayVersion=self._plugin_version,

                # version check: github repository
                type="github_release",
                user="maocypher",
                repo="Octoprint-Smart-Filament-Sensor",
                current=self._plugin_version,

                # stable releases
                stable_branch=dict(
					name="Stable",
					branch="master",
					comittish=["master"]
				),

				# release candidates
				prerelease_branches=[
					dict(
						name="Release Candidate",
						branch="PreRelease",
						comittish=["PreRelease"],
					)
				],

                # update method: pip
                pip="https://github.com/maocypher/Octoprint-Smart-Filament-Sensor/archive/{target_version}.zip"
            )
        )

    # Interprete the GCode commands that are sent to the printer to print the 3D object
    # G92: Reset the distance detection values
    # G0 or G1: Caluclate the remaining distance
    def distance_detection(self, comm_instance, phase, cmd, cmd_type, gcode, *args, **kwargs):
        # Only performed if distance detection is used
        if(self.detection_method == DetectionMethod.DISTANCE_DETECTION.value and self.is_one_sensor_enabled()):
            # G0 and G1 for linear moves and G2 and G3 for circle movements
            if(gcode == "G0" or gcode == "G1" or gcode == "G2" or gcode == "G3"):
                commands = cmd.split(" ")

                for command in commands:
                    if (command.startswith("E")):
                        extruder = command[1:]
                        self._controller.extruders[self._controller.tool].filament_moved(float(extruder))
                        self._logger.debug("E: " + extruder)

            # G92 reset extruder
            elif(gcode == "G92"):
                if(self.detection_method == DetectionMethod.DISTANCE_DETECTION.value):
                    self._controller.resetDistanceDetectionForAll()
                self._logger.debug("G92: Reset Extruders")

            # M82 absolut extrusion mode
            elif(gcode == "M82"):
                self._controller.absolut_extrusion = True
                self._logger.info("M82: Absolut extrusion")

            # M83 relative extrusion mode
            elif(gcode == "M83"):
                self._controller.absolut_extrusion = False
                self._logger.info("M83: Relative extrusion")

            elif(gcode.startswith("T")):
                tool = int(gcode[1:])
                self._controller.tool = tool

        return cmd

__plugin_name__ = "Smart Filament Sensor"
__plugin_version__ = "1.2.0"
__plugin_pythoncompat__ = ">=2.7,<4"

def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = SmartFilamentSensor()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.update_hook,
        "octoprint.comm.protocol.gcode.sent": __plugin_implementation__.distance_detection
    }



def __plugin_check__():
    try:
        import RPi.GPIO
    except ImportError:
        return False

    return True
