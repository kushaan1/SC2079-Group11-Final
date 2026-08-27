# RPi–Android Bluetooth protocol v1

Transport is Bluetooth RFCOMM. Application frames are UTF-8 JSON objects terminated by `\n`, with a
maximum encoded length of 4096 bytes. Both peers must buffer partial socket reads until a newline is
received. Every frame follows
[`schemas/status-message-v1.schema.json`](schemas/status-message-v1.schema.json).

Detection example:

```json
{"version":"1.0","type":"detection","timestamp":"2026-08-27T12:00:00Z","payload":{"object_id":"obstacle-3","status":"target","competition_id":39}}
```

Bull's-eyes use `"status":"bullseye"` and `"competition_id":null`; a frame with no recognised
object uses `"status":"no_detection"`. This distinction drives Task 1 recovery.
