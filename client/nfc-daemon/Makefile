CC = gcc
CFLAGS = -Wall -Wextra -O2
LDLIBS = -lnfc

TARGET = nfc-daemon

.PHONY: all clean

all: $(TARGET)

$(TARGET): main.c
	$(CC) $(CFLAGS) -o $@ $< $(LDLIBS)

clean:
	rm -f $(TARGET)
