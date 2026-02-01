# *********************************************************************************************
# Escuela Superior de Innovación y tecnologia. El Salvador.                                   *
# Tecnico superior en Servicios de computación en la nube.                                    *
# Fecha de desarrollo: Diciembre 2025.                                                        *
# Para proyecto NUBE VERDE                                                                    *
# GRUPO: 6                                                                                    *
# Descripción: Simulador de datos de consumo energético para múltiples puntos de medición,    *
# con capacidad de envío a Google Firestore.tanto en tiempo real como en modo acelerado.      *
# Creado por: Tec. René Mauricio Góchez Chicas.                                               *
# Versión: 4.0.0                                                                              *
# Modificaciones:                                                                             *
#       su cambio libreria a una mas actal google-cloud-storage dejamos de usar gcloud        *

# Apoyo de GEMINI para edicion y correcciones y GEMINI para estructura, funciones y clases.*
#                                                                                             *
# # NOTA: Requiere instalar firebase-admin y tener las credenciales adecuadas.                *
# *********************************************************************************************

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, simpledialog

import random
import time
import threading

from datetime import datetime, timedelta
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud import storage
import pyrebase  # <--- NUEVA LIBRERÍA PARA AUTH DE USUARIO

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


FIREBASE_CRED_PATH = 'serviceAccountKey.json'
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
        self.init_default_config()

    def init_default_config(self):
        default_params = {"metodo": "rango", "min": 10, "max": 100, "constante": 50, "prob": 80, "estado": "activo"}
        for pid in PUNTOS_ID:
            self.config[pid] = {h: default_params.copy() for h in range(24)}

    def init_firestore(self):
        if not firebase_admin._apps:
            try:
                cred = credentials.Certificate(FIREBASE_CRED_PATH)
                firebase_admin.initialize_app(cred)
                return firestore.client()
            except Exception as e:
                self.log(f"OFFLINE: {e}")
                return None
        return firestore.client()

    def init_storage(self):
        try:
            # Utiliza las mismas credenciales que Firestore
            return storage.Client.from_service_account_json(FIREBASE_CRED_PATH)
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
        
        # Inicializar Pyrebase para la autenticación
        self.firebase_auth = pyrebase.initialize_app(FIREBASE_CONFIG).auth()

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
            # Validar con Firebase Auth
            user = self.firebase_auth.sign_in_with_email_and_password(email, password)
            # Si tiene éxito, pasamos a la app principal
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
        self.setup_ui()

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
        tab_control.pack(expand=1, fill="both")

        # Botones de control
        btn_frame = ttk.Frame(self.tab_main)
        btn_frame.pack(pady=10)
        self.btn_start = ttk.Button(btn_frame, text="▶ INICIAR", command=self.start_simulation)
        self.btn_start.pack(side="left", padx=10)
        self.btn_stop = ttk.Button(btn_frame, text="⏹ PARAR", command=self.stop_simulation, state="disabled")
        self.btn_stop.pack(side="left", padx=10)

        self.monitor_tree = ttk.Treeview(self.tab_main, columns=("ID", "Valor", "Hora"), show="headings")
        self.monitor_tree.heading("ID", text="PUNTO"); self.monitor_tree.heading("Valor", text="kWh"); self.monitor_tree.heading("Hora", text="FECHA")
        self.monitor_tree.pack(fill="both", expand=True, padx=10, pady=10)

        self.log_area = scrolledtext.ScrolledText(self.tab_logs, state='disabled', bg="black", fg="#00FF41")
        self.log_area.pack(fill="both", expand=True)

    def start_simulation(self):
        self.stop_event.clear()
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        threading.Thread(target=self.run_process, daemon=True).start()

    def stop_simulation(self):
        self.stop_event.set()
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")

    def run_process(self):
        while not self.stop_event.is_set():
            batch = []
            now = datetime.now()
            for pid in PUNTOS_ID:
                val = self.engine.simular_valor(pid, now.hour)
                batch.append({"id_punto": pid, "consumo_kwh": val, "fecha": self.engine.get_formatted_date(now)})
            
            self.engine.enviar_datos(batch)
            self.root.after(0, self.update_table, batch)
            time.sleep(10)

    def update_table(self, batch):
        for i in self.monitor_tree.get_children(): self.monitor_tree.delete(i)
        for item in batch:
            self.monitor_tree.insert("", "end", values=(item["id_punto"], item["consumo_kwh"], item["fecha"]))

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