import time, logging, json, math, atexit
import SDL_Pi_HDC1080
import RPi.GPIO as GPIO
import paho.mqtt.client as paho
from datetime import datetime
from flask import Flask, request, Blueprint, jsonify, render_template
from flask_restful import reqparse, abort, Resource, Api
from apscheduler.schedulers.background import BackgroundScheduler

# define config
SOFA = "sofa"
TRIGGERS = {
	SOFA: 23
}

# MQTT connection variables
mqttBroker = "10.0.0.21"
mqttPort = 1883
mqttTopic = "environmentals/piflora"
mqttTimeOut = 120

# local Variables
temperature = 0
humidity = 0
dewpoint = 0
message = "waiting for first measurement"

app = Flask(__name__)
api = Api(app)

errors = Blueprint('errors', __name__)

# Configure logging
log = logging.getLogger()
log.addHandler(logging.StreamHandler())
log.setLevel(logging.INFO)


@app.route('/')
def index():
	return render_template('index.html', temperature=temperature, humidity=humidity, dewpoint=dewpoint, message=message)

###
# Keep track of stat
state = {}
def setup():
	log.debug("setup triggers %s" % (TRIGGERS))

	GPIO.setmode(GPIO.BCM)
	GPIO.setup(TRIGGERS[SOFA], GPIO.OUT)
	GPIO.output(TRIGGERS[SOFA], GPIO.LOW)

	state[SOFA] = GPIO.LOW

def clean():
	logging.debug("destroy: turn off and cleanup  pins %s" % (TRIGGERS))
	GPIO.output(TRIGGERS[SOFA], GPIO.LOW) # power off
	GPIO.cleanup() # Release resource

###
# setup parser for extracting data from posts
trigger_parser = reqparse.RequestParser()
trigger_parser.add_argument('trigger', required=False, type=str, help='trigger unkonw or missing')
trigger_parser.add_argument('action', required=True, type=str, help='action missing or failed to be converted')

class Trigger(Resource):
	def get(self, trigger):
		trigger = trigger.strip().lower()
		if not trigger in TRIGGERS:
			return "trigger unkonwn or missing", 404

		info = {
			'trigger': trigger,
			'pin': TRIGGERS[trigger],
			'state': 'on' if state[trigger] == GPIO.HIGH else 'off'
		}

		log.debug('get trigger state: %s' % (info))
		return info, 200

	def post(self, trigger):
		args = trigger_parser.parse_args()
		# trigger = args['trigger'].strip().lower()
		action = args['action'].strip().lower()

		if not trigger in TRIGGERS:
			return "trigger unkonw or missing", 404

		state[trigger] = GPIO.HIGH if action == 'on' else GPIO.LOW
		GPIO.output(TRIGGERS[trigger], state[trigger])

		info = {
			'trigger': trigger,
			'pin': TRIGGERS[trigger],
			'state': action
		}
		log.debug('set trigger state: %s' % (info))
		return info, 200

@errors.app_errorhandler(Exception)
def handle_error(error):
	logger.warn(error)
	message = [str(x) for x in error.args]
	status_code = error.status_code
	success = False
	response = {
		'success': success,
		'error': {
			'type': error.__class__.__name__,
			'message': message
		}
	}

	return jsonify(response), status_code

def on_log(client, userdata, level, buff):
	log.log(level, buff)

def on_connect(client, userdata, flags, rc):
	log.debug("connected with result code '%s'" % str(rc))

def on_publish(client, userdata, result):
	log.debug("data published '%s'" % result)

def read():
	global temperature, humidity, dewpoint, message

	time = datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')

	hdc1080 = SDL_Pi_HDC1080.SDL_Pi_HDC1080()

	temperature = round(hdc1080.readTemperature(), 2)
	humidity = round(hdc1080.readHumidity(), 1)
	dewpoint = round(calc_dewpoint(temperature, humidity), 1)

	data = {
		'temperature': temperature,
		'humidity': humidity
	}

	log.info("reading HDC1080 { temperature: %f C, humidity: %f %%, dewpoint: %.1f }" % (temperature, humidity, dewpoint))

	try:
		client = paho.Client("piflora")
		client.on_connect = on_connect
		client.on_log = on_log
		client.on_publish = on_publish
		client.connect(mqttBroker, mqttPort)
		
		result = client.publish(mqttTopic, json.dumps(data))
		log.debug("published climate: %s" % result)

		message = "measured at: %s " % datetime.now().strftime('%H:%M:%S')

	except Exception as e:
		log.error("failure", exc_info=e)
		message = "failed to send climate data %s" % e
		
def calc_dewpoint(temperature, humidity):
	A = 17.27
	B = 237.7
	alpha = ((A * temperature) / (B + temperature)) + math.log(humidity/100.0)
	return (B * alpha) / (A - alpha)

def init():
	log.info("Sample uses 0x40 and SwitchDoc HDC1080 Breakout board ")
	log.info("Program Started at:"+ time.strftime("%Y-%m-%d %H:%M:%S"))
	log.info("")

	hdc1080 = SDL_Pi_HDC1080.SDL_Pi_HDC1080()

	log.info("------------")
	log.info("Manfacturer ID=0x%X"% hdc1080.readManufacturerID())
	log.info("Device ID=0x%X"% hdc1080.readDeviceID() )
	log.info("Serial Number ID=0x%X"% hdc1080.readSerialNumber())
	# read configuration register
	log.info("configure register = 0x%X" % hdc1080.readConfigRegister())
	# turn heater on
	log.info("turning Heater On")
	hdc1080.turnHeaterOn()
	# read configuration register
	log.info("configure register = 0x%X" % hdc1080.readConfigRegister())
	# turn heater off
	log.info("turning Heater Off")
	hdc1080.turnHeaterOff()
	# read configuration register
	log.info("configure register = 0x%X" % hdc1080.readConfigRegister())

	# change temperature resolution
	log.info("change temperature resolution")
	hdc1080.setTemperatureResolution(SDL_Pi_HDC1080.HDC1080_CONFIG_TEMPERATURE_RESOLUTION_11BIT)
	# read configuration register
	log.info("configure register = 0x%X" % hdc1080.readConfigRegister())
	# change temperature resolution
	log.info("change temperature resolution")
	hdc1080.setTemperatureResolution(SDL_Pi_HDC1080.HDC1080_CONFIG_TEMPERATURE_RESOLUTION_14BIT)
	# read configuration register
	log.info("configure register = 0x%X" % hdc1080.readConfigRegister())

	# change humidity resolution
	log.info("change humidity resolution")
	hdc1080.setHumidityResolution(SDL_Pi_HDC1080.HDC1080_CONFIG_HUMIDITY_RESOLUTION_8BIT)
	# read configuration register
	log.info("configure register = 0x%X" % hdc1080.readConfigRegister())
	# change humidity resolution
	log.info("change humidity resolution")
	hdc1080.setHumidityResolution(SDL_Pi_HDC1080.HDC1080_CONFIG_HUMIDITY_RESOLUTION_14BIT)
	# read configuration register
	log.info("configure register = 0x%X" % hdc1080.readConfigRegister())
	


if __name__ == '__main__':
	init()
	read()
	
	scheduler = BackgroundScheduler(daemon = False)
	scheduler.add_job(func=read, trigger="interval", seconds=300)
	scheduler.start()
	
	
	api.add_resource(Trigger, '/triggers/<trigger>')
	
	app.run(host='0.0.0.0', port=5000, threaded=True, debug=True)

	# Shut down the scheduler when exiting the app
	atexit.register(lambda: scheduler.shutdown())
