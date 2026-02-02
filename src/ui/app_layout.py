from dash import dcc, html, Dash
import dash_mantine_components as dmc
from dash_iconify import DashIconify
from src.config import CONFIG

# Theme Colors
COLORS = {
    "bg_primary": "#0a0f14",
    "bg_secondary": "#111920",
    "bg_tertiary": "#1a232d",
    "bg_card": "#151d26",
    "accent_primary": "#00ff88",
    "accent_secondary": "#00b4d8",
    "accent_warning": "#ffd60a",
    "accent_danger": "#ff4757",
    "accent_orange": "#ff6b35",
    "text_primary": "#e8eaed",
    "text_secondary": "#8b949e",
    "text_muted": "#5c6370",
    "border": "#2d3748",
    "grid": "#1e2832",
}

def create_header():
    return html.Div(style={
        "background": f"linear-gradient(90deg, {COLORS['bg_secondary']} 0%, {COLORS['bg_primary']} 100%)",
        "padding": "16px 24px",
        "display": "flex",
        "justifyContent": "space-between",
        "alignItems": "center",
        "borderBottom": f"1px solid {COLORS['border']}",
    }, children=[
        html.Div(style={"display": "flex", "alignItems": "center", "gap": "16px"}, children=[
            DashIconify(icon="mdi:robot-industrial", width=40, color=COLORS['accent_primary']),
            html.Div([
                html.H1("H.E.R.M.E.S. v2.0", style={ # Version changed to 2.0 per user request
                    "fontFamily": "'Orbitron', sans-serif", "fontSize": "1.5rem", "fontWeight": "800",
                    "color": COLORS['text_primary'], "margin": "0", "letterSpacing": "3px",
                }),
                html.Span("GROUND CONTROL STATION", style={
                    "fontFamily": "'Rajdhani', sans-serif", "fontSize": "0.7rem",
                    "color": COLORS['text_secondary'], "letterSpacing": "4px",
                }),
            ]),
        ]),
        html.Div(style={"display": "flex", "alignItems": "center", "gap": "24px"}, children=[
            html.Div(id="connection-status"),
            html.Div(id="alert-status"),
            html.Div(id="clock", style={
                "fontFamily": "'Orbitron', monospace", "fontSize": "1.25rem", "color": COLORS['accent_secondary'],
            }),
        ]),
    ])

def create_sidebar():
    nav_items = [
        ("teleop", "Teleoperación", "mdi:controller"),
        ("sensors", "Sensores", "mdi:chart-line"),
        ("gas-map", "Mapa de Gases", "mdi:map-marker-radius"),
        ("acoustic", "Acústica / IA", "mdi:waveform"),
        ("radar", "LIDAR / Radar", "mdi:radar"),
        ("logs", "Registros", "mdi:console"),
        ("replay", "Mission Replay", "mdi:rewind"), # New Item
    ]
    return html.Div(style={
        "width": "220px",
        "background": COLORS['bg_secondary'],
        "borderRight": f"1px solid {COLORS['border']}",
        "padding": "16px",
        "display": "flex",
        "flexDirection": "column",
        "gap": "8px",
    }, children=[
        html.Div(style={"marginBottom": "16px"}, children=[
            html.Span("CONTROL DE MISIÓN", style={
                "fontFamily": "'Rajdhani', sans-serif", "fontSize": "0.75rem",
                "color": COLORS['text_muted'], "letterSpacing": "2px",
            }),
        ]),
            *[html.Button([DashIconify(icon=icon, width=20), html.Span(label)],
                id={"type": "nav-btn", "index": view_id}, className="nav-button")
              for view_id, label, icon in nav_items],
            html.Div(style={"flex": "1"}),
        html.Div(className="gcs-card", style={"padding": "12px"}, children=[
            html.Div(style={"display": "flex", "justifyContent": "space-between", "marginBottom": "8px"}, children=[
                html.Span("Batería", className="metric-label"),
                html.Span(id="sidebar-battery", style={"color": COLORS['accent_primary'], "fontWeight": "600"}),
            ]),
            dmc.Progress(id="battery-progress", value=100, color="teal", size="sm", radius="xl"),
            html.Div(style={"display": "flex", "justifyContent": "space-between", "marginTop": "12px"}, children=[
                html.Span("Señal", className="metric-label"),
                html.Span(id="sidebar-rssi", style={"color": COLORS['accent_secondary'], "fontWeight": "600"}),
            ]),
            dmc.Progress(id="rssi-progress", value=80, color="cyan", size="sm", radius="xl"),
        ]),
    ])

def get_layout():
    return dmc.MantineProvider(
        html.Div(style={
            "minHeight": "100vh",
            "background": COLORS['bg_primary'],
            "color": COLORS['text_primary'],
            "display": "flex",
            "flexDirection": "column",
        }, children=[
            create_header(),
            html.Div(id="alert-banner-container"),
            html.Div(style={"display": "flex", "flex": "1", "overflow": "hidden"}, children=[
                create_sidebar(),
                html.Div(id="main-content", style={"flex": "1", "padding": "20px", "overflowY": "auto"}, children=[
                    html.Div(id="view-container")
                ]),
            ]),
            dcc.Interval(id="interval-fast", interval=500),
            dcc.Interval(id="interval-slow", interval=2000),
            dcc.Store(id="current-view", data="teleop"),
            
            # --- CONNECTION MODAL ---
            dmc.Modal(
                id="connection-modal",
                opened=True, # Open by default on load
                closeOnClickOutside=False,
                closeOnEscape=False,
                withCloseButton=False,
                centered=True,
                title=dmc.Title("Conexión Hermes GCS", order=3, style={"fontFamily": "'Orbitron'"}),
                children=[
                    dmc.Text("Ingrese las direcciones IP para conectar.", size="sm", color="dimmed", style={"marginBottom": 16}),
                    dmc.TextInput(id="input-broker-ip", label="MQTT Broker / Robot IP", value=CONFIG["mqtt_broker"], style={"marginBottom": 10}),
                    dmc.TextInput(id="input-camera-ip", label="Cámara IP (ESP32-CAM)", value=CONFIG.get("camera_ip", CONFIG["mqtt_broker"]), style={"marginBottom": 20}),
                    
                    dmc.Group(position="right", spacing="sm", children=[
                        dmc.Button("Modo Simulado", id="btn-simulate", variant="subtle", color="gray"),
                        dmc.Button("Conectar", id="btn-connect-system", color="teal"),
                    ])
                ]
            )
        ])
    )
