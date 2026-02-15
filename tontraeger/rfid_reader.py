import RPi.GPIO as GPIO
from mfrc522 import SimpleMFRC522

class RFIDReader:
    def __init__(self) -> None:
        self.reader = SimpleMFRC522()

    def read_tag(self) -> str:
        """
        Blocks until a tag is presented and returns its UID as a string.
        """
        tag_id = self.reader.read_id()
        return str(tag_id)

    def cleanup(self) -> None:
        """
        Performs GPIO cleanup.
        """
        GPIO.cleanup()
