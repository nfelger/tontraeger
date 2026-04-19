/*
 * NFC presence daemon for tontraeger.
 *
 * Detects ISO14443A tags on a PN532 reader via libnfc.
 * Emits line-based events on stdout:
 *   PRESENT 04:ab:cd:12:34:56:78
 *   REMOVED 04:ab:cd:12:34:56:78
 *
 * Logs go to stderr (flows to journald under systemd).
 * Never exits voluntarily — the parent process detects death via EOF.
 */

#include <stdio.h>
#include <stdlib.h>
#include <inttypes.h>
#include <time.h>
#include <unistd.h>

#include <nfc/nfc.h>

/* Presence polling interval (milliseconds). */
#define POLL_INTERVAL_MS 300

/* How many consecutive presence-check failures before declaring removal. */
#define MISS_THRESHOLD 3

/* Retry delays when the device can't be opened (seconds). */
#define BACKOFF_INITIAL_S 1
#define BACKOFF_MAX_S 30

/* Maximum UID length for ISO14443A tags (bytes). */
#define MAX_UID_LEN 10

/* Format a UID as colon-separated lowercase hex.
 * Example: {0x04, 0xab, 0xcd} → "04:ab:cd" */
static void format_uid(const uint8_t *uid, size_t len, char *buf, size_t bufsize)
{
    size_t pos = 0;
    for (size_t i = 0; i < len; i++) {
        int n = snprintf(buf + pos, bufsize - pos, "%s%02x", i ? ":" : "", uid[i]);
        if (n <= 0 || pos + (size_t)n >= bufsize)
            break;
        pos += (size_t)n;
    }
}

static void msleep(int ms)
{
    struct timespec ts = { .tv_sec = ms / 1000, .tv_nsec = (ms % 1000) * 1000000L };
    nanosleep(&ts, NULL);
}

static uint64_t monotonic_ms(void)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0)
        return 0;
    return ((uint64_t) ts.tv_sec * 1000ULL) + (uint64_t)(ts.tv_nsec / 1000000L);
}

/* Open and initialize the NFC device. Retries forever on failure. */
static nfc_device *open_device(nfc_context *context)
{
    int backoff_s = BACKOFF_INITIAL_S;

    for (;;) {
        nfc_device *dev = nfc_open(context, NULL);
        if (dev == NULL) {
            fprintf(stderr, "nfc-daemon: nfc_open failed, retrying in %ds\n", backoff_s);
            sleep((unsigned)backoff_s);
            if (backoff_s < BACKOFF_MAX_S)
                backoff_s = (backoff_s * 2 > BACKOFF_MAX_S) ? BACKOFF_MAX_S : backoff_s * 2;
            continue;
        }

        if (nfc_initiator_init(dev) < 0) {
            fprintf(stderr, "nfc-daemon: nfc_initiator_init failed: %s, retrying in %ds\n",
                    nfc_strerror(dev), backoff_s);
            nfc_close(dev);
            sleep((unsigned)backoff_s);
            if (backoff_s < BACKOFF_MAX_S)
                backoff_s = (backoff_s * 2 > BACKOFF_MAX_S) ? BACKOFF_MAX_S : backoff_s * 2;
            continue;
        }

        fprintf(stderr, "nfc-daemon: device opened: %s (%s)\n",
                nfc_device_get_name(dev), nfc_device_get_connstring(dev));
        return dev;
    }
}

int main(void)
{
    /* Line-buffer stdout so Python sees events immediately. */
    setlinebuf(stdout);

    nfc_context *context = NULL;
    nfc_init(&context);
    if (context == NULL) {
        fprintf(stderr, "nfc-daemon: nfc_init failed\n");
        return 1;
    }

    nfc_device *dev = open_device(context);

    nfc_modulation mod = {
        .nmt = NMT_ISO14443A,
        .nbr = NBR_106,
    };

    char uid_str[MAX_UID_LEN * 3 + 1] = "";
    uint64_t session_id = 0;

    for (;;) {
        nfc_target target;

        /* Block until a tag arrives. */
        int ret = nfc_initiator_select_passive_target(dev, mod, NULL, 0, &target);

        if (ret < 0 && ret != NFC_ETIMEOUT) {
            /* Device error — close, reopen with backoff. */
            fprintf(stderr, "nfc-daemon: select failed: %s, reopening device\n",
                    nfc_strerror(dev));
            nfc_close(dev);
            dev = open_device(context);
            continue;
        }

        if (ret <= 0) {
            /* No target found (timeout or empty field). Try again. */
            msleep(POLL_INTERVAL_MS);
            continue;
        }

        /* Tag detected. */
        format_uid(target.nti.nai.abtUid, target.nti.nai.szUidLen,
                   uid_str, sizeof(uid_str));
        session_id++;
        uint64_t present_ms = monotonic_ms();

        fprintf(stderr,
                "nfc-daemon: session=%" PRIu64 " present uid=%s atqa=%02x%02x sak=%02x uid_len=%u\n",
                session_id,
                uid_str,
                target.nti.nai.abtAtqa[1], target.nti.nai.abtAtqa[0],
                target.nti.nai.btSak,
                (unsigned int)target.nti.nai.szUidLen);
        printf("PRESENT %s\n", uid_str);

        /* Poll for continued presence. */
        int misses = 0;
        int poll_index = 0;
        while (misses < MISS_THRESHOLD) {
            msleep(POLL_INTERVAL_MS);

            poll_index++;
            int misses_before = misses;
            ret = nfc_initiator_target_is_present(dev, NULL);

            const char *classification = "transient";
            if (ret >= 0) {
                misses = 0;
                classification = "ok";
            } else if (ret == NFC_ETGRELEASED || ret == NFC_EINVARG || ret == NFC_EDEVNOTSUPP) {
                misses++;
                classification = "hard-miss";
            } else {
                /*
                 * Transient communication errors (e.g. NFC_ERFTRANS) are common
                 * on this UART setup while the tag is still present. Treating
                 * them as hard misses causes false REMOVED events.
                 */
                classification = "transient";
            }

            uint64_t elapsed_ms = monotonic_ms() - present_ms;
            fprintf(stderr,
                    "nfc-daemon: session=%" PRIu64 " poll=%d ret=%d class=%s err=\"%s\" misses=%d->%d elapsed_ms=%" PRIu64 "\n",
                    session_id,
                    poll_index,
                    ret,
                    classification,
                    nfc_strerror(dev),
                    misses_before,
                    misses,
                    elapsed_ms);
        }

        fprintf(stderr,
                "nfc-daemon: session=%" PRIu64 " removed uid=%s elapsed_ms=%" PRIu64 " polls=%d terminal_misses=%d\n",
                session_id,
                uid_str,
                monotonic_ms() - present_ms,
                poll_index,
                misses);
        printf("REMOVED %s\n", uid_str);

        /* Deselect so we can detect the next tag (or the same one re-placed). */
        nfc_initiator_deselect_target(dev);
    }

    /* Unreachable, but be tidy. */
    nfc_close(dev);
    nfc_exit(context);
    return 0;
}
