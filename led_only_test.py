import RPi.GPIO as GPIO
import time

GREEN = 17
RED = 27

GPIO.setmode(GPIO.BCM)
GPIO.setup(GREEN, GPIO.OUT)
GPIO.setup(RED, GPIO.OUT)

while True:
    GPIO.output(GREEN, 1)
    print("Green ON")
    time.sleep(1)

    GPIO.output(GREEN, 0)
    GPIO.output(RED, 1)
    print("Red ON")
    time.sleep(1)

    GPIO.output(RED, 0)
