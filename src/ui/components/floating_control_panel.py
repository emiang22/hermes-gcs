from dash import html, dcc
import dash_mantine_components as dmc
from dash_iconify import DashIconify
from src.ui.app_layout import COLORS
from src.config import ROBOT_IP, CAMERA_PORT


# ────────────────────────── Mini control pad ──────────────────────────

def create_mini_control_pad():
    """D-pad style control buttons overlaid on camera feed - COMPACT SIZE"""
    grid_style = {
        "position": "absolute",
        "bottom": "6px",
        "right": "-10%",
        "transform": "translateX(-50%)",
        "display": "grid",
        "gridTemplateColumns": "28px 28px 28px",  # 50% smaller (was 50px)
        "gridTemplateRows": "28px 28px",
        "gap": "2px",
        "zIndex": "10",
    }

    arrows = {
        "forward": ("mdi:arrow-up-bold", "ArrowUp"),
        "left": ("mdi:arrow-left-bold", "ArrowLeft"),
        "backward": ("mdi:arrow-down-bold", "ArrowDown"),
        "right": ("mdi:arrow-right-bold", "ArrowRight"),
    }

    def arrow_btn(key):
        icon, data_key = arrows[key]
        return html.Button(
            DashIconify(icon=icon, width=14),  # Smaller icon (was 20)
            id={"type": "floating-nav", "index": key},
            className="floating-arrow-btn",
            **{"data-key": data_key},
        )

    return html.Div(
        id="floating-control-pad",
        style=grid_style,
        children=[
            html.Div(), arrow_btn("forward"), html.Div(),
            arrow_btn("left"), arrow_btn("backward"), arrow_btn("right"),
        ],
    )


# ────────────────────────── Camera mode buttons ──────────────────────────

def create_camera_mode_buttons(layout_type="normal"):
    """
    Camera mode selector buttons (RGB/IR/Thermal)
    
    Args:
        layout_type: "normal" or "compact" - ensures unique IDs for each layout
    """
    # (label, index, border_color, text_color, opacity, extra_class)
    modes = [
        ("RGB", "rgb", COLORS["accent_primary"], COLORS["text_primary"], 0.4, "cam-mode-active"),
        ("IR", "ir", COLORS["border"], COLORS["text_secondary"], 0.3, ""),
        ("🔥", "thermal", COLORS["border"], COLORS["text_secondary"], 0.3, ""),
    ]

    return html.Div(
        style={
            "position": "absolute",
            "bottom": "6px",
            "left": "6px",
            "display": "flex",
            "gap": "3px",
            "zIndex": "5",
        },
        children=[
            html.Button(
                label,
                id={"type": f"cam-mode-{layout_type}", "index": idx},
                className=f"cam-mode-btn-base cam-mode-btn {cls}".strip(),
                style={
                    "border": f"1px solid {border}",
                    "color": color,
                    "opacity": opacity,
                },
            )
            for label, idx, border, color, opacity, cls in modes
        ],
    )


# ────────────────────────── Utility buttons ──────────────────────────

def create_utility_buttons(orientation="vertical"):
    """
    Lights, speaker, and extra function buttons
    
    Args:
        orientation: "vertical" (stacked) or "horizontal" (row)
    """
    buttons = [
        ("mdi:lightbulb-on", "Lights", "floating-btn-lights", "yellow"),
        ("mdi:volume-high", "Speaker", "floating-btn-speaker", "cyan"),
        ("mdi:dots-horizontal", "Extra", "floating-btn-extra", "gray"),
    ]

    def btn(icon, label, id_, color):
        return dmc.Button(
            children=[
                DashIconify(icon=icon, width=16),
                html.Span(label, style={"marginLeft": "4px", "fontSize": "0.7rem"}),
            ],
            id=id_,
            color=color,
            variant="outline",
            size="xs",
            styles={"root": {"padding": "4px 8px", "height": "auto"}},
        )

    container_style = {
        "display": "flex",
        "gap": "4px",
        "padding": "4px",
    }
    
    if orientation == "vertical":
        container_style.update({
            "flexDirection": "column",
            "justifyContent": "flex-start",
            "alignItems": "stretch",
            "width": "90px",
        })
    else:
        container_style.update({
            "flexDirection": "row",
            "justifyContent": "flex-start",
            "alignItems": "center",
            "flexWrap": "wrap",
        })

    return html.Div(
        id="floating-utility-buttons",
        style=container_style,
        children=[btn(*b) for b in buttons],
    )


# ────────────────────────── Camera container ──────────────────────────

def create_camera_feed(feed_id):
    """Just the camera img element"""
    cam_src = f"http://{ROBOT_IP}:{CAMERA_PORT}/stream"
    
    return html.Img(
        id=feed_id,
        src=cam_src,
        style={
            "maxWidth": "100%",
            "maxHeight": "100%",
            "objectFit": "contain",
            "display": "block",
        },
        alt="Camera Feed",
    )


# ────────────────────────── Floating panel ──────────────────────────

def create_floating_panel():
    """
    Main floating panel component with:
    - Minimized icon (🎮) that can be dragged
    - Expandable window with camera feed and controls
    - Adaptive layout: horizontal (wide) or vertical (tall)
    """
    
    # ═══════════════════════════════════════════════════════════════
    # MINIMIZED ICON
    # ═══════════════════════════════════════════════════════════════
    minimized_icon = html.Div(
        id="floating-minimized-icon",
        className="floating-icon",
        title="Open Floating Controls",
        style={
            "position": "fixed",
            "bottom": "20px",
            "right": "20px",
            "width": "60px",
            "height": "60px",
            "borderRadius": "12px",
            "display": "flex",
            "alignItems": "center",
            "justifyContent": "center",
            "cursor": "grab",
            "fontSize": "2rem",
            "zIndex": "99998",
            "background": f"linear-gradient(135deg, {COLORS['bg_secondary']}, {COLORS['bg_tertiary']})",
            "border": f"2px solid {COLORS['accent_primary']}",
            "boxShadow": "0 4px 20px rgba(0,255,136,.3)",
            "transition": "opacity 0.3s ease, all 0.3s ease",  # ✅ CHANGED
            "opacity": "1",           # ✅ ADDED
            "pointerEvents": "auto",  # ✅ ADDED
        },
        children=DashIconify(icon="mdi:controller", width=24, color=COLORS["accent_primary"]),
    )

    # ═══════════════════════════════════════════════════════════════
    # TITLE BAR
    # ═══════════════════════════════════════════════════════════════
    title_bar = html.Div(
        id="floating-titlebar",
        className="floating-titlebar",
        style={
            "display": "flex",
            "justifyContent": "space-between",
            "alignItems": "center",
            "padding": "6px 10px",
            "cursor": "grab",
            "userSelect": "none",
            "borderBottom": f"1px solid {COLORS['border']}",
            "background": f"linear-gradient(90deg, {COLORS['bg_secondary']}, {COLORS['bg_primary']})",
            "flexShrink": 0,
        },
        children=[
            html.Div(
                style={"display": "flex", "gap": "6px", "alignItems": "center"},
                children=[
                    DashIconify(icon="mdi:controller", width=18, color=COLORS["accent_primary"]),
                    html.Span(
                        "REMOTE CONTROL",
                        style={
                            "fontFamily": "'Rajdhani', sans-serif",
                            "fontSize": "0.7rem",
                            "fontWeight": "600",
                            "letterSpacing": "1.5px",
                            "color": COLORS["text_primary"],
                        },
                    ),
                ],
            ),
            html.Button(
                "−",
                id="floating-minimize-btn",
                title="Minimize",
                style={
                    "background": "transparent",
                    "border": "none",
                    "fontSize": "1.3rem",
                    "cursor": "pointer",
                    "color": COLORS["text_secondary"],
                    "padding": "0 4px",
                    "lineHeight": "1",
                },
            ),
        ],
    )

    # ═══════════════════════════════════════════════════════════════
    # CONTENT AREA - Adaptive layout via CSS/JS
    # Camera + controls, aligned top-left
    # ═══════════════════════════════════════════════════════════════
    content_area = html.Div(
        id="floating-content",
        style={
            "flex": 1,
            "display": "flex",
            "padding": "6px",
            "gap": "6px",
            "overflow": "hidden",
            "alignItems": "flex-start",      # Top alignment
            "justifyContent": "flex-start",  # Left alignment
            # Default: horizontal layout (camera left, buttons right)
            "flexDirection": "row",
        },
        children=[
            # Camera container with overlays
            html.Div(
                id="floating-camera-container",
                style={
                    "position": "relative",
                    "background": COLORS["bg_primary"],
                    "borderRadius": "6px",
                    "overflow": "hidden",
                    "flex": "1 1 auto",
                    "minWidth": "150px",
                    "minHeight": "100px",
                    "maxHeight": "100%",
                    "display": "flex",
                    "alignItems": "flex-start",
                    "justifyContent": "flex-start",
                },
                children=[
                    create_camera_feed("floating-video-feed"),
                    create_camera_mode_buttons("normal"),
                    create_mini_control_pad(),
                ],
            ),
            # Utility buttons (right side in horizontal, bottom in vertical)
            html.Div(
                id="floating-buttons-container",
                style={
                    "flexShrink": 0,
                    "display": "flex",
                    "flexDirection": "column",
                    "gap": "4px",
                },
                children=[
                    create_utility_buttons("vertical"),
                ],
            ),
        ],
    )

    # ═══════════════════════════════════════════════════════════════
    # FLOATING WINDOW
    # ═══════════════════════════════════════════════════════════════
    floating_window = html.Div(
        id="floating-window",
        className="floating-window",
        style={
            "position": "fixed",
            "bottom": "20px",
            "right": "20px",
            "width": "480px",
            "height": "320px",
            "minWidth": "250px",
            "minHeight": "180px",
            "display": "flex",
            "flexDirection": "column",
            "resize": "both",
            "overflow": "hidden",
            "zIndex": "99999",
            "borderRadius": "10px",
            "background": f"linear-gradient(135deg, {COLORS['bg_secondary']}ee, {COLORS['bg_tertiary']}ee)",
            "border": f"2px solid {COLORS['accent_primary']}",
            "backdropFilter": "blur(10px)",
            "boxShadow": "0 8px 32px rgba(0, 0, 0, 0.4)",
            "opacity": "0",             # ✅ ADDED
            "pointerEvents": "none",    # ✅ ADDED
            "transition": "opacity 0.3s ease",  # ✅ ADDED
        },
        children=[title_bar, content_area],
    )

    # ═══════════════════════════════════════════════════════════════
    # STATE STORES
    # ═══════════════════════════════════════════════════════════════
    stores = [
        dcc.Store(
            id="floating-panel-state",
            data={
                "isOpen": False,
                "position": {"x": None, "y": None},
                "size": {"width": 380, "height": 320},
                "layout": "horizontal",  # or "vertical"
            },
        ),
        dcc.Store(id="floating-hidden-by-view", data=False),
        dcc.Store(id="floating-camera-mode", data="rgb"),
        dcc.Store(id="floating-keyboard-enabled", data=False),
    ]

    # ═══════════════════════════════════════════════════════════════
    # CONTAINER
    # ═══════════════════════════════════════════════════════════════
    return html.Div(
        id="floating-panel-container",
        children=[minimized_icon, floating_window] + stores,
    )