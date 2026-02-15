Setting up the Pi:
- Configure SSH and Wifi
- Wire up components like here: https://tutorials-raspberrypi.de/raspberry-pi-rfid-rc522-tueroeffner-nfc/ (don't follow the rest of the tutorial)
- Run `raspi-config` and enable SPI and reboot
- Copy code over to the Pi: ./sync_to_pi.sh nfelger@tontraeger:~/tontraeger
- Install uv `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Install Python headers: `sudo apt update && sudo apt install python3.11-dev`




