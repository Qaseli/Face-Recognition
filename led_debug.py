import RPi.GPIO as GPIO
import time

GREEN = 17
RED = 27

GPIO.setmode(GPIO.BCM)
GPIO.setup(GREEN, GPIO.OUT)
GPIO.setup(RED, GPIO.OUT)

while True:
    print("GREEN ON")
    GPIO.output(GREEN, GPIO.HIGH)
    time.sleep(2)

    print("GREEN OFF")
    GPIO.output(GREEN, GPIO.LOW)
    time.sleep(1)

    print("RED ON")
    GPIO.output(RED, GPIO.HIGH)
    time.sleep(2)

    print("RED OFF")
    GPIO.output(RED, GPIO.LOW)
    time.sleep(1)
