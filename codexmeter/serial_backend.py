"""Non-resetting serial open shared by packaged transports and maintenance tools."""


def open_serial(port, *, timeout=0.1, write_timeout=0.5, factory=None):
    if factory is None:
        import serial

        factory = serial.Serial
    handle = factory()
    handle.port = port
    handle.baudrate = 115200
    handle.bytesize = 8
    handle.parity = "N"
    handle.stopbits = 1
    handle.timeout = timeout
    handle.write_timeout = write_timeout
    handle.xonxoff = False
    handle.rtscts = False
    handle.dsrdtr = False
    handle.dtr = False
    handle.rts = False
    try:
        handle.open()
    except BaseException:
        handle.close()
        raise
    return handle
