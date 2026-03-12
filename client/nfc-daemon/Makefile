CC = gcc
CFLAGS = -Wall -Wextra -Werror -O2
LDFLAGS = -lnfc

TARGET = nfc-daemon

.PHONY: all clean lint

all: $(TARGET)

$(TARGET): main.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

lint: ## Static analysis (requires cppcheck)
	cppcheck --enable=warning,style,performance --error-exitcode=1 main.c

clean:
	rm -f $(TARGET)
