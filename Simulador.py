# *********************************************************************************************
# Escuela Superior de Innovación y tecnologia. El Salvador.                                   *
# Tecnico superior en Servicios de computación en la nube.                                    *
# Fecha de desarrollo: Diciembre 2025.                                                        *
# Para proyecto NUBE VERDE                                                                    *
# GRUPO: 6                                                                                    *
# Descripción: Simulador de datos de consumo energético para múltiples puntos de medición,    *
# con capacidad de envío a Google Firestore.tanto en tiempo real como en modo acelerado.      *
# Creado por: Tec. René Mauricio Góchez Chicas.                                               *
# Versión: 4.3.0                                                                              *
# Modificaciones:                                                                             *
#                se ajusto los parametros y la forma de ver en pantallas                      *
# Apoyo de GEMINI para edicion y correcciones y GEMINI para estructura, funciones y clases.   *
#                                                                                             *
# # NOTA: Requiere instalar firebase-admin y tener las credenciales adecuadas.                *
# *********************************************************************************************
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, simpledialog
import json
import random
import time
import threading
import os

from datetime import datetime, timedelta
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud import storage
import requests  # Para autenticación vía REST API
# --- CONFIGURACIÓN GLOBAL ---
#  Configuración del proyecto
# --- FIREBASE ---

FIREBASE_CONFIG = {
    "apiKey": "AIzaSyAE_pViacv5LR9DpalknyS5nuu-TJcTsxw",
    "authDomain": "nube-verde-monitor.firebaseapp.com",
    "projectId": "nube-verde-monitor",
    "storageBucket": "nube-verde-monitor.firebasestorage.app",
    "messagingSenderId": "694437356246",
    "appId": "1:694437356246:web:0b6792fd2a913727739f77",
    "databaseURL": "https://nube-verde-monitor.firebaseio.com" 
}


COLECCION_FIRESTORE = 'lecturas'
BUCKET_NAME = 'nube-verde-monitor.appspot.com'
FILE_SENT = 'datos_enviados.json'
FILE_UNSENT = 'datos_no_enviados.json'
FILE_ACCEL_OUTPUT = 'salida_acelerada.json'
FILE_USERS = 'usuarios.json'

PUNTOS_ID = [f"N{i}" for i in range(1, 13)]
MESES = {1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
         7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"}

# --- ESTILOS VISUALES ---
def aplicar_tema(root):
    style = ttk.Style(root)
    style.theme_use('clam')
    bg_color = "#121212"
    fg_color = "#00FF41"
    accent_color = "#008F11"
    root.configure(bg=bg_color)
    style.configure(".", background=bg_color, foreground=fg_color, fieldbackground="black", font=("Consolas", 10))
    style.configure("TLabel", background=bg_color, foreground=fg_color)
    style.configure("TButton", background="#222", foreground=fg_color)
    style.map("TButton", background=[('active', accent_color)], foreground=[('active', 'black')])
    style.configure("TEntry", fieldbackground="#000", foreground=fg_color, insertcolor=fg_color)
    style.configure("TNotebook", background=bg_color)
    style.configure("TNotebook.Tab", background="#222", foreground="#888")
    style.map("TNotebook.Tab", background=[('selected', accent_color)], foreground=[('selected', 'black')])
    style.configure("Treeview", background="black", foreground=fg_color, fieldbackground="black")
    style.configure("Treeview.Heading", background="#222", foreground=fg_color)
    return bg_color, fg_color

# --- MOTOR DE SIMULACIÓN ---
class SimulationEngine:
    def __init__(self, log_callback):
        self.log = log_callback
        self.db = self.init_firestore()
        self.storage_client = self.init_storage()
        self.running = False
        self.config = {}
        self.session_file = None
        self.session_data = []
        self.init_default_config()

    def init_default_config(self):
        default_params = {"metodo": "rango", "min": 10, "max": 100, "constante": 50, "prob": 80, "estado": "activo"}
        for pid in PUNTOS_ID:
            self.config[pid] = {h: default_params.copy() for h in range(24)}

    def init_firestore(self):
        if not firebase_admin._apps:
            try:
                # Inicialización usando Application Default Credentials (ADC) o configuración de entorno
                firebase_admin.initialize_app()
                return firestore.client()
            except Exception as e:
                self.log(f"OFFLINE: {e}")
                return None
        return firestore.client()

    def init_storage(self):
        try:
            return storage.Client()
        except Exception as e:
            self.log(f"STORAGE ERROR: {e}")
            return None

    def get_formatted_date(self, dt_obj):
        mes = MESES[dt_obj.month]
        am_pm = "a.m." if dt_obj.hour < 12 else "p.m."
        hora_12 = dt_obj.strftime("%I:%M:%S").lstrip("0")
        return f"{dt_obj.day} de {mes} de {dt_obj.year} a las {hora_12} {am_pm} UTC-6"

    def simular_valor(self, pid, current_hour):
        cfg = self.config[pid][int(current_hour) % 24]
        if cfg["estado"] == "inactivo": return 0
        metodo = cfg["metodo"]
        if metodo == "constante": return float(cfg["constante"])
        elif metodo == "rango": return round(random.uniform(cfg["min"], cfg["max"]), 2)
        elif metodo == "probabilistico":
            return round(random.uniform(0, cfg["max"]), 2) if random.uniform(0, 100) <= cfg["prob"] else 0
        return 0

    def guardar_en_archivo(self, data_batch):
        try:
            self.session_data.extend(data_batch)
            with open(self.session_file, 'w', encoding='utf-8') as f:
                json.dump(self.session_data, f, indent=4, ensure_ascii=False)
            self.log(f"💾 Guardado lote en {self.session_file}")
            return True
        except Exception as e:
            self.log(f"❌ ERROR ARCHIVO: {e}")
            return False

    def enviar_datos(self, data_batch):
        if not self.db: return False
        try:
            batch = self.db.batch()
            for item in data_batch:
                doc_ref = self.db.collection(COLECCION_FIRESTORE).document()
                batch.set(doc_ref, item)
            batch.commit()
            self.log(f"⚡ Enviado lote de {len(data_batch)} registros.")
            return True
        except Exception as e:
            self.log(f"❌ FALLO CONEXIÓN: {e}")
            return False

# --- INTERFAZ DE LOGIN (AJUSTADA PARA FIREBASE) ---
class LoginWindow:
    def __init__(self, root, on_success):
        self.root = root
        self.on_success = on_success
        self.root.title("ACCESO NUBE VERDE")
        self.root.geometry("400x350")
        aplicar_tema(self.root)

        # Centrar ventana en pantalla
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')
        
        frame = ttk.Frame(root, padding=20)
        frame.pack(expand=True)

        ttk.Label(frame, text="SISTEMA MONITOR NUBE VERDE", font=("Consolas", 12, "bold")).pack(pady=10)
        
        ttk.Label(frame, text="Correo Electrónico:").pack(anchor="w")
        self.user_entry = ttk.Entry(frame, width=35)
        self.user_entry.insert(0, "esit@nubeverde.local") # Sugerencia por defecto
        self.user_entry.pack(pady=5)
        
        ttk.Label(frame, text="Contraseña:").pack(anchor="w")
        self.pass_entry = ttk.Entry(frame, width=35, show="*")
        self.pass_entry.insert(0, "3s1tgrupo06") # Sugerencia por defecto
        self.pass_entry.pack(pady=5)
        
        self.btn_login = ttk.Button(frame, text="VERIFICAR CREDENCIALES", command=self.check_login)
        self.btn_login.pack(pady=20, fill="x")
        
        self.lbl_status = ttk.Label(frame, text="Esperando validación...", font=("Consolas", 8))
        self.lbl_status.pack()

    def check_login(self):
        email = self.user_entry.get()
        password = self.pass_entry.get()
        
        self.lbl_status.config(text="Conectando con Firebase...", foreground="yellow")
        self.root.update()

        try:
            # Autenticación usando la REST API oficial de Firebase
            auth_url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_CONFIG['apiKey']}"
            payload = {
                "email": email,
                "password": password,
                "returnSecureToken": True
            }
            response = requests.post(auth_url, json=payload)
            data = response.json()

            if "error" in data:
                raise Exception(data["error"]["message"])

            messagebox.showinfo("Éxito", "Token validado correctamente.")
            self.on_success()
        except Exception as e:
            self.lbl_status.config(text="Error de autenticación", foreground="red")
            messagebox.showerror("Acceso Denegado", "Usuario o contraseña de Firebase incorrectos.")

# --- APP PRINCIPAL ---
# (Se mantiene la lógica del simulador que ya tenías optimizada)
class SimulatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("⚡ CONTROL MASTER - NUBE VERDE ⚡")
        self.root.geometry("1000x750")
        aplicar_tema(self.root)
        
        self.engine = SimulationEngine(self.log_message)
        self.stop_event = threading.Event()
        self.intervalo_minutos = tk.IntVar(value=1)
        self.horas_aceleradas = tk.IntVar(value=1)
        self.sort_descending = True  # Por defecto descendente
        self.setup_ui()
        
        # Capturar el evento de cierre de la ventana (X de la barra superior)
        self.root.protocol("WM_DELETE_WINDOW", self.confirm_exit)

    def log_message(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_area.config(state='normal')
        self.log_area.insert(tk.END, f"> [{ts}] {msg}\n")
        self.log_area.see(tk.END)
        self.log_area.config(state='disabled')

    def setup_ui(self):
        tab_control = ttk.Notebook(self.root)
        self.tab_main = ttk.Frame(tab_control)
        self.tab_logs = ttk.Frame(tab_control)
        tab_control.add(self.tab_main, text='[ EJECUCIÓN ]')
        tab_control.add(self.tab_logs, text='[ LOGS ]')
        tab_control.pack(expand=1, fill="both", side="top")

        # --- Panel Superior: Control General ---
        top_frame = ttk.Frame(self.tab_main)
        top_frame.pack(fill="x", padx=10, pady=5)

        # Botones de Control
        btn_frame = ttk.LabelFrame(top_frame, text=" Control Maestro ")
        btn_frame.pack(pady=10)

        ttk.Label(btn_frame, text="Mín:").pack(side="left", padx=2)
        self.min_val = ttk.Entry(btn_frame, width=8)
        self.min_val.insert(0, "10")
        self.min_val.pack(side="left", padx=5)

        ttk.Label(btn_frame, text="Máx:").pack(side="left", padx=2)
        self.max_val = ttk.Entry(btn_frame, width=8)
        self.max_val.insert(0, "100")
        self.max_val.pack(side="left", padx=5)

        ttk.Label(btn_frame, text="Destino:").pack(side="left", padx=2)
        self.dest_var = tk.StringVar(value="ARCHIVO")
        self.combo_dest = ttk.Combobox(btn_frame, textvariable=self.dest_var, values=["ARCHIVO", "DB"], width=10, state="readonly")
        self.combo_dest.pack(side="left", padx=5)

        ttk.Label(btn_frame, text="Intervalo (min):").pack(side="left", padx=2)
        self.spin_intervalo = ttk.Spinbox(btn_frame, from_=1, to=60, textvariable=self.intervalo_minutos, width=5)
        self.spin_intervalo.pack(side="left", padx=5)

        # --- Botón Acelerado ---
        accel_frame = ttk.LabelFrame(top_frame, text=" Simulación Acelerada (Histórica) ")
        accel_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(accel_frame, text="Generar próximas:").pack(side="left", padx=5)
        ttk.Spinbox(accel_frame, from_=1, to=24, textvariable=self.horas_aceleradas, width=5).pack(side="left", padx=5)
        ttk.Label(accel_frame, text="horas").pack(side="left", padx=5)
        ttk.Button(accel_frame, text="⚡ GENERAR RÁPIDO", command=self.run_accelerated).pack(side="left", padx=20)

        # Indicador de estado
        self.lbl_status_led = ttk.Label(btn_frame, text=" ● ", foreground="red", font=("Consolas", 52))
        self.lbl_status_led.pack(side="left", padx=5)

        self.btn_start = ttk.Button(btn_frame, text="▶ INICIAR SIMULACIÓN", command=self.start_simulation)
        self.btn_start.pack(side="left", padx=10)
        self.btn_stop = ttk.Button(btn_frame, text="⏹ PARAR", command=self.stop_simulation, state="disabled")
        self.btn_stop.pack(side="left", padx=10)

        # Botón Salir
        self.btn_exit = ttk.Button(btn_frame, text="✖ SALIR", command=self.confirm_exit)
        self.btn_exit.pack(side="left", padx=10)

        # --- Panel Central: Configuración Individual ---
        config_frame = ttk.LabelFrame(self.tab_main, text=" Configuración por Punto de Medición ")
        config_frame.pack(fill="x", padx=10, pady=5)

        for col_idx in range(18): # 6 puntos * 3 columnas cada uno
            config_frame.columnconfigure(col_idx, weight=1)

        self.individual_configs = {}
        for i, pid in enumerate(PUNTOS_ID):
            row = 0 if i < 6 else 2 # Fila 0 para los primeros 6, Fila 2 para los siguientes (deja Fila 1 libre)
            col = (i % 6) * 3
            ttk.Label(config_frame, text=f"{pid}:").grid(row=row, column=col, padx=2, pady=5, sticky="e")
            
            min_ent = ttk.Entry(config_frame, width=8)
            min_ent.insert(0, "10")
            min_ent.grid(row=row, column=col+1, padx=2, pady=5, sticky="w")
            
            max_ent = ttk.Entry(config_frame, width=8)
            max_ent.insert(0, "100")
            max_ent.grid(row=row, column=col+2, padx=2, pady=5, sticky="w")
            
            self.individual_configs[pid] = {"min": min_ent, "max": max_ent}

        # Botones de acción masiva
        bulk_frame = ttk.Frame(self.tab_main)
        bulk_frame.pack(fill="x", padx=10)
        ttk.Button(bulk_frame, text="APLICAR A TODOS", command=self.apply_master_to_all).pack(side="left", padx=5)
        ttk.Button(bulk_frame, text="RESETEAR TODOS", command=self.reset_all_to_master).pack(side="left", padx=5)

        # --- Panel Inferior: Tabla ---
        tree_frame = ttk.Frame(self.tab_main)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.monitor_tree = ttk.Treeview(tree_frame, columns=("ID", "Valor", "Hora"), show="headings")
        self.monitor_tree.heading("ID", text="PUNTO", command=lambda: self.sort_column("ID", False))
        self.monitor_tree.heading("Valor", text="kWh")
        self.monitor_tree.heading("Hora", text="FECHA ▼", command=lambda: self.sort_column("Hora", None))
        
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.monitor_tree.yview)
        self.monitor_tree.configure(yscrollcommand=scrollbar.set)
        
        self.monitor_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # --- Panel de Control Inferior (Filtros y Ordenamiento) ---
        filter_frame = ttk.Frame(self.tab_main)
        filter_frame.pack(fill="x", padx=10, pady=0, side="bottom")
        
        ttk.Button(filter_frame, text="APLICAR FILTRO", command=self.apply_filter).pack(side="right", padx=5)
        self.filter_var = tk.StringVar(value="TODOS")
        combo_filter = ttk.Combobox(filter_frame, textvariable=self.filter_var, values=["TODOS"] + PUNTOS_ID, state="readonly", width=15)
        combo_filter.pack(side="right", padx=5)
        ttk.Label(filter_frame, text="Filtrar vista:").pack(side="right", padx=5)

        # Botones de ordenamiento (Movidos al fondo)
        sort_frame = ttk.Frame(filter_frame)
        sort_frame.pack(side="left")
        ttk.Label(sort_frame, text="Ordenar por:").pack(side="left", padx=5)
        ttk.Button(sort_frame, text="PUNTO (ID)", command=lambda: self.sort_column("ID", False)).pack(side="left", padx=2)
        ttk.Button(sort_frame, text="GENERACIÓN (FECHA)", command=lambda: self.sort_column("Hora", True)).pack(side="left", padx=2)

        self.log_area = scrolledtext.ScrolledText(self.tab_logs, state='disabled', bg="black", fg="#00FF41")
        self.log_area.pack(fill="both", expand=True)

    def confirm_exit(self):
        if messagebox.askokcancel("Confirmar Salida", "¿Desea cerrar el simulador?"):
            self.stop_event.set()
            # Asegurar que los datos en memoria se guarden antes de cerrar
            if self.engine.session_file and self.engine.session_data:
                try:
                    self.engine.guardar_en_archivo([])
                except: pass
            self.root.destroy()

    def validate_ranges(self):
        errores = []
        m_min = self.min_val.get()
        m_max = self.max_val.get()
        
        for pid, entries in self.individual_configs.items():
            try:
                v_min = float(entries["min"].get())
                v_max = float(entries["max"].get())
                
                if v_min < 0 or v_max < 0 or v_min > 10000 or v_max > 10000 or v_min > v_max:
                    raise ValueError
            except ValueError:
                errores.append(pid)
                entries["min"].delete(0, tk.END)
                entries["min"].insert(0, m_min)
                entries["max"].delete(0, tk.END)
                entries["max"].insert(0, m_max)
        return errores

    def apply_master_to_all(self):
        m_min = self.min_val.get()
        m_max = self.max_val.get()
        for pid in self.individual_configs:
            self.individual_configs[pid]["min"].delete(0, tk.END)
            self.individual_configs[pid]["min"].insert(0, m_min)
            self.individual_configs[pid]["max"].delete(0, tk.END)
            self.individual_configs[pid]["max"].insert(0, m_max)
        self.log_message("Valores maestros aplicados a todos los puntos.")

    def reset_all_to_master(self):
        self.min_val.delete(0, tk.END); self.min_val.insert(0, "10")
        self.max_val.delete(0, tk.END); self.max_val.insert(0, "100")
        self.apply_master_to_all()
        self.log_message("Reinicio total a valores de fábrica (10-100).")

    def start_simulation(self):
        errores = self.validate_ranges()
        if errores:
            msg = "Valores inválidos detectados (negativos, >10000 o texto).\n"
            msg += f"Se resetearon los puntos: {', '.join(errores)} a valores maestros."
            messagebox.showerror("Error de Validación", msg)
            self.log_message(f"⚠️ Error en: {', '.join(errores)}. Reseteados.")
            return

        # Configurar archivo de sesión si no existe
        if not self.engine.session_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.engine.session_file = f"simulacion_{timestamp}.json"
            self.engine.session_data = []

        self.stop_event.clear()
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.min_val.config(state="disabled")
        self.max_val.config(state="disabled")
        self.spin_intervalo.config(state="disabled")
        self.combo_dest.config(state="disabled")
        self.lbl_status_led.config(foreground="#00FF41") # Verde
        threading.Thread(target=self.run_process, daemon=True).start()

    def stop_simulation(self):
        self.stop_event.set()
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.min_val.config(state="normal")
        self.max_val.config(state="normal")
        self.spin_intervalo.config(state="normal")
        self.combo_dest.config(state="readonly")
        self.lbl_status_led.config(foreground="red")

    def run_process(self):
        while not self.stop_event.is_set():
            batch = []
            now = datetime.now()
            for pid in PUNTOS_ID:
                try:
                    v_min = float(self.individual_configs[pid]["min"].get())
                    v_max = float(self.individual_configs[pid]["max"].get())
                except:
                    v_min, v_max = 10, 100

                cfg = self.engine.config[pid][now.hour % 24]
                
                # Usar los valores individuales de la UI
                val = round(random.uniform(v_min, v_max), 2) if cfg["estado"] != "inactivo" else 0
                
                batch.append({
                    "id_punto": pid, 
                    "consumo_kwh": val, 
                    "fecha": self.engine.get_formatted_date(now),
                    "timestamp": now.isoformat()
                })
            
            if self.dest_var.get() == "DB":
                self.engine.enviar_datos(batch)
            else:
                self.engine.guardar_en_archivo(batch)

            self.root.after(0, self.update_table, batch)
            time.sleep(self.intervalo_minutos.get() * 60)

    def run_accelerated(self):
        horas = self.horas_aceleradas.get()
        intervalo = self.intervalo_minutos.get()
        total_minutos = horas * 60
        total_pasos = max(1, total_minutos // intervalo)

        self.log_message(f"🚀 Iniciando ráfaga histórica: {horas}h cada {intervalo}min ({total_pasos} lotes)")

        if not self.engine.session_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.engine.session_file = f"simulacion_{timestamp}.json"
            self.engine.session_data = []

        def worker():
            fecha_simulada = datetime.now()
            for _ in range(total_pasos):
                batch = []
                for pid in PUNTOS_ID:
                    try:
                        v_min = float(self.individual_configs[pid]["min"].get())
                        v_max = float(self.individual_configs[pid]["max"].get())
                    except:
                        v_min, v_max = 10, 100

                    val = round(random.uniform(v_min, v_max), 2)
                    batch.append({
                        "id_punto": pid, 
                        "consumo_kwh": val, 
                        "fecha": self.engine.get_formatted_date(fecha_simulada),
                        "timestamp": fecha_simulada.isoformat()
                    })

                if self.dest_var.get() == "DB":
                    self.engine.enviar_datos(batch)
                self.engine.guardar_en_archivo(batch)

                self.root.after(0, self.update_table, batch)
                fecha_simulada += timedelta(minutes=intervalo)
            self.log_message(f"✅ Simulación acelerada completada. Datos en {self.engine.session_file}")

        threading.Thread(target=worker, daemon=True).start()

    def sort_column(self, col, reverse):
        # Si es la columna de Hora, manejamos el indicador visual y alternancia
        if col == "Hora":
            self.sort_descending = not self.sort_descending if reverse is None else reverse
            reverse = self.sort_descending
            icon = "▼" if reverse else "▲"
            self.monitor_tree.heading("Hora", text=f"FECHA {icon}")

        l = [(self.monitor_tree.set(k, col), k) for k in self.monitor_tree.get_children('')]
        # Intentar ordenar numéricamente si es posible, si no, alfabéticamente
        try:
            l.sort(key=lambda t: float(t[0]), reverse=reverse)
        except ValueError:
            l.sort(reverse=reverse)

        for index, (val, k) in enumerate(l):
            self.monitor_tree.move(k, '', index)

    def apply_filter(self):
        filtro = self.filter_var.get()
        for item in self.monitor_tree.get_children():
            self.monitor_tree.delete(item)
        
        # Recargar desde la data de sesión filtrando
        for entry in self.engine.session_data:
            if filtro == "TODOS" or entry["id_punto"] == filtro:
                self.monitor_tree.insert("", "end", values=(entry["id_punto"], entry["consumo_kwh"], entry["fecha"]))
        self.log_message(f"Vista filtrada por: {filtro}")

    def update_table(self, batch):
        filtro = self.filter_var.get()
        for item in batch:
            if filtro == "TODOS" or item["id_punto"] == filtro:
                self.monitor_tree.insert("", "end", values=(item["id_punto"], item["consumo_kwh"], item["fecha"]))
        self.monitor_tree.yview_moveto(1) # Auto-scroll to bottom

# --- ARRANQUE ---

if __name__ == "__main__":
    def launch_main():
        login_root.destroy()
        app_root = tk.Tk()
        SimulatorApp(app_root)
        app_root.mainloop()

    login_root = tk.Tk()
    LoginWindow(login_root, launch_main)
    login_root.mainloop()