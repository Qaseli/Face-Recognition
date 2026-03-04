from RPLCD.i2c import CharLCD
from time import sleep

lcd = CharLCD(
    i2c_expander='PCF8574',
    address=0x27,
    port=1,
    cols=16,
    rows=2,
    charmap='A00'
)

lcd.clear()
lcd.write_string("LCD OK!")
lcd.cursor_pos = (1, 0)
lcd.write_string("Face System")

while True:
    sleep(1)
