# FT8 Propagation Tracker — Tkinter GUI (status + radar + band bar)
from __future__ import annotations

import time
from datetime import datetime

from .bands import VALID_BANDS
from . import config as _cfg
from .collector import Collector
from .http_reporter import HttpReporter
from .propagation_fetcher import PropagationFetcher
from .pskreporter_fetcher import PskReporterFetcher
from .udp_listener import UdpListener
from .models import PropagationReport


def run_gui(
    port: int,
    log,
    bind_ip: str = "",
    other_bind_ip: str | None = None,
    multicast: bool = False,
    udp_locked: bool = False,
    api_key: str | None = None,
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
    reporter = HttpReporter(api_key=api_key)
    fetcher.start()

    def get_psk_grid() -> str | None:
        g = getattr(collector, "_my_grid", None) or ""
        return (g[:2].upper()) if g and len(g) >= 2 else None

    def get_psk_callsign() -> str | None:
        return getattr(collector, "_my_call", None) or None

    psk_fetcher = PskReporterFetcher(log, get_psk_grid, get_psk_callsign)

    cur_ip = [bind_ip]
    cur_port = [port]
    cur_multicast = [multicast]

    def make_udp_listener_ex(use_multicast: bool, ip: str, p: int):
        return UdpListener(
            p,
            collector.on_status,
            lambda msg, ts: collector.on_decode(msg, ts),
            collector.on_qso_logged,
            log,
            bind_ip=ip,
            multicast=use_multicast,
        )

    udp_ref: list[UdpListener] = [
        make_udp_listener_ex(cur_multicast[0], cur_ip[0], cur_port[0]),
    ]
    udp_ref[0].start()

    root = tk.Tk()
    root.title("FT8 Propagation Tracker  v" + _cfg.CLIENT_VERSION)
    root.geometry("860x590")
    root.resizable(True, True)
    root.minsize(700, 490)

    def toggle_transparency() -> None:
        try:
            a = root.attributes("-alpha")
            if a is None:
                a = 1.0
            if a >= 0.99:
                root.attributes("-alpha", 0.5)
                trans_btn.config(text="Opaque (1.0)")
            else:
                root.attributes("-alpha", 1.0)
                trans_btn.config(text="Transparent (0.5)")
        except tk.TclError:
            pass

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
        value=_cfg.SERVER_ENDPOINT[:48] + "…" if len(_cfg.SERVER_ENDPOINT) > 50 else _cfg.SERVER_ENDPOINT
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

    # UDP settings section
    tk.Label(left, text="UDP", font=("", 10, "bold")).pack(anchor=tk.W, pady=(8, 0))

    if udp_locked:
        udp_lock_row = tk.Frame(left)
        udp_lock_row.pack(fill=tk.X, pady=2)
        mode_text = "Multicast" if multicast else "Unicast"
        tk.Label(udp_lock_row, text=f"{mode_text}  {bind_ip}:{port}", anchor="w").pack(
            side=tk.LEFT, fill=tk.X, expand=True,
        )
    else:
        multicast_var = tk.BooleanVar(value=multicast)
        ip_var = tk.StringVar(value=bind_ip)
        port_var = tk.StringVar(value=str(port))

        def on_multicast_toggle() -> None:
            if multicast_var.get():
                ip_var.set(_cfg.UDP_MULTICAST_IP)
                port_var.set(str(_cfg.UDP_DEFAULT_PORT))
            else:
                ip_var.set(_cfg.UDP_UNICAST_IP)
                port_var.set(str(_cfg.UDP_DEFAULT_PORT))

        def apply_udp() -> None:
            new_ip = ip_var.get().strip()
            try:
                new_port = int(port_var.get().strip())
            except ValueError:
                log.warning("Invalid port number: %s", port_var.get())
                return
            new_mc = multicast_var.get()
            udp_ref[0].stop()
            time.sleep(0.25)
            cur_ip[0] = new_ip
            cur_port[0] = new_port
            cur_multicast[0] = new_mc
            udp_ref[0] = make_udp_listener_ex(new_mc, new_ip, new_port)
            udp_ref[0].start()
            log.info(
                "UDP switched → %s %s:%d",
                "multicast" if new_mc else "unicast", new_ip, new_port,
            )

        chk_row = tk.Frame(left)
        chk_row.pack(fill=tk.X, pady=2)
        tk.Checkbutton(
            chk_row, text="Multicast", variable=multicast_var, command=on_multicast_toggle,
        ).pack(side=tk.LEFT)

        ip_row = tk.Frame(left)
        ip_row.pack(fill=tk.X, pady=1)
        tk.Label(ip_row, text="IP", width=5, anchor="w").pack(side=tk.LEFT)
        tk.Entry(ip_row, textvariable=ip_var, width=18).pack(side=tk.LEFT, fill=tk.X, expand=True)

        port_row = tk.Frame(left)
        port_row.pack(fill=tk.X, pady=1)
        tk.Label(port_row, text="Port", width=5, anchor="w").pack(side=tk.LEFT)
        tk.Entry(port_row, textvariable=port_var, width=8).pack(side=tk.LEFT)
        tk.Button(port_row, text="Apply", command=apply_udp).pack(side=tk.RIGHT)

    # PSK Reporter
    tk.Label(left, text="PSK Reporter", font=("", 10, "bold")).pack(
        anchor=tk.W, pady=(8, 0)
    )
    psk_enabled_var = tk.BooleanVar(value=False)

    def on_psk_toggle() -> None:
        enabled = psk_enabled_var.get()
        psk_fetcher.set_enabled(enabled)
        if enabled:
            psk_fetcher.start()
        else:
            psk_fetcher.stop()

    psk_chk = tk.Checkbutton(
        left,
        text="Enable PSK Reporter",
        variable=psk_enabled_var,
        command=on_psk_toggle,
        state=tk.DISABLED,
    )
    psk_chk.pack(fill=tk.X, pady=2)

    _psk_placeholder = "—  data —  next —"
    psk_status_frame = tk.Frame(left)
    psk_out_var = tk.StringVar(value="Out: " + _psk_placeholder)
    psk_in_var = tk.StringVar(value="In: " + _psk_placeholder)
    psk_call_var = tk.StringVar(value="Call: " + _psk_placeholder)
    psk_out_lbl = tk.Label(psk_status_frame, textvariable=psk_out_var, font=("", 8), anchor="w")
    psk_in_lbl = tk.Label(psk_status_frame, textvariable=psk_in_var, font=("", 8), anchor="w")
    psk_call_lbl = tk.Label(psk_status_frame, textvariable=psk_call_var, font=("", 8), anchor="w")
    psk_out_lbl.pack(fill=tk.X)
    psk_in_lbl.pack(fill=tk.X)
    psk_call_lbl.pack(fill=tk.X)
    psk_status_frame.pack(fill=tk.X, pady=1)

    trans_btn = tk.Button(
        left, text="Transparent (0.5)", command=toggle_transparency, font=("", 9),
    )
    trans_btn.pack(fill=tk.X, pady=(6, 0))

    def _format_psk_step(name: str, info: dict) -> str:
        last_ok = info.get("last_ok", 0)
        ok = info.get("ok")
        next_in = info.get("next_in", 0)
        active = info.get("active", False)
        if active:
            status = "⏳"
        elif ok is True:
            status = "✓"
        elif ok is False:
            status = "✗"
        else:
            status = "—"
        if last_ok > 0:
            age = int(time.time() - last_ok)
            if age < 60:
                age_s = f"{age}s ago"
            else:
                age_s = f"{age // 60}m{age % 60}s ago"
        else:
            age_s = "never"
        nxt = f"{int(next_in)}s" if next_in > 0 else ("now" if active else "—")
        return f"{name}: {status}  data {age_s}  next {nxt}"

    def update_psk_status() -> None:
        has_grid = bool(get_psk_grid())
        has_call = bool(get_psk_callsign())
        can_enable = has_grid and has_call
        if not can_enable:
            psk_chk.config(state=tk.DISABLED)
            if psk_enabled_var.get():
                psk_enabled_var.set(False)
                psk_fetcher.set_enabled(False)
                psk_fetcher.stop()
            psk_out_var.set("Out: " + _psk_placeholder)
            psk_in_var.set("In: " + _psk_placeholder)
            psk_call_var.set("Call: " + _psk_placeholder)
            return
        psk_chk.config(state=tk.NORMAL)
        if psk_enabled_var.get():
            st = psk_fetcher.get_status()
            psk_out_var.set(_format_psk_step("Out", st.get("out", {})))
            psk_in_var.set(_format_psk_step("In", st.get("in", {})))
            psk_call_var.set(_format_psk_step("Call", st.get("call", {})))
        else:
            psk_out_var.set("Out: " + _psk_placeholder)
            psk_in_var.set("In: " + _psk_placeholder)
            psk_call_var.set("Call: " + _psk_placeholder)

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
    next_refresh_var = tk.StringVar(value="—")
    tk.Label(band_bar, text="Next refresh:", font=("", 9), fg="#666").pack(
        side=tk.RIGHT, padx=(12, 0)
    )
    tk.Label(band_bar, textvariable=next_refresh_var, font=("", 9), fg="#666").pack(
        side=tk.RIGHT
    )

    last_jtdx_band: list[str | None] = [None]

    def update() -> None:
        now = time.time()
        connected = bool(udp_ref[0].last_message_time and (now - udp_ref[0].last_message_time) < 30)
        if connected:
            wsjt_status.set("● Connected")
            wsjt_detail.set(udp_ref[0].instance_id or "—")
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

        # Next refresh countdown (so user sees when data will refresh)
        sec = fetcher.get_seconds_until_next_refresh()
        next_refresh_var.set(f"{int(sec)}s")

        # Update radar from fetcher (15m + 3h trend layer)
        band = display_band_var.get() or "6m"
        data = fetcher.get_latest(band)
        data_3h = fetcher.get_latest_3h(band)
        b64 = data.get("data") if data else None
        w_start = data.get("window_start") if data else None
        w_end = data.get("window_end") if data else None
        if w_start is not None and w_end is not None:
            desc = datetime.utcfromtimestamp(w_start).strftime("%H:%M") + "~" + datetime.utcfromtimestamp(w_end).strftime("%H:%M") + "Z"
        else:
            desc = ""
        b64_3h = data_3h.get("data") if data_3h else None
        w_start_3h = data_3h.get("window_start") if data_3h else None
        w_end_3h = data_3h.get("window_end") if data_3h else None
        if w_start_3h is not None and w_end_3h is not None:
            desc_3h = datetime.utcfromtimestamp(w_start_3h).strftime("%H:%M") + "~" + datetime.utcfromtimestamp(w_end_3h).strftime("%H:%M") + "Z"
        else:
            desc_3h = ""
        psk_in, psk_out, psk_both = set(), set(), set()
        heard_me: set[int] = set()
        if psk_enabled_var.get():
            psk_in_f, psk_out_f, psk_both_f = psk_fetcher.get_psk_data(band)
            heard_me_f = psk_fetcher.get_heard_me(band)
            try:
                from gridcodec import field_index
                for name in psk_in_f:
                    idx = field_index(name)
                    if idx >= 0:
                        psk_in.add(idx)
                for name in psk_out_f:
                    idx = field_index(name)
                    if idx >= 0:
                        psk_out.add(idx)
                for name in psk_both_f:
                    idx = field_index(name)
                    if idx >= 0:
                        psk_both.add(idx)
                for name in heard_me_f:
                    idx = field_index(name)
                    if idx >= 0:
                        heard_me.add(idx)
            except Exception:
                pass
        radar.update_data(
            b64, band, desc,
            propagation_b64_3h=b64_3h,
            window_desc_3h=desc_3h,
            psk_in=psk_in,
            psk_out=psk_out,
            psk_both=psk_both,
            heard_me=heard_me,
        )

        update_psk_status()
        root.after(1000, update)

    root.after(500, update)

    def on_closing() -> None:
        fetcher.stop()
        psk_fetcher.stop()
        udp_ref[0].stop()
        reporter.shutdown()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()
