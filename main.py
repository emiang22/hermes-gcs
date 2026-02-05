import dash
from dash import dcc, html, Input, Output, State, ALL, callback_context
import dash_mantine_components as dmc
from dash_iconify import DashIconify
import threading
import cv2
import flask
import datetime
import numpy as np
import plotly.graph_objects as go
import math
import requests

try:
    from scipy.interpolate import griddata
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    print("WARNING: scipy not installed. Gas heatmap interpolation will be basic.")

# Import internal modules
from src.config import CONFIG, CAMERA_PORT, ROBOT_IP
from src.state import state, db_manager # db_manager starts automatically
from src.services.mqtt import start_mqtt, publish_command
from src.services.replay import replay_service
from src.services.simulation import start_simulation
from src.ui.app_layout import get_layout, COLORS
from src.ui.views.teleop import view_teleop
from src.ui.views.sensors import view_sensors
from src.ui.views.gas_map import view_gas_map
from src.ui.views.acoustic import view_acoustic
from src.ui.views.radar import view_radar
from src.ui.views.logs import view_logs
from src.ui.views.replay import view_replay

# Initialize App
app = dash.Dash(
    __name__,
    title="H.E.R.M.E.S. GCS",
    update_title=None,
    suppress_callback_exceptions=True,
    external_stylesheets=[
        "https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Orbitron:wght@400;500;600;700;800;900&family=Rajdhani:wght@400;500;600;700&display=swap"
    ]
)

app.layout = get_layout()

# ═══════════════════════════════════════════════════════════════════════════════
# WEBCAM SERVER (Simulation Mode)
# ═══════════════════════════════════════════════════════════════════════════════
def gen_frames():
    # Use CAP_DSHOW for better compatibility on Windows
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        state.log("Error: No se pudo abrir la cámara local para simulación", "ERROR")
        return

    try:
        while True:
            success, frame = cap.read()
            if not success:
                state.log("Error: Fallo al leer frame de cámara local", "ERROR")
                break
            else:
                cv2.putText(frame, "SIMULATION MODE - LOCAL CAMERA", (10, 30), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 136), 2)
                ret, buffer = cv2.imencode('.jpg', frame)
                frame = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
    finally:
        cap.release()

@app.server.route('/video_feed_local')
def video_feed_local():
    return flask.Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

# ═══════════════════════════════════════════════════════════════════════════════
# NAVIGATION CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════════
@app.callback(
    [Output("view-container", "children"), Output("current-view", "data")],
    [Input({"type": "nav-btn", "index": ALL}, "n_clicks")],
    [State("current-view", "data")]
)
def navigate(clicks, current_view):
    ctx = callback_context
    if not ctx.triggered or not any(c for c in clicks if c):
         # Default view
         return view_teleop(), "teleop"
         
    triggered_id = ctx.triggered[0]["prop_id"]
    try:
        import ast
        id_dict = ast.literal_eval(triggered_id.split(".")[0])
        view_id = id_dict["index"]
    except:
        view_id = "teleop"

    content = {
        "teleop": view_teleop,
        "sensors": view_sensors,
        "gas-map": view_gas_map,
        "acoustic": view_acoustic,
        "radar": view_radar,
        "logs": view_logs,
        "replay": view_replay
    }.get(view_id, view_teleop)()
    
    return content, view_id

# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL UI UPDATES
# ═══════════════════════════════════════════════════════════════════════════════
@app.callback(
    [Output("clock", "children"), Output("connection-status", "children"), Output("alert-status", "children"),
     Output("sidebar-battery", "children"), Output("battery-progress", "value"),
     Output("sidebar-rssi", "children"), Output("rssi-progress", "value"),
     Output("alert-banner-container", "children")],
    [Input("interval-fast", "n_intervals")]
)
def fast_update_global(n):
    clock = datetime.datetime.now().strftime("%H:%M:%S")
    
    conn_status = state.status["connection"]
    conn_class = "status-online" if conn_status == "ONLINE" else "status-warning" if conn_status in ["SIMULATED", "REPLAY FILE"] else ""
    connection_indicator = html.Div(style={"display": "flex", "alignItems": "center"}, children=[
        html.Span(className=f"status-indicator {conn_class}"),
        html.Span(conn_status, style={"fontFamily": "'Rajdhani', sans-serif", "fontSize": "0.875rem"}),
    ])
    
    alert_level = state.status["alert_level"]
    alert_color = {"NORMAL": COLORS['accent_primary'], "WARNING": COLORS['accent_warning'], "CRITICAL": COLORS['accent_danger']}.get(alert_level, COLORS['text_secondary'])
    alert_indicator = html.Span(alert_level, style={"color": alert_color, "fontFamily": "'Rajdhani', sans-serif", "fontWeight": "600"})
    
    battery_pct = state.current_values["battery_percent"]
    rssi = state.current_values["rssi"]
    rssi_pct = max(0, min(100, (rssi + 90) * 2))
    
    alert_banner = None
    if alert_level == "CRITICAL":
        alert_banner = html.Div(className="alert-banner alert-critical", children=[
            DashIconify(icon="mdi:alert-circle", width=24),
            html.Span("¡ALERTA CRÍTICA! Niveles de gas peligrosos"),
        ])
    
    return (clock, connection_indicator, alert_indicator, f"{battery_pct}%", battery_pct, 
            f"{rssi} dBm", rssi_pct, alert_banner)

# Callbacks for Connection Modal
@app.callback(
    Output("connection-modal", "opened"),
    Input("btn-connect-system", "n_clicks"),
    Input("btn-reopen-modal", "n_clicks"),
    State("input-broker-ip", "value"),
    State("input-camera-ip", "value"),
    prevent_initial_call=True
)
def handle_connection(n_connect, n_reopen, broker_ip, camera_ip):
    ctx = dash.callback_context
    if not ctx.triggered: return dash.no_update
    btn_id = ctx.triggered[0]["prop_id"].split(".")[0]
    
    if btn_id == "btn-reopen-modal":
        return True
    
    if btn_id == "btn-reopen-modal":
        return True
        
    if btn_id == "btn-connect-system":
        if not broker_ip: return dash.no_update
        state.log(f"Conectando a {broker_ip}...", "INFO")
        state.status["connection"] = "CONNECTING..."
        state.status["mode"] = "CONNECTING"
        
        # Update Runtime Config
        CONFIG["mqtt_broker"] = broker_ip
        CONFIG["camera_ip"] = camera_ip if camera_ip else broker_ip
        
        # Actually start MQTT now
        threading.Thread(target=lambda: start_mqtt(broker_ip), daemon=True).start()
        
        return False
    
    return dash.no_update

# ═══════════════════════════════════════════════════════════════════════════════
# REPLAY CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════════
@app.callback(
    Output("replay-status-text", "children"),
    [Input("btn-replay-play", "n_clicks"), Input("btn-replay-pause", "n_clicks"), 
     Input("btn-replay-stop", "n_clicks"), Input("btn-replay-load", "n_clicks")],
    prevent_initial_call=True
)
def control_replay(play, pause, stop, load):
    ctx = callback_context
    if not ctx.triggered: return dash.no_update
    btn_id = ctx.triggered[0]["prop_id"].split(".")[0]
    
    if btn_id == "btn-replay-play":
        replay_service.start_replay()
        return "▶️ Reproduciendo misión..."
    elif btn_id == "btn-replay-pause":
        replay_service.toggle_pause()
        return "⏸️ Pausado."
    elif btn_id == "btn-replay-stop":
        replay_service.stop_replay()
        return "⏹️ Detenido."
    elif btn_id == "btn-replay-load":
        if replay_service.load_mission_data():
            return "✅ Datos cargados. Listo para reproducir."
        else:
            return "❌ Error al cargar datos. Verifique DB."
    return ""

@app.callback(
    [Output("replay-progress", "value"), Output("replay-time-current", "children"), 
     Output("replay-time-total", "children")],
    [Input("interval-slow", "n_intervals")],
    prevent_initial_call=True
)
def update_replay_progress(n):
    return replay_service.progress, replay_service.current_time_str, replay_service.total_time_str

# ═══════════════════════════════════════════════════════════════════════════════
# SENSOR GRAPHS CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════════
@app.callback(
    [Output("graph-gas-history", "figure"), Output("graph-environment", "figure"), Output("graph-power", "figure")],
    [Input("interval-slow", "n_intervals")],
    prevent_initial_call=True
)
def update_sensor_graphs(n):
    # Check if elements exist (only update if view is active)
    # Actually, Output elements must exist in layout for callback to work, 
    # but since they are dynamic, Dash might complain if we don't handle it or suppress_callback_exceptions=True (which is set)
    # But if they are not in DOM, this callback might fire and do nothing or error.
    # With 'suppress_callback_exceptions=True', Dash handles missing outputs gracefully usually.
    
    layout_common = dict(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                         margin=dict(l=40, r=20, t=20, b=40), font=dict(family="JetBrains Mono", size=10),
                         xaxis=dict(showgrid=True, gridcolor=COLORS['grid']))
    
    fig_gas = go.Figure()
    fig_gas.add_trace(go.Scatter(y=list(state.ppm), name="MQ-2", line=dict(color=COLORS['accent_orange'], width=2), fill='tozeroy', fillcolor="rgba(255, 107, 53, 0.2)"))
    fig_gas.add_trace(go.Scatter(y=list(state.co2), name="CO₂", line=dict(color=COLORS['accent_primary'], width=2), yaxis="y2"))
    fig_gas.update_layout(**layout_common, yaxis=dict(title="MQ-2 (ppm)", showgrid=True, gridcolor=COLORS['grid']),
                          yaxis2=dict(title="CO₂ (ppm)", overlaying="y", side="right"), showlegend=True,
                          legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    
    fig_env = go.Figure()
    fig_env.add_trace(go.Scatter(y=list(state.temperature), name="Temp", line=dict(color=COLORS['accent_warning'], width=2)))
    fig_env.add_trace(go.Scatter(y=list(state.humidity), name="Humedad", line=dict(color=COLORS['accent_secondary'], width=2), yaxis="y2"))
    fig_env.update_layout(**layout_common, yaxis=dict(title="°C", showgrid=True, gridcolor=COLORS['grid']),
                          yaxis2=dict(title="%", overlaying="y", side="right"),
                          legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    
    fig_power = go.Figure()
    fig_power.add_trace(go.Scatter(y=list(state.voltage), name="V", line=dict(color=COLORS['accent_primary'], width=2)))
    fig_power.add_trace(go.Scatter(y=list(state.current_draw), name="A", line=dict(color=COLORS['accent_secondary'], width=2), yaxis="y2"))
    fig_power.update_layout(**layout_common, yaxis=dict(title="V", showgrid=True, gridcolor=COLORS['grid'], range=[9, 13]),
                            yaxis2=dict(title="A", overlaying="y", side="right"),
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                            
    return fig_gas, fig_env, fig_power

@app.callback(
    Output("sensor-stats", "children"),
    [Input("interval-slow", "n_intervals")],
    prevent_initial_call=True
)
def update_sensor_statistics(n):
    if not state.ppm:
        return html.Div("Recopilando datos...", style={"color": COLORS['text_muted']})
    
    def calc_stats(data, unit=""):
        if not data: return "N/A"
        return f"{min(data):.1f} / {sum(data)/len(data):.1f} / {max(data):.1f} {unit}"

    return html.Div([
        html.Div([html.Span("MQ-2 (Min/Avg/Max):", style={"color": COLORS['text_secondary']}), 
                  html.Span(calc_stats(list(state.ppm), "ppm"), style={"float": "right", "color": COLORS['accent_primary']})]),
        html.Div([html.Span("Temp (Min/Avg/Max):", style={"color": COLORS['text_secondary']}), 
                  html.Span(calc_stats(list(state.temperature), "°C"), style={"float": "right", "color": COLORS['accent_warning']})]),
        html.Div([html.Span("Volt (Min/Avg/Max):", style={"color": COLORS['text_secondary']}), 
                  html.Span(calc_stats(list(state.voltage), "V"), style={"float": "right", "color": COLORS['accent_secondary']})]),
    ], style={"display": "flex", "flexDirection": "column", "gap": "8px", "fontFamily": "monospace", "fontSize": "0.8rem"})

# ═══════════════════════════════════════════════════════════════════════════════
# ROBOT CONTROL
# ═══════════════════════════════════════════════════════════════════════════════

@app.callback(Output("btn-stop", "n_clicks"),
    [Input("btn-forward", "n_clicks"), Input("btn-backward", "n_clicks"),
     Input("btn-left", "n_clicks"), Input("btn-right", "n_clicks")],
    prevent_initial_call=True)
def control_robot(*args):
    if state.status["mode"] in ["SIMULACIÓN", "REPLAY", "REPLAY FILE"]:
        return dash.no_update
    ctx = callback_context
    if not ctx.triggered:
        return dash.no_update
    btn = ctx.triggered[0]['prop_id'].split('.')[0]
    cmd = {"btn-forward": "FORWARD", "btn-backward": "BACKWARD", "btn-left": "LEFT", "btn-right": "RIGHT"}.get(btn, "STOP")
    state.log(f"Comando enviado: {cmd}")
    publish_command("hermes/control", {"command": cmd})
    return dash.no_update

@app.callback(
    Output("led-status-text", "children"),
    [Input("led-intensity-slider", "value")],
    prevent_initial_call=True
)
def update_led_intensity(value):
    if state.status["mode"] != "MQTT":
         return f"Intensidad: {value} (Simulado)"
         
    publish_command("hermes/control", {"command": "LED", "val": value})
    return f"Intensidad: {value} (Enviado)"

# ═══════════════════════════════════════════════════════════════════════════════
# GAS MAP & ADVANCED VISUALIZATION
# ═══════════════════════════════════════════════════════════════════════════════
@app.callback(
    [Output("gas-heatmap", "figure"), Output("robot-position-display", "children"),
     Output("current-ppm-reading", "children"), Output("gas-map-stats", "children")],
    [Input("interval-slow", "n_intervals"), Input("map-view-mode", "value")],
    [State("show-grid", "checked"), State("show-heatmap", "checked"), State("show-path", "checked")],
    prevent_initial_call=True
)
def update_gas_map(n, view_mode, show_grid, show_heatmap, show_path):
    fig = go.Figure()
    map_size = 50
    rx, ry, rt = state.robot_position["x"], state.robot_position["y"], state.robot_position["theta"]
    
    # Intelligently cache grid calculation
    current_count = len(state.gas_map_points)
    zi = None
    
    if current_count > 3 and SCIPY_AVAILABLE:
        if state.cached_zi is not None and current_count == state.last_heatmap_count:
            zi = state.cached_zi
        else:
            try:
                points = state.gas_map_points[-500:]
                x, y, z = [p["x"] for p in points], [p["y"] for p in points], [p["ppm"] for p in points]
                xi, yi = np.meshgrid(np.linspace(0, map_size, 40), np.linspace(0, map_size, 40))
                zi = griddata((x, y), z, (xi, yi), method='cubic', fill_value=300)
                zi = np.clip(zi, 200, 10000)
                state.cached_zi = zi
                state.last_heatmap_count = current_count
            except Exception:
                pass

    if view_mode == "3d":
        if zi is not None:
                fig.add_trace(go.Surface(z=zi, x=np.linspace(0, map_size, 40), y=np.linspace(0, map_size, 40),
                    colorscale=[[0, COLORS['accent_primary']], [0.3, COLORS['accent_warning']], [1, COLORS['accent_danger']]],
                    showscale=False, opacity=0.9, uid="terrain_surface"))
        
        fig.add_trace(go.Scatter3d(x=[rx], y=[ry], z=[state.current_values["ppm"] + 100], 
                                   mode='markers', marker=dict(size=10, color=COLORS['accent_primary']), showlegend=False, uid="robot_marker_3d"))

        fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            uirevision='3d_mode', # Keeps camera state ONLY while in 3D mode
            margin=dict(l=0, r=0, t=0, b=0),
            scene=dict(xaxis=dict(range=[0, map_size], title="X"), yaxis=dict(range=[0, map_size], title="Y"), zaxis=dict(range=[0, 10000], title="PPM"), aspectmode='cube'))
            
    else: # 2D Mode
        if show_heatmap and zi is not None:
                fig.add_trace(go.Heatmap(z=zi, x=np.linspace(0, map_size, 40), y=np.linspace(0, map_size, 40),
                    colorscale=[[0, COLORS['accent_primary']], [0.3, COLORS['accent_warning']], [1, COLORS['accent_danger']]],
                    showscale=False, opacity=0.7, uid="heatmap_2d"))
        
        if show_path and len(state.robot_path) > 1:
            path = list(state.robot_path)
            fig.add_trace(go.Scatter(x=[p[0] for p in path], y=[p[1] for p in path], mode='lines',
                line=dict(color=COLORS['accent_secondary'], width=2, dash='dot'), showlegend=False, uid="path_trace"))
        
        # Robot Triangle (pointing forward)
        size = 1.5
        # Use 2*pi/3 (~120°) for equilateral triangle pointing in direction of theta
        angles = [rt, rt + math.pi * 2/3, rt - math.pi * 2/3]
        fig.add_trace(go.Scatter(x=[rx + size * math.cos(a) for a in angles] + [rx + size * math.cos(rt)],
            y=[ry + size * math.sin(a) for a in angles] + [ry + size * math.sin(rt)],
            mode='lines', fill='toself', fillcolor=COLORS['accent_primary'],
            line=dict(color=COLORS['accent_primary'], width=2), showlegend=False, uid="robot_triangle"))
        
        fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor=COLORS['bg_tertiary'],
            uirevision='2d_mode', # Keeps zoom state ONLY while in 2D mode
            margin=dict(l=40, r=20, t=20, b=40),
            xaxis=dict(range=[0, map_size], showgrid=show_grid, gridcolor=COLORS['grid']),
            yaxis=dict(range=[0, map_size], showgrid=show_grid, gridcolor=COLORS['grid']))
    
    # Stats
    num_points = len(state.gas_map_points)
    max_ppm = max((p["ppm"] for p in state.gas_map_points), default=0)
    avg_ppm = sum(p["ppm"] for p in state.gas_map_points) / num_points if num_points else 0
    stats = html.Div([
        html.Div(f"Puntos: {num_points} | Max: {max_ppm:.0f}", style={"color": COLORS['text_secondary']}),
        html.Div(f"Avg: {avg_ppm:.0f} ppm", style={"color": COLORS['accent_warning']})
    ])
    
    return fig, f"X: {rx:.1f}m, Y: {ry:.1f}m", str(int(state.current_values["ppm"])), stats

@app.callback(Output("btn-clear-gas-map", "n_clicks"), [Input("btn-clear-gas-map", "n_clicks")], prevent_initial_call=True)
def clear_gas_map(n):
    if n:
        state.gas_map_points = []
        state.robot_path.clear()
        state.log("Datos del mapa de gases limpiados", "INFO")
    return None

# ═══════════════════════════════════════════════════════════════════════════════
# ACOUSTIC & RADAR & LOGS
# ═══════════════════════════════════════════════════════════════════════════════
@app.callback(
    [Output("acoustic-current-class", "children"), Output("acoustic-confidence", "children"),
     Output("acoustic-direction", "children"), Output("acoustic-count", "children"),
     Output("graph-audio-confidence", "figure"), Output("graph-audio-classes", "figure"),
     Output("acoustic-detection-log", "children")],
    [Input("interval-slow", "n_intervals")],
    prevent_initial_call=True
)
def update_acoustic(n):
    # Safely access first detection's direction
    direction = "N/A"
    if state.acoustic_detections:
        first_detection = state.acoustic_detections[0]
        if first_detection.get('direction') is not None:
            direction = f"{first_detection['direction']:.0f}°"
    
    count = sum(1 for d in state.acoustic_detections if d.get("class") in ["SCREAM", "BREATHING", "VOICE", "GLASS_BREAK"])
    
    fig_conf = go.Figure()
    fig_conf.add_trace(go.Scatter(y=list(state.audio_confidence), fill='tozeroy',
        line=dict(color=COLORS['accent_secondary'], width=2), fillcolor="rgba(0, 180, 216, 0.3)"))
    fig_conf.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=40, r=20, t=20, b=40), yaxis=dict(range=[0, 100], title="Confianza (%)", showgrid=True, gridcolor=COLORS['grid']))
    
    class_counts = {}
    for d in state.acoustic_detections:
        class_counts[d["class"]] = class_counts.get(d["class"], 0) + 1
    fig_classes = go.Figure(go.Pie(labels=list(class_counts.keys()), values=list(class_counts.values()), hole=0.5,
        marker=dict(colors=[COLORS['accent_primary'], COLORS['accent_secondary'], COLORS['accent_warning'], COLORS['accent_danger'], COLORS['accent_orange']]))) if class_counts else go.Figure()
    fig_classes.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=20, r=20, t=20, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=-0.1))
    
    log_entries = [html.Div(style={"padding": "4px 8px", "borderLeft": f"2px solid {COLORS['accent_danger']}",
        "marginBottom": "4px", "background": COLORS['bg_tertiary']}, children=[
        html.Span(f"[{d['timestamp'].strftime('%H:%M:%S')}] ", style={"color": COLORS['text_muted']}),
        html.Span(d['class'], style={"color": COLORS['accent_danger'], "fontWeight": "600"}),
        html.Span(f" ({d['confidence']:.0f}%)", style={"color": COLORS['text_secondary']})
    ]) for d in list(state.acoustic_detections)[:20]]
    
    return (state.status["audio_class"], f"{state.status['audio_confidence']:.0f}%", direction, str(count),
            fig_conf, fig_classes, log_entries)

@app.callback(
    [Output("graph-radar", "figure"), Output("radar-min-distance", "children"),
     Output("radar-min-angle", "children"), Output("obstacle-count", "children")],
    [Input("interval-fast", "n_intervals")],
    [State("radar-range", "value")],
    prevent_initial_call=True
)
def update_radar(n, max_range):
    # Default max_range if None
    max_range = max_range or 5
    distances, angles = state.radar_distances, state.radar_angles
    min_idx = np.argmin(distances)
    min_dist, min_angle = distances[min_idx], angles[min_idx]
    
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(r=distances, theta=angles, fill='toself',
        fillcolor="rgba(0, 255, 136, 0.3)", line=dict(color=COLORS['accent_primary'], width=2), name='Scan'))
    fig.add_trace(go.Scatterpolar(r=[min_dist], theta=[min_angle], mode='markers',
        marker=dict(size=12, color=COLORS['accent_danger'], symbol='x'), name='Más Cercano'))
    
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
        polar=dict(radialaxis=dict(range=[0, max_range], showgrid=True, gridcolor=COLORS['grid']),
                   angularaxis=dict(showgrid=True, gridcolor=COLORS['grid'])),
        showlegend=False, margin=dict(l=40, r=40, t=40, b=40))
    
    obstacles = sum(1 for d in distances if d < max_range * 0.6)
    
    return fig, f"{min_dist:.2f}", f"Ángulo: {min_angle:.0f}°", str(obstacles)

@app.callback(Output("log-container", "children"), [Input("interval-fast", "n_intervals")], prevent_initial_call=True)
def update_logs(n):
    return [html.Div(log, className="log-entry") for log in list(state.logs)[:50]]

@app.callback(Output("btn-clear-logs", "n_clicks"), [Input("btn-clear-logs", "n_clicks")], prevent_initial_call=True)
def clear_logs(n):
    if n:
        state.logs.clear()
        state.log("Registros limpiados", "INFO")
    return None

@app.callback(
    Output("btn-export-logs", "n_clicks"),
    [Input("btn-export-logs", "n_clicks")],
    prevent_initial_call=True
)
def export_logs(n):
    if n:
        try:
            import os
            logs_content = "\n".join(list(state.logs))
            filename = f"hermes_logs_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            filepath = os.path.join(os.getcwd(), filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"H.E.R.M.E.S. GCS - Log Export\n")
                f.write(f"Fecha: {datetime.datetime.now().isoformat()}\n")
                f.write("=" * 50 + "\n\n")
                f.write(logs_content)
            state.log(f"Logs exportados a: {filename}", "SUCCESS")
        except Exception as e:
            state.log(f"Error exportando logs: {e}", "ERROR")
    return None

# ═══════════════════════════════════════════════════════════════════════════════
# SENSOR VIEW SPECIFIC CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════════
@app.callback(
    [Output("sensor-ppm", "children"), Output("sensor-co2", "children"),
     Output("sensor-temp", "children"), Output("sensor-humidity", "children"),
     Output("sensor-voltage", "children"), Output("sensor-current", "children")],
    [Input("interval-fast", "n_intervals")],
    prevent_initial_call=True
)
def update_sensor_cards(n):
    return (
        str(int(state.current_values["ppm"])),
        str(int(state.current_values["co2"])),
        f"{state.current_values['temperature']:.1f}",
        f"{state.current_values['humidity']:.1f}",
        f"{state.current_values['voltage']:.2f}",
        f"{state.current_values['current']:.2f}"
    )

# ═══════════════════════════════════════════════════════════════════════════════
# TELEOP SPECIFIC CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════════
@app.callback(
    [Output("audio-class-display", "children"), Output("audio-confidence-bar", "value"),
     Output("teleop-ppm", "children"), Output("teleop-co2", "children"),
     Output("teleop-temp", "children"), Output("teleop-voltage", "children")],
     [Input("interval-fast", "n_intervals")],
     prevent_initial_call=True
)
def update_teleop_metrics(n):
    return (state.status["audio_class"], state.status["audio_confidence"],
            str(int(state.current_values["ppm"])), str(int(state.current_values["co2"])),
            f"{state.current_values['temperature']:.1f}", f"{state.current_values['voltage']:.2f}")

@app.callback(
    Output("video-feed", "src"), 
    [Input("interval-slow", "n_intervals")], 
    [State("video-feed", "src")],
    prevent_initial_call=True
)
def update_video_source(n, current_src):
    is_sim = state.status["mode"] == "SIMULATED"
    # Use CONFIG dictionary to get current IPs instead of stale constants
    target_ip = CONFIG.get("camera_ip", CONFIG.get("mqtt_broker", "127.0.0.1"))
    target_src = "/video_feed_local" if is_sim else f"http://{target_ip}:{CAMERA_PORT}/stream"
    if current_src != target_src:
        return target_src
    return dash.no_update

# ═══════════════════════════════════════════════════════════════════════════════
# FLOATING CONTROL PANEL CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────────────────
# 2. VIEW-BASED VISIBILITY (MODIFIED FOR OPACITY)
# ─────────────────────────────────────────────────────────────────────────────
@app.callback(
    [Output("floating-minimized-icon", "style", allow_duplicate=True),
     Output("floating-window", "style", allow_duplicate=True),
     Output("floating-hidden-by-view", "data")],
    [Input("current-view", "data")],
    [State("floating-panel-state", "data"),
     State("floating-minimized-icon", "style"),
     State("floating-window", "style")],
    prevent_initial_call=True
)
def handle_view_change(current_view, panel_state, icon_style, window_style):
    """Show/hide floating panel based on current view"""
    icon_style = icon_style or {}
    window_style = window_style or {}
    
    if current_view == "teleop":
        # Hide both with opacity
        icon_style["opacity"] = "0"
        icon_style["pointerEvents"] = "none"
        window_style["opacity"] = "0"
        window_style["pointerEvents"] = "none"
        return icon_style, window_style, True
    else:
        # Show the appropriate one (JavaScript handles which)
        icon_style.pop("opacity", None)
        icon_style.pop("pointerEvents", None)
        window_style.pop("opacity", None)
        window_style.pop("pointerEvents", None)
        return icon_style, window_style, False


# ─────────────────────────────────────────────────────────────────────────────
# 3. ROBOT CONTROL FROM FLOATING PANEL
# ─────────────────────────────────────────────────────────────────────────────
@app.callback(
    Output({"type": "floating-nav", "index": ALL}, "className"),
    [Input({"type": "floating-nav", "index": ALL}, "n_clicks")],
    prevent_initial_call=True
)
def control_robot_from_floating(clicks):
    """Handle robot movement commands from floating panel buttons"""
    ctx = callback_context
    num_buttons = len(clicks) if clicks else 4
    default_classes = ["floating-arrow-btn"] * num_buttons
    
    if not ctx.triggered or not any(c for c in clicks if c):
        return default_classes
    
    triggered_id = ctx.triggered[0]["prop_id"]
    try:
        import ast
        id_dict = ast.literal_eval(triggered_id.split(".")[0])
        direction = id_dict["index"]
    except:
        return default_classes
    
    if state.status["mode"] in ["SIMULACIÓN", "REPLAY", "REPLAY FILE"]:
        state.log(f"Control ignorado: {direction} (modo simulación/replay)", "WARN")
        return default_classes
    
    cmd = {
        "forward": "FORWARD",
        "backward": "BACKWARD",
        "left": "LEFT",
        "right": "RIGHT"
    }.get(direction, "STOP")
    
    state.log(f"Comando flotante: {cmd}")
    
    try:
        threading.Thread(
            target=lambda: requests.get(
                f"http://{ROBOT_IP}/control?var=move&val={cmd.lower()}",
                timeout=0.5
            ),
            daemon=True
        ).start()
    except Exception as e:
        state.log(f"Error enviando comando: {e}", "ERROR")
    
    return default_classes


# ─────────────────────────────────────────────────────────────────────────────
# 4. CAMERA MODE SWITCHING (simplified - only normal layout now)
# ─────────────────────────────────────────────────────────────────────────────
@app.callback(
    [Output({"type": "cam-mode-normal", "index": ALL}, "style"),
     Output({"type": "cam-mode-normal", "index": ALL}, "className"),
     Output("floating-camera-mode", "data")],
    [Input({"type": "cam-mode-normal", "index": ALL}, "n_clicks")],
    [State("floating-camera-mode", "data")],
    prevent_initial_call=True
)
def switch_camera_mode(clicks, current_mode):
    """Switch between RGB, IR, and Thermal camera modes"""
    ctx = callback_context
    
    if not ctx.triggered or not any(c for c in clicks if c):
        return (dash.no_update,) * 3
    
    triggered_id = ctx.triggered[0]["prop_id"]
    try:
        import ast
        id_dict = ast.literal_eval(triggered_id.split(".")[0])
        new_mode = id_dict["index"]
    except:
        return (dash.no_update,) * 3
    
    modes = ["rgb", "ir", "thermal"]
    styles = []
    classes = []
    
    for mode in modes:
        is_active = (mode == new_mode)
        style = {
            "border": f"1px solid {COLORS['accent_primary'] if is_active else COLORS['border']}",
            "color": COLORS['text_primary'] if is_active else COLORS['text_secondary'],
            "opacity": "0.4" if is_active else "0.3",
        }
        classname = "cam-mode-btn-base cam-mode-btn cam-mode-active" if is_active else "cam-mode-btn-base cam-mode-btn"
        
        styles.append(style)
        classes.append(classname)
    
    state.log(f"Modo de cámara: {new_mode.upper()}", "INFO")
    
    return styles, classes, new_mode


# ─────────────────────────────────────────────────────────────────────────────
# 5. UPDATE VIDEO FEED
# ─────────────────────────────────────────────────────────────────────────────
@app.callback(
    Output("floating-video-feed", "src"),
    [Input("interval-slow", "n_intervals")],
    [State("floating-video-feed", "src")],
    prevent_initial_call=True
)
def update_floating_video_source(n, current_src):
    """Update video source based on connection mode"""
    is_sim = state.status["mode"] in ["SIMULACIÓN", "REPLAY FILE", "ESPERANDO"]
    target_src = "/video_feed_local" if is_sim else f"http://{ROBOT_IP}:{CAMERA_PORT}/stream"
    
    if current_src != target_src:
        return target_src
    return dash.no_update


# ─────────────────────────────────────────────────────────────────────────────
# 6. UTILITY BUTTONS
# ─────────────────────────────────────────────────────────────────────────────
@app.callback(
    Output("floating-btn-lights", "children", allow_duplicate=True),
    [Input("floating-btn-lights", "n_clicks")],
    prevent_initial_call=True
)
def floating_toggle_lights(n):
    if not n:
        return dash.no_update
    
    if state.status["mode"] != "MQTT":
        state.log("Luces alternadas (simulado)", "INFO")
        return dash.no_update
    
    state.log("Luces alternadas", "INFO")
    return dash.no_update


@app.callback(
    Output("floating-btn-speaker", "children", allow_duplicate=True),
    [Input("floating-btn-speaker", "n_clicks")],
    prevent_initial_call=True
)
def floating_activate_speaker(n):
    if not n:
        return dash.no_update
    
    if state.status["mode"] != "MQTT":
        state.log("Bocina activada (simulado)", "INFO")
        return dash.no_update
    
    state.log("Bocina activada", "INFO")
    return dash.no_update


@app.callback(
    Output("floating-btn-extra", "children", allow_duplicate=True),
    [Input("floating-btn-extra", "n_clicks")],
    prevent_initial_call=True
)
def floating_extra_function(n):
    if not n:
        return dash.no_update
    
    state.log("Función extra (TBD)", "INFO")
    return dash.no_update


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN EXECUTION
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Removed auto-start of MQTT to wait for user input
    # if CONFIG["mqtt_broker"]:
    #     threading.Thread(target=start_mqtt, daemon=True).start()
    
    print("H.E.R.M.E.S. Ground Control Station v2.0 (Modular) Starting...")
    print("Waiting for Connection Modal input...")
    app.run(debug=True, port=8050)
