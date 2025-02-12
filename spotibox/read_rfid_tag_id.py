# spotibox/read_rfid_tag_id.py

from rfid_reader import RFIDReader
reader = RFIDReader()

try:
    print("Place your RFID card near the reader...")
    id = reader.read_tag()
    print(f"ID: {id}")
finally:
    reader.cleanup()
