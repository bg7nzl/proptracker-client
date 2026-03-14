# FT8 Propagation Tracker — radar (polar) propagation view
from __future__ import annotations

import base64
import math
import os
import tkinter as tk

_here = os.path.dirname(os.path.abspath(__file__))
_src = os.path.dirname(_here)
_gc_path = os.path.join(_src, "gridcodec", "python")
if _gc_path not in __import__("sys").path:
    __import__("sys").path.insert(0, _gc_path)

from .grid_utils import field_center, haversine_km, initial_bearing

MAX_DISTANCE_KM = 20000
DISTANCE_RINGS = [5000, 10000, 15000, 20000]
DISTANCE_LABELS = ["5k", "10k", "15k", "20k km"]

# Legend and dot colors (distinct so legend is never grey)
COLOR_INCOMING = "#E04040"
COLOR_OUTGOING = "#4080E0"
COLOR_BOTH = "#20A020"
COLOR_GRID_BG = "#E8E8E8"
COLOR_RING = "#AAAAAA"
COLOR_RING_TEXT = "#888888"
DOT_RADIUS = 5
DOT_RADIUS_BOTH = 6

MARGIN_TOP = 18
MARGIN_BOTTOM = 40
MARGIN_SIDE = 24


class RadarView(tk.Canvas):
    """Polar (bearing-distance) radar canvas. Center = user field."""

    def __init__(self, parent, size: int = 400, **kwargs) -> None:
        super().__init__(parent, bg="white", highlightthickness=0, **kwargs)
        self._my_field: str | None = None
        self._my_lat = 0.0
        self._my_lon = 0.0
        self._dot_items: list[tuple[int, str, float, float, str]] = []
        self._tooltip_window: tk.Toplevel | None = None
        self._last_band = ""
        self._last_window_desc = ""
        self._last_b64: str | None = None
        self._last_counts = (0, 0, 0)
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Configure>", self._on_resize)

    def _calc_geometry(self) -> None:
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 10 or h < 10:
            w = h = 400
        usable_w = w - 2 * MARGIN_SIDE
        usable_h = h - MARGIN_TOP - MARGIN_BOTTOM
        diameter = min(usable_w, usable_h)
        self._radius = diameter / 2
        self._cx = w / 2
        self._cy = MARGIN_TOP + usable_h / 2

    def _on_resize(self, event=None) -> None:
        self._calc_geometry()
        self._redraw()

    def set_my_field(self, field: str) -> None:
        if not field or len(field) < 2:
            self._my_field = None
            return
        self._my_field = field.upper()[:2]
        self._my_lat, self._my_lon = field_center(self._my_field)

    def update_data(
        self,
        propagation_b64: str | None,
        band: str,
        window_desc: str,
    ) -> None:
        self._last_b64 = propagation_b64
        self._last_band = band
        self._last_window_desc = window_desc
        self._calc_geometry()
        self._redraw()

    def _redraw(self) -> None:
        self.delete("all")
        self._dot_items.clear()
        self._draw_background()

        band = self._last_band
        window_desc = self._last_window_desc
        propagation_b64 = self._last_b64

        if not self._my_field or not propagation_b64:
            self._draw_center_label()
            self._draw_legend(band, window_desc, 0, 0, 0)
            return

        n_in = n_out = n_both = 0
        try:
            from gridcodec import GridCodecMatrix, field_name

            raw = base64.b64decode(propagation_b64)
            matrix = GridCodecMatrix()
            matrix.decode(raw)

            outgoing = set(matrix.gc_from(self._my_field))
            incoming = set(matrix.gc_to(self._my_field))
            both = outgoing & incoming
            only_out = outgoing - both
            only_in = incoming - both

            for fi in only_in:
                self._draw_field_dot(fi, COLOR_INCOMING, DOT_RADIUS, "In")
            for fi in only_out:
                self._draw_field_dot(fi, COLOR_OUTGOING, DOT_RADIUS, "Out")
            for fi in both:
                self._draw_field_dot(fi, COLOR_BOTH, DOT_RADIUS_BOTH, "Both")

            n_in, n_out, n_both = len(only_in), len(only_out), len(both)
        except Exception:
            n_in = n_out = n_both = 0

        self._last_counts = (n_in, n_out, n_both)
        self._draw_center_label()
        self._draw_legend(band, window_desc, n_in, n_out, n_both)

    def _draw_background(self) -> None:
        for i, r_km in enumerate(DISTANCE_RINGS):
            frac = r_km / MAX_DISTANCE_KM
            r_px = self._radius * frac
            is_outer = (r_km == MAX_DISTANCE_KM)
            self.create_oval(
                self._cx - r_px,
                self._cy - r_px,
                self._cx + r_px,
                self._cy + r_px,
                outline=COLOR_RING,
                width=2 if is_outer else 1,
                dash=() if is_outer else (4, 2),
            )
            self.create_text(
                self._cx + 4,
                self._cy - r_px + 10,
                text=DISTANCE_LABELS[i],
                fill=COLOR_RING_TEXT,
                font=("", 7),
                anchor="w",
            )

        for deg in range(0, 360, 30):
            rad = math.radians(deg - 90)
            dx = self._radius * math.cos(rad)
            dy = self._radius * math.sin(rad)
            self.create_line(
                self._cx, self._cy,
                self._cx + dx, self._cy + dy,
                fill=COLOR_GRID_BG, width=1,
            )

        cardinals = {0: "N", 90: "E", 180: "S", 270: "W"}
        for deg in range(0, 360, 30):
            rad = math.radians(deg - 90)
            label_r = self._radius + 14
            x = self._cx + label_r * math.cos(rad)
            y = self._cy + label_r * math.sin(rad)
            label = cardinals.get(deg, str(deg))
            bold = deg in cardinals
            self.create_text(
                x, y, text=label, fill="#666" if bold else COLOR_RING_TEXT,
                font=("", 9, "bold") if bold else ("", 7),
            )

    def _draw_field_dot(
        self, field_idx: int, color: str, radius: int, type_label: str
    ) -> None:
        from gridcodec import field_name

        name = field_name(field_idx)
        if name == "??":
            return
        lat, lon = field_center(name)
        d_km = haversine_km(self._my_lat, self._my_lon, lat, lon)
        bearing = initial_bearing(self._my_lat, self._my_lon, lat, lon)
        if d_km > MAX_DISTANCE_KM:
            d_km = MAX_DISTANCE_KM
        scale = self._radius / MAX_DISTANCE_KM
        rad = math.radians(bearing - 90)
        x = self._cx + scale * d_km * math.cos(rad)
        y = self._cy + scale * d_km * math.sin(rad)
        item = self.create_oval(
            x - radius, y - radius,
            x + radius, y + radius,
            fill=color, outline=color, width=1,
        )
        self._dot_items.append((item, name, bearing, d_km, type_label))

    def _draw_center_label(self) -> None:
        if self._my_field:
            self.create_oval(
                self._cx - 6, self._cy - 6,
                self._cx + 6, self._cy + 6,
                fill="white", outline="black", width=2,
            )
            self.create_text(
                self._cx, self._cy + 18,
                text=self._my_field, font=("", 9, "bold"),
            )

    def _draw_legend(
        self, band: str, window_desc: str, n_in: int, n_out: int, n_both: int
    ) -> None:
        w = max(self.winfo_width() or 400, 320)
        y = self._cy + self._radius + 28
        # Fixed-width legend: same layout regardless of band/desc length
        radius = 6
        block_w = 80
        start_x = w / 2 - (3 * block_w) / 2
        for i, (color, label, count) in enumerate([
            (COLOR_INCOMING, "In", n_in),
            (COLOR_OUTGOING, "Out", n_out),
            (COLOR_BOTH, "Both", n_both),
        ]):
            cx = start_x + i * block_w + block_w / 2 - 6
            self.create_oval(
                cx - radius, y - radius, cx + radius, y + radius,
                fill=color, outline=color, width=2,
            )
            self.create_text(
                cx + radius + 4, y,
                text=f"{label}({count})", anchor="w", font=("", 9), fill="#333",
            )

        # Second line: band + window, fixed max width so layout doesn't jump
        band_str = (band or "—")[:6].ljust(6)
        desc_str = (window_desc or "")[:14]
        info = f"{band_str}  {desc_str}".strip()
        self.create_text(w / 2, y + 16, text=info, font=("", 8), fill="#888")

    def _on_motion(self, event) -> None:
        if not self._dot_items:
            return
        x, y = event.x, event.y
        best = None
        best_d = 1e9
        for item, name, bearing, d_km, type_label in self._dot_items:
            coords = self.coords(item)
            if len(coords) < 4:
                continue
            cx = (coords[0] + coords[2]) / 2
            cy = (coords[1] + coords[3]) / 2
            d = (x - cx) ** 2 + (y - cy) ** 2
            if d < 400 and d < best_d:
                best_d = d
                best = (name, bearing, d_km, type_label)
        if best:
            name, bearing, d_km, type_label = best
            text = f"{name}  Brg {bearing:.0f}°  Dist {d_km:.0f} km  {type_label}"
            if self._tooltip_window:
                try:
                    self._tooltip_window.destroy()
                except tk.TclError:
                    pass
            self._tooltip_window = tw = tk.Toplevel(self)
            tw.wm_overrideredirect(True)
            tw.wm_geometry(f"+{event.x_root + 12}+{event.y_root + 12}")
            tk.Label(
                tw, text=text, bg="#ffffcc", relief=tk.SOLID,
                borderwidth=1, font=("", 9),
            ).pack(padx=4, pady=2)
        else:
            self._on_leave(event)

    def _on_leave(self, event=None) -> None:
        if self._tooltip_window:
            try:
                self._tooltip_window.destroy()
            except tk.TclError:
                pass
            self._tooltip_window = None
