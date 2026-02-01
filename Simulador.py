# *********************************************************************************************
# Escuela Superior de Innovación y tecnologia. El Salvador.                                   *
# Tecnico superior en Servicios de computación en la nube.                                    *
# Fecha de desarrollo: Diciembre 2025.                                                        *
# Para proyecto NUBE VERDE                                                                    *
# GRUPO: 6                                                                                    *
# Descripción: Simulador de datos de consumo energético para múltiples puntos de medición,    *
# con capacidad de envío a Google Firestore.tanto en tiempo real como en modo acelerado.      *
# Creado por: Tec. René Mauricio Góchez Chicas.                                               *
# Versión: 4.1.0                                                                              *
# Modificaciones:                                                                             *
#                se coloco la opcion de guardar directamente en la base de datos o un archivo *
# Apoyo de GEMINI para edicion y correcciones y GEMINI para estructura, funciones y clases.   *
#                                                                                             *
# # NOTA: Requiere instalar firebase-admin y tener las credenciales adecuadas.                *
# *********************************************************************************************

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, simpledialog
import json
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
        self.dest_var = tk.StringVar(value="DB")
        self.combo_dest = ttk.Combobox(btn_frame, textvariable=self.dest_var, values=["DB", "ARCHIVO"], width=10, state="readonly")
        self.combo_dest.pack(side="left", padx=5)

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
        self.monitor_tree = ttk.Treeview(self.tab_main, columns=("ID", "Valor", "Hora"), show="headings")
        self.monitor_tree.heading("ID", text="PUNTO"); self.monitor_tree.heading("Valor", text="kWh"); self.monitor_tree.heading("Hora", text="FECHA")
        self.monitor_tree.pack(fill="both", expand=True, padx=10, pady=10)

        self.log_area = scrolledtext.ScrolledText(self.tab_logs, state='disabled', bg="black", fg="#00FF41")
        self.log_area.pack(fill="both", expand=True)

    def confirm_exit(self):
        if messagebox.askokcancel("Confirmar Salida", "¿Desea cerrar el simulador?"):
            self.stop_event.set()
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
        self.combo_dest.config(state="disabled")
        self.lbl_status_led.config(foreground="#00FF41") # Verde
        threading.Thread(target=self.run_process, daemon=True).start()

    def stop_simulation(self):
        self.stop_event.set()
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.min_val.config(state="normal")
        self.max_val.config(state="normal")
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
                
                batch.append({"id_punto": pid, "consumo_kwh": val, "fecha": self.engine.get_formatted_date(now)})
            
            if self.dest_var.get() == "DB":
                self.engine.enviar_datos(batch)
            else:
                self.engine.guardar_en_archivo(batch)

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