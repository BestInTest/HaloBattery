"""Tests for the tray icon life cycle in halo_battery.pyw (#38, #95). No tray, no hardware.

pystray makes an icon's window in the icon's own thread. Until that window exists,
stop() is ignored and a show is lost. The "no devices" icon used to be stopped and
made again each time a device came or went, which could leave a copy in the tray.
Now it is made once and only shown or hidden, and only after its window exists.

Run from the repository root:

    python -m unittest discover -s tests
"""
import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_hide_rename import FakeTrayIcon, HideRenameTestCase, dev, hb, make_app  # noqa: E402


class PlaceholderTests(HideRenameTestCase):
    def setUp(self):
        super().setUp()
        self.made = []
        real_init = FakeTrayIcon.__init__

        def counting_init(icon, *a, **k):
            real_init(icon, *a, **k)
            self.made.append(icon)
        p = mock.patch.object(FakeTrayIcon, "__init__", counting_init)
        p.start()
        self.addCleanup(p.stop)

    def test_made_once_then_only_shown_or_hidden(self):
        app = make_app()
        app.apply([])                         # no device: the "no devices" icon shows
        app.apply([dev()])                    # a device: it hides
        app.apply([dev()])
        app.icons.clear()                     # the device goes away
        app.apply([])
        app.apply([dev()])
        self.assertEqual(len(self.made), 1, "one icon for the whole session")
        ph = self.made[0]
        self.assertEqual(ph.shows, [True, False, True, False])
        self.assertFalse(ph.stopped, "never stopped while the app runs")
        self.assertFalse(ph.visible)

    def test_no_icon_made_while_devices_are_shown(self):
        app = make_app()
        app.apply([dev()])
        self.assertEqual(self.made, [])
        self.assertIsNone(app.placeholder)

    def test_all_devices_hidden_shows_it(self):
        app = make_app({"hidden": {"logitech:C15E09CD": "G502"}})
        app.apply([dev()])
        self.assertTrue(app.placeholder.visible)


class SlowStartTests(HideRenameTestCase):
    """The icon's window is made later than the app asks to show or hide it."""

    def test_waits_for_the_window_before_showing(self):
        started = {}

        class LateIcon(FakeTrayIcon):
            def run(icon, setup=None):
                started["setup"] = setup          # the window is not there yet

        app = make_app()
        with mock.patch.object(hb.pystray, "Icon", LateIcon), \
                mock.patch.object(hb, "ICON_READY_TIMEOUT", 0.01):
            app.apply([])
            ph = app.placeholder
            self.assertEqual(ph.shows, [], "no show before the window exists")
            started["setup"](ph)                  # now the window exists
            app.apply([])
            self.assertEqual(ph.shows, [True])

    def test_quick_device_after_start_leaves_no_copy(self):
        """#95: a device comes back right after the "no devices" icon was made. The old
        code stopped an icon that was not running yet (ignored by pystray) and forgot it."""
        app = make_app()
        with mock.patch.object(hb.threading, "Thread", threading.Thread):
            class SlowIcon(FakeTrayIcon):
                def run(icon, setup=None):
                    time.sleep(0.2)                   # a busy PC right after a wake
                    setup(icon)
            with mock.patch.object(hb.pystray, "Icon", SlowIcon):
                app.show_placeholder(True)            # waits for the window, then shows
                app.show_placeholder(False)           # the device is back at once
        ph = app.placeholder
        self.assertEqual(ph.shows, [True, False])
        self.assertFalse(ph.visible, "nothing left in the tray")


class DeviceIconStartTests(unittest.TestCase):
    """The real DeviceIcon shows itself only after its window exists (#61, item 1)."""

    def test_show_waits_for_the_window(self):
        order = []

        class SlowIcon:
            def __init__(icon, *a, **k):
                icon.title, icon.icon = "", None
                icon._visible = False

            @property
            def visible(icon):
                return icon._visible

            @visible.setter
            def visible(icon, value):
                order.append(("visible", value))
                icon._visible = value

            def run(icon, setup=None):
                time.sleep(0.2)
                order.append(("window", True))
                setup(icon)

            def update_menu(icon):
                pass

        app = make_app()
        with mock.patch.object(hb.pystray, "Icon", SlowIcon):
            ic = hb.DeviceIcon(app, "logitech:C15E09CD")
            ic.update(dev())
        self.assertEqual(order, [("window", True), ("visible", True)])


if __name__ == "__main__":
    unittest.main()
