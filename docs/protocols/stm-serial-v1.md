# RPi–STM32 serial protocol v1

Transport is USB serial or hardware UART at 115200 baud, 8 data bits, no parity, one stop bit. Each
UTF-8 JSON object is one frame terminated by `\n`. A receiver must reject malformed JSON, unsupported
versions, and lines larger than 4096 bytes. The sender assigns a unique `message_id`; the receiver
answers with an `ack` containing the same ID only after the command finishes.

RPi command example:

```json
{"version":"1.0","message_id":"motion-42","action":"turn_left","angle_deg":90,"speed":35}
```

STM32 acknowledgement example:

```json
{"version":"1.0","type":"ack","message_id":"motion-42","status":"completed"}
```

The machine-checkable RPi command schema is
[`schemas/stm-command-v1.schema.json`](schemas/stm-command-v1.schema.json). Motion values are supplied
by the STM subsystem's calibrated configuration; this protocol does not define physical constants.
For Task 2, `execute_left_route` and `execute_right_route` select calibrated S-curve macros on the
STM32. The vision module never supplies an uncalibrated steering angle or speed.
