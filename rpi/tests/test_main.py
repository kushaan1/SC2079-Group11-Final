from rpi.bt_link import BluetoothLink
from rpi.dispatcher import Dispatcher
from rpi.main import build
from rpi.stm_driver import FakeStmDriver


def test_build_with_fakes_needs_no_hardware():
    wiring = build(fake_stm=True, fake_camera=True)
    assert isinstance(wiring.stm, FakeStmDriver)
    assert isinstance(wiring.link, BluetoothLink)
    assert isinstance(wiring.dispatcher, Dispatcher)
    assert wiring.link.connected is False
