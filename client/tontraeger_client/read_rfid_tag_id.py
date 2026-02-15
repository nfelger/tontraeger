from tontraeger_client.rfid_reader import RFIDReader
reader = RFIDReader()

try:
    print("Place your RFID card near the reader...")
    tag_id = reader.read_tag()
    print(f"ID: {tag_id}")
finally:
    reader.cleanup()
