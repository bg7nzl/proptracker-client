# FT8 Propagation Tracker — Tkinter GUI (status + radar + band bar)
from __future__ import annotations

import time
from datetime import datetime

from .bands import VALID_BANDS
from .collector import Collector
from .config import CLIENT_VERSION, SERVER_ENDPOINT
from .http_reporter import HttpReporter
from .propagation_fetcher import PropagationFetcher
from .udp_listener import UdpListener
from .models import PropagationReport


def run_gui(
    port: int,
    log,
    bind_ip: str = "",
    multicast: bool = False,
) -> None:
    try:
        import tkinter as tk
    except ImportError:
        log.error("tkinter not available; use --cli")
        try:
            import sys
            import ctypes
            if getattr(sys, "frozen", False) and sys.platform == "win32":
                ctypes.windll.user32.MessageBoxW(  # type: ignore[union-attr]
                    None,
                    "GUI (tkinter) is not available in this build.\n\n"
                    "To build with GUI, install Python 3.10+ on Windows and run:\n"
                    "  build_windows.bat\n"
                    "or:\n"
                    "  pip install pyinstaller\n"
                    "  pyinstaller ft8_tracker_client.spec\n\n"
                    "For CLI mode: ft8_tracker_client.exe --cli",
                    "FT8 Tracker — No GUI",
                    0x30,
                )
        except Exception:  # noqa: BLE001
            pass
        return
    from .radar_view import RadarView

    def on_report(r: PropagationReport) -> None:
        reporter.submit(r)

    fetcher = PropagationFetcher(log)
    collector = Collector(on_report, on_band_change=fetcher.notify_band)
    reporter = HttpReporter()
    fetcher.start()
    udp = UdpListener(
        port,
        collector.on_status,
        lambda msg, ts: collector.on_decode(msg, ts),
        collector.on_qso_logged,
        log,
        bind_ip=bind_ip,
        multicast=multicast,
    )
    udp.start()

    root = tk.Tk()
    root.title("FT8 Propagation Tracker  v" + CLIENT_VERSION)
    root.geometry("860x500")
    root.resizable(True, True)
    root.minsize(700, 400)

    main_row = tk.Frame(root, padx=8, pady=8)
    main_row.pack(fill=tk.BOTH, expand=True)

    # Left: status panel
    left = tk.Frame(main_row, width=280)
    left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 12))

    def status_row(parent: tk.Frame, label: str, var: tk.StringVar) -> tk.Frame:
        f = tk.Frame(parent)
        f.pack(fill=tk.X, pady=2)
        tk.Label(f, text=label + "  ", width=14, anchor="w").pack(side=tk.LEFT)
        tk.Label(f, textvariable=var, anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True)
        return f

    wsjt_status = tk.StringVar(value="—")
    wsjt_detail = tk.StringVar(value="—")
    my_grid_var = tk.StringVar(value="—")
    freq_var = tk.StringVar(value="—")
    server_status = tk.StringVar(value="—")
    server_endpoint_var = tk.StringVar(
        value=SERVER_ENDPOINT[:48] + "…" if len(SERVER_ENDPOINT) > 50 else SERVER_ENDPOINT
    )
    pending_var = tk.StringVar(value="0")
    last_upload_var = tk.StringVar(value="—")
    stats_var = tk.StringVar(value="RX today: 0   TX QSO: 0")

    tk.Label(left, text="WSJT-X/JTDX", font=("", 10, "bold")).pack(anchor=tk.W)
    status_row(left, "Status", wsjt_status)
    status_row(left, "Instance", wsjt_detail)
    status_row(left, "My Grid", my_grid_var)
    status_row(left, "Frequency", freq_var)
    tk.Label(left, text="Server", font=("", 10, "bold")).pack(anchor=tk.W, pady=(8, 0))
    status_row(left, "Status", server_status)
    status_row(left, "Endpoint", server_endpoint_var)
    status_row(left, "Pending", pending_var)
    status_row(left, "Last upload", last_upload_var)
    tk.Label(left, textvariable=stats_var).pack(anchor=tk.W, pady=(8, 0))

    # Right: radar
    right = tk.Frame(main_row)
    right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    radar = RadarView(right)
    radar.pack(fill=tk.BOTH, expand=True)

    # Band selected for radar; syncs to JTDX band when JTDX switches
    display_band_var = tk.StringVar(value="6m")
    user_picked_band = [False]  # ref so closure can mutate

    def select_band(band: str) -> None:
        user_picked_band[0] = True
        display_band_var.set(band)
        fetcher.request_fetch(band)
        refresh_band_buttons()

    def refresh_band_buttons() -> None:
        current = display_band_var.get() or "6m"
        for b, btn in band_buttons.items():
            if b == current:
                btn.config(bg="#90EE90", activebackground="#7CCD7C")
            else:
                btn.config(bg="#e0e0e0", activebackground="#d0d0d0")

    band_bar = tk.Frame(root)
    band_bar.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=6)
    tk.Label(band_bar, text="Band:", font=("", 9)).pack(side=tk.LEFT, padx=(0, 6))
    band_buttons: dict[str, tk.Button] = {}
    for b in VALID_BANDS:
        btn = tk.Button(
            band_bar,
            text=b,
            width=4,
            font=("", 9),
            command=lambda b=b: select_band(b),
        )
        btn.pack(side=tk.LEFT, padx=2)
        band_buttons[b] = btn

    last_jtdx_band: list[str | None] = [None]

    def update() -> None:
        now = time.time()
        connected = bool(udp.last_message_time and (now - udp.last_message_time) < 30)
        if connected:
            wsjt_status.set("● Connected")
            wsjt_detail.set(udp.instance_id or "—")
            my_grid = collector._my_grid or "—"
            my_grid_var.set(my_grid)
            if my_grid and len(my_grid) >= 2:
                radar.set_my_field(my_grid[:2])
            f = collector._current_frequency
            freq_var.set(f"{f / 1_000_000:.6f} MHz" if f else "—")
            # Sync radar band to JTDX when JTDX switches band
            jtdx_band = collector._current_band
            if jtdx_band:
                if jtdx_band != last_jtdx_band[0]:
                    last_jtdx_band[0] = jtdx_band
                    user_picked_band[0] = False
                    display_band_var.set(jtdx_band)
                    fetcher.request_fetch(jtdx_band)
                elif not user_picked_band[0] and (display_band_var.get() or "6m") != jtdx_band:
                    display_band_var.set(jtdx_band)
                    fetcher.request_fetch(jtdx_band)
        else:
            wsjt_status.set("● Disconnected")
            wsjt_detail.set("—")
            my_grid_var.set("—")
            freq_var.set("—")

        refresh_band_buttons()
        pending_var.set(str(reporter.pending_count))
        if reporter.is_connected is True:
            server_status.set("● Online")
        elif reporter.is_connected is False:
            server_status.set("● Retrying")
        else:
            server_status.set("● —")
        if reporter.last_success_time:
            t = datetime.utcfromtimestamp(reporter.last_success_time).strftime("%H:%M:%S UTC")
            last_upload_var.set(t)
        else:
            last_upload_var.set("—")
        rx, tx = collector.get_stats()
        stats_var.set(f"RX today: {rx}   TX QSO: {tx}")

        # Update radar from fetcher
        band = display_band_var.get() or "6m"
        data = fetcher.get_latest(band)
        if data:
            b64 = data.get("data")
            w_start = data.get("window_start")
            w_end = data.get("window_end")
            if w_start and w_end:
                desc = datetime.utcfromtimestamp(w_start).strftime("%H:%M") + "~" + datetime.utcfromtimestamp(w_end).strftime("%H:%M") + "Z"
            else:
                desc = ""
            radar.update_data(b64, band, desc)
        else:
            radar.update_data(None, band, "")

        root.after(1000, update)

    root.after(500, update)

    def on_closing() -> None:
        fetcher.stop()
        udp.stop()
        reporter.shutdown()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()
