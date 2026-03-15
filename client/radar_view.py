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
# 3h layer: lighter shades for semi-transparent trend
COLOR_INCOMING_3H = "#F0A0A0"
COLOR_OUTGOING_3H = "#A0C0F0"
COLOR_BOTH_3H = "#80D080"
COLOR_GRID_BG = "#E8E8E8"
COLOR_RING = "#AAAAAA"
COLOR_RING_TEXT = "#888888"
DOT_RADIUS = 5
DOT_RADIUS_BOTH = 6
DOT_RADIUS_PSK = 3
COLOR_HEARD_ME = "#FFD700"

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
        self._last_window_desc_3h = ""
        self._last_b64: str | None = None
        self._last_b64_3h: str | None = None
        self._last_counts = (0, 0, 0)
        self._last_counts_3h = (0, 0, 0)
        self._last_psk_in: set[int] = set()
        self._last_psk_out: set[int] = set()
        self._last_psk_both: set[int] = set()
        self._last_heard_me: set[int] = set()
        self._legend_rects: list[tuple[float, float, float, str]] = []  # (cx, cy, hit_r, tooltip)
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
        propagation_b64_3h: str | None = None,
        window_desc_3h: str = "",
        *,
        psk_in: set[int] | None = None,
        psk_out: set[int] | None = None,
        psk_both: set[int] | None = None,
        heard_me: set[int] | None = None,
    ) -> None:
        self._last_b64 = propagation_b64
        self._last_b64_3h = propagation_b64_3h
        self._last_band = band
        self._last_window_desc = window_desc
        self._last_window_desc_3h = window_desc_3h
        self._last_psk_in = psk_in if psk_in is not None else set()
        self._last_psk_out = psk_out if psk_out is not None else set()
        self._last_psk_both = psk_both if psk_both is not None else set()
        self._last_heard_me = heard_me if heard_me is not None else set()
        self._calc_geometry()
        self._redraw()

    def _redraw(self) -> None:
        self.delete("all")
        self._dot_items.clear()
        self._draw_background()

        band = self._last_band
        window_desc = self._last_window_desc
        window_desc_3h = self._last_window_desc_3h
        propagation_b64 = self._last_b64
        propagation_b64_3h = self._last_b64_3h

        if not self._my_field:
            self._draw_center_label(None)
            self._draw_legend(band, window_desc, 0, 0, 0, 0, 0, 0)
            return

        n_in, n_out, n_both = 0, 0, 0
        n_in_3h, n_out_3h, n_both_3h = 0, 0, 0
        local_state: str | None = None
        try:
            from gridcodec import GridCodecMatrix, field_name, field_index

            my_fi = field_index(self._my_field) if self._my_field else -1

            # 1. PSK Reporter layer (small dots, bottom)
            for fi in self._last_psk_in:
                if fi != my_fi:
                    self._draw_field_dot(
                        fi, COLOR_INCOMING, DOT_RADIUS_PSK, "In (PSK)"
                    )
            for fi in self._last_psk_out:
                if fi != my_fi:
                    self._draw_field_dot(
                        fi, COLOR_OUTGOING, DOT_RADIUS_PSK, "Out (PSK)"
                    )
            for fi in self._last_psk_both:
                if fi != my_fi:
                    self._draw_field_dot(
                        fi, COLOR_BOTH, DOT_RADIUS_PSK + 1, "Both (PSK)"
                    )

            # 2. 3h layer (semi-transparent trend)
            if self._my_field and propagation_b64_3h:
                raw_3h = base64.b64decode(propagation_b64_3h)
                matrix_3h = GridCodecMatrix()
                matrix_3h.decode(raw_3h)
                out_3h = set(matrix_3h.gc_from(self._my_field))
                inc_3h = set(matrix_3h.gc_to(self._my_field))
                both_3h = out_3h & inc_3h
                only_out_3h = out_3h - both_3h
                only_in_3h = inc_3h - both_3h
                for fi in only_in_3h:
                    if fi == my_fi:
                        continue
                    self._draw_field_dot(fi, COLOR_INCOMING_3H, DOT_RADIUS - 1, "In", faded=True)
                for fi in only_out_3h:
                    if fi == my_fi:
                        continue
                    self._draw_field_dot(fi, COLOR_OUTGOING_3H, DOT_RADIUS - 1, "Out", faded=True)
                for fi in both_3h:
                    if fi == my_fi:
                        continue
                    self._draw_field_dot(fi, COLOR_BOTH_3H, DOT_RADIUS_BOTH - 1, "Both", faded=True)
                n_in_3h, n_out_3h, n_both_3h = len(only_in_3h), len(only_out_3h), len(both_3h)

            # Then 15min layer (full opacity on top)
            if not propagation_b64:
                self._last_counts = (n_in, n_out, n_both)
                self._last_counts_3h = (n_in_3h, n_out_3h, n_both_3h)
                self._draw_center_label(local_state)
                self._draw_legend(band, window_desc, n_in, n_out, n_both, n_in_3h, n_out_3h, n_both_3h)
                return

            raw = base64.b64decode(propagation_b64)
            matrix = GridCodecMatrix()
            matrix.decode(raw)
            outgoing = set(matrix.gc_from(self._my_field))
            incoming = set(matrix.gc_to(self._my_field))
            both = outgoing & incoming
            only_out = outgoing - both
            only_in = incoming - both
            if my_fi in both:
                local_state = "both"
            elif my_fi in only_in:
                local_state = "in"
            elif my_fi in only_out:
                local_state = "out"

            for fi in only_in:
                if fi == my_fi:
                    continue
                self._draw_field_dot(fi, COLOR_INCOMING, DOT_RADIUS, "In")
            for fi in only_out:
                if fi == my_fi:
                    continue
                self._draw_field_dot(fi, COLOR_OUTGOING, DOT_RADIUS, "Out")
            for fi in both:
                if fi == my_fi:
                    continue
                self._draw_field_dot(fi, COLOR_BOTH, DOT_RADIUS_BOTH, "Both")
            n_in, n_out, n_both = len(only_in), len(only_out), len(both)

            # 5. Who heard me (yellow stars, top)
            for fi in self._last_heard_me:
                if fi != my_fi:
                    self._draw_field_star(fi)
        except Exception:
            n_in = n_out = n_both = 0
            n_in_3h = n_out_3h = n_both_3h = 0
            local_state = None

        self._last_counts = (n_in, n_out, n_both)
        self._last_counts_3h = (n_in_3h, n_out_3h, n_both_3h)
        self._draw_center_label(local_state)
        self._draw_legend(band, window_desc, n_in, n_out, n_both, n_in_3h, n_out_3h, n_both_3h)

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
        self,
        field_idx: int,
        color: str,
        radius: int,
        type_label: str,
        faded: bool = False,
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
        opts = {"fill": color, "outline": color, "width": 1}
        if faded:
            opts["stipple"] = "gray50"
        item = self.create_oval(
            x - radius, y - radius,
            x + radius, y + radius,
            **opts,
        )
        self._dot_items.append((item, name, bearing, d_km, type_label))

    def _draw_field_star(self, field_idx: int) -> None:
        """Draw yellow 5-pointed star at field position (who heard me)."""
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
        # 5-pointed star: outer R=7, inner r=3 (canvas y down, angle 90° = up)
        R, r = 7, 3
        points: list[float] = []
        for i in range(5):
            deg_outer = 90 - i * 72
            deg_inner = 90 - (i + 0.5) * 72
            for rad_pt, radius in (
                (math.radians(deg_outer), R),
                (math.radians(deg_inner), r),
            ):
                points.append(x + radius * math.cos(rad_pt))
                points.append(y - radius * math.sin(rad_pt))
        self.create_polygon(
            points,
            fill=COLOR_HEARD_ME,
            outline="#CC9900",
            width=1,
        )

    def _draw_center_label(self, local_state: str | None = None) -> None:
        if self._my_field:
            if local_state == "both":
                fill = COLOR_BOTH
            elif local_state == "in":
                fill = COLOR_INCOMING
            elif local_state == "out":
                fill = COLOR_OUTGOING
            else:
                fill = "white"
            self.create_oval(
                self._cx - 6, self._cy - 6,
                self._cx + 6, self._cy + 6,
                fill=fill, outline="black", width=2,
            )
            self.create_text(
                self._cx, self._cy + 18,
                text=self._my_field, font=("", 9, "bold"),
            )

    # Legend hover tooltips (English)
    _LEGEND_TOOLTIPS = (
        ("In", "I can receive from them"),
        ("Out", "They can receive from me"),
        ("Both", "QSO possible"),
    )

    def _draw_legend(
        self,
        band: str,
        window_desc: str,
        n_in: int,
        n_out: int,
        n_both: int,
        n_in_3h: int = 0,
        n_out_3h: int = 0,
        n_both_3h: int = 0,
    ) -> None:
        w = max(self.winfo_width() or 400, 320)
        h = max(self.winfo_height() or 400, 300)
        circle_bottom = self._cy + self._radius
        self._legend_rects.clear()

        # ── Left bottom corner: In/Out/Both color legend ──
        lx = MARGIN_SIDE + 4
        ly = circle_bottom + 6
        radius = 5
        hit_r = 16
        for i, (color, label, count) in enumerate([
            (COLOR_INCOMING, "In", n_in),
            (COLOR_OUTGOING, "Out", n_out),
            (COLOR_BOTH, "Both", n_both),
        ]):
            row_y = ly + i * 14
            self.create_oval(
                lx - radius, row_y - radius, lx + radius, row_y + radius,
                fill=color, outline=color, width=2,
            )
            self.create_text(
                lx + radius + 4, row_y,
                text=f"{label}({count})", anchor="w", font=("", 8), fill="#333",
            )
            _, tip = self._LEGEND_TOOLTIPS[i]
            self._legend_rects.append((lx, row_y, hit_r, tip))
        # 3h counts below
        if n_in_3h or n_out_3h or n_both_3h or self._last_window_desc_3h:
            line3 = self._last_window_desc_3h or "3h"
            if n_in_3h or n_out_3h or n_both_3h:
                line3 += f" In({n_in_3h}) Out({n_out_3h}) Both({n_both_3h})"
            self.create_text(
                lx, ly + 3 * 14 + 2, text=line3, anchor="w",
                font=("", 7), fill="#999",
            )

        # ── Right bottom corner: PSK / band / time info ──
        rx = w - MARGIN_SIDE - 4
        ry = circle_bottom + 6
        self.create_text(
            rx, ry, anchor="e",
            text="● Large = our network",
            font=("", 7), fill="#666",
        )
        self.create_text(
            rx, ry + 12, anchor="e",
            text="· Small = PSK Reporter",
            font=("", 7), fill="#666",
        )
        self.create_text(
            rx, ry + 24, anchor="e",
            text="★ = who heard me",
            font=("", 7), fill="#666",
        )
        band_str = (band or "—")[:6]
        desc_str = (window_desc or "")[:14]
        info = f"{band_str}  {desc_str}".strip()
        self.create_text(
            rx, ry + 40, anchor="e",
            text=info, font=("", 8), fill="#888",
        )

    def _on_motion(self, event) -> None:
        x, y = event.x, event.y
        # Legend hover: show English explanation for In/Out/Both
        for cx, cy, hit_r, tooltip in self._legend_rects:
            if (x - cx) ** 2 + (y - cy) ** 2 <= hit_r * hit_r:
                if self._tooltip_window:
                    try:
                        self._tooltip_window.destroy()
                    except tk.TclError:
                        pass
                self._tooltip_window = tw = tk.Toplevel(self)
                tw.wm_overrideredirect(True)
                tw.wm_geometry(f"+{event.x_root + 12}+{event.y_root + 12}")
                tk.Label(
                    tw, text=tooltip, bg="#ffffcc", relief=tk.SOLID,
                    borderwidth=1, font=("", 9),
                ).pack(padx=4, pady=2)
                return
        if not self._dot_items:
            self._on_leave(event)
            return
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
