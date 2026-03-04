import RPi.GPIO as GPIO
import time

GREEN = 17
RED = 27

GPIO.setmode(GPIO.BCM)
GPIO.setup(GREEN, GPIO.OUT)
GPIO.setup(RED, GPIO.OUT)

print("Green ON")
GPIO.output(GREEN, GPIO.HIGH)
time.sleep(2)

print("Red ON")
GPIO.output(GREEN, GPIO.LOW)
GPIO.output(RED, GPIO.HIGH)
time.sleep(2)

print("Both OFF")
GPIO.output(GREEN, GPIO.LOW)
GPIO.output(RED, GPIO.LOW)

GPIO.cleanup()
