# *********************************************************************************************
# Escuela Superior de Innovación y tecnologia. El Salvador.                                   *
# Tecnico superior en Servicios de computación en la nube.                                    *
# Fecha de desarrollo: Diciembre 2025.                                                        *
# Para proyecto NUBE VERDE                                                                    *
# GRUPO: 6                                                                                    *
# Descripción: Simulador de datos de consumo energético para múltiples puntos de medición,    *
# con capacidad de envío a Google Firestore.tanto en tiempo real como en modo acelerado.      *
# Creado por: Tec. René Mauricio Góchez Chicas.                                               *
# Versión: 1.0                                                                                *
# Apoyo de ChatGPT-4 para edicion y correcciones y GEMINI para estructura, funciones y clases.*
#                                                                                             *
# # NOTA: Requiere instalar firebase-admin y tener las credenciales adecuadas.                *
# *********************************************************************************************
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import json
import random
import time
import threading
import os
from datetime import datetime, timedelta
import firebase_admin
from firebase_admin import credentials, firestore


# configuramos las variables globales e importantes del script.


FIREBASE_CRED_PATH = 'serviceAccountKey.json'
COLECCION_FIRESTORE = 'lecturaPruebas'

FILE_SENT = 'datos_enviados.json'
FILE_UNSENT = 'datos_no_enviados.json'
FILE_ACCEL_OUTPUT = 'salida_acelerada.json'

PUNTOS_ID = [f"N{i}" for i in range(1, 13)] # N1 a N12

# Mapeo manual de meses para asegurar formato español sin depender del OS locale
MESES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
    7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
}

class SimulationEngine:
    """
    Clase encargada de la lógica pura: generación de datos,
    conexión a DB y manejo de archivos locales.
    """
    def __init__(self, log_callback):
        self.db = self.init_firestore()
        self.log = log_callback
        self.running = False
        
        # Estructura de configuración por defecto para cada punto (simplificada para todas las horas)
        # En un caso real, esto sería una matriz de 12 puntos x 24 horas.
        self.config = {pid: {"metodo": "rango", "min": 10, "max": 100, "constante": 50, "prob": 80, "estado": "activo"} for pid in PUNTOS_ID}

    def init_firestore(self):
        """Inicializa la conexión a Firebase."""
        # NOTA: Verifica si ya está inicializada para evitar errores al reiniciar
        if not firebase_admin._apps:
            try:
                cred = credentials.Certificate(FIREBASE_CRED_PATH)
                firebase_admin.initialize_app(cred)
                #self.log("Conexión a Firestore exitosa.")
                return firestore.client()
            except Exception as e:
                self.log(f"ERROR: No se pudo conectar a Firebase: {e}")
                self.log("El sistema funcionará en modo OFFLINE (guardando localmente).")
                return None
        return firestore.client()

    def get_formatted_date(self, dt_obj):
        """Genera el string de fecha específico solicitado."""
        mes = MESES[dt_obj.month]
        am_pm = "a.m." if dt_obj.hour < 12 else "p.m."
        # Formato 12 horas para la hora visual, pero manteniendo precisión
        hora_12 = dt_obj.strftime("%I:%M:%S").lstrip("0")
        return f"{dt_obj.day} de {mes} de {dt_obj.year} a las {hora_12} {am_pm} UTC-6"

    def simular_valor(self, pid, current_hour):
        """
        Núcleo de la lógica de simulación.
        Aplica las 3 reglas según la configuración del punto.
        """
        cfg = self.config[pid]
        
        if cfg["estado"] == "inactivo":
            return 0
        
        metodo = cfg["metodo"]
        
        if metodo == "constante":
            return float(cfg["constante"])
        
        elif metodo == "rango":
            return round(random.uniform(cfg["min"], cfg["max"]), 2)
        
        elif metodo == "probabilistico":
            # Si random (0-100) es menor o igual a la probabilidad, genera valor, sino 0
            if random.uniform(0, 100) <= cfg["prob"]:
                return round(random.uniform(0, cfg["max"]), 2)
            else:
                return 0
        return 0

    def guardar_local(self, data, filename):
        """Guarda datos en JSON local (append mode simulado)."""
        existing_data = []
        if os.path.exists(filename):
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
            except json.JSONDecodeError:
                pass # Archivo corrupto o vacío
        
        # Si es una lista, extendemos. Si es un dict único, lo metemos en lista.
        if isinstance(data, list):
            existing_data.extend(data)
        else:
            existing_data.append(data)

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(existing_data, f, indent=4, ensure_ascii=False)

    def enviar_datos(self, data_batch):
        """
        Intenta enviar a Firestore. Gestiona la lógica de reintento (Cola de No Enviados).
        """
        if not self.db:
            self.guardar_local(data_batch, FILE_UNSENT)
            return False

        # 1. Intentar enviar datos antiguos (Retry Logic)
        if os.path.exists(FILE_UNSENT):
            try:
                with open(FILE_UNSENT, 'r', encoding='utf-8') as f:
                    unsent = json.load(f)
                if unsent:
                    self.log(f"Reintentando enviar {len(unsent)} registros antiguos...")
                    batch = self.db.batch()
                    for doc in unsent:
                        doc_ref = self.db.collection(COLECCION_FIRESTORE).document()
                        batch.set(doc_ref, doc)
                    batch.commit()
                    # Si tiene éxito, vaciamos el archivo de no enviados y guardamos en enviados
                    self.guardar_local(unsent, FILE_SENT)
                    open(FILE_UNSENT, 'w').close() # Limpiar archivo
                    self.log("Registros antiguos recuperados y enviados.")
            except Exception as e:
                self.log(f"Error reintentando antiguos: {e}")

        # 2. Enviar datos actuales
        try:
            batch = self.db.batch()
            for item in data_batch:
                doc_ref = self.db.collection(COLECCION_FIRESTORE).document()
                batch.set(doc_ref, item)
            batch.commit()
            
            self.guardar_local(data_batch, FILE_SENT)
            self.log(f"Lote de {len(data_batch)} datos enviado y respaldado.")
            return True
        except Exception as e:
            self.log(f"FALLO DE CONEXIÓN: {e}. Guardando en no enviados.")
            self.guardar_local(data_batch, FILE_UNSENT)
            return False

class SimulatorApp:
    """
    Clase principal de la Interfaz Gráfica (GUI).
    Maneja los hilos y la interacción con el usuario.
    """
    def __init__(self, root):
        self.root = root
        self.root.title("Simulador Experto de Energía - Firestore")
        self.root.geometry("900x700")
        
        self.engine = SimulationEngine(self.log_message)
        self.simulation_thread = None
        self.stop_event = threading.Event()

        self.setup_ui()

    def setup_ui(self):
        # Tabs
        tab_control = ttk.Notebook(self.root)
        self.tab_main = ttk.Frame(tab_control)
        self.tab_config = ttk.Frame(tab_control)
        self.tab_logs = ttk.Frame(tab_control)
        
        tab_control.add(self.tab_main, text='Control y Ejecución')
        tab_control.add(self.tab_config, text='Parametrización Puntos')
        tab_control.add(self.tab_logs, text='Logs y Datos')
        tab_control.pack(expand=1, fill="both")

        # --- TAB MAIN ---
        frame_controls = ttk.LabelFrame(self.tab_main, text="Configuración de Ejecución")
        frame_controls.pack(padx=10, pady=10, fill="x")

        # Modo de ejecución
        self.mode_var = tk.StringVar(value="realtime")
        ttk.Radiobutton(frame_controls, text="Tiempo Real", variable=self.mode_var, value="realtime", command=self.toggle_inputs).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(frame_controls, text="Acelerado (Histórico)", variable=self.mode_var, value="accelerated", command=self.toggle_inputs).grid(row=0, column=1, sticky="w")

        # Inputs Tiempo Real
        self.frame_real = ttk.Frame(frame_controls)
        self.frame_real.grid(row=1, column=0, columnspan=2, pady=5, sticky="w")
        ttk.Label(self.frame_real, text="Recurrencia (seg):").pack(side="left")
        self.recurrencia_combo = ttk.Combobox(self.frame_real, values=["15", "30", "60"], width=5)
        self.recurrencia_combo.current(0)
        self.recurrencia_combo.pack(side="left", padx=5)

        # Inputs Acelerado
        self.frame_accel = ttk.Frame(frame_controls)
        self.frame_accel.grid(row=2, column=0, columnspan=2, pady=5, sticky="w")
        ttk.Label(self.frame_accel, text="Fecha Inicio (dd/mm/yyyy HH:MM):").pack(side="left")
        self.start_date_entry = ttk.Entry(self.frame_accel, width=18)
        self.start_date_entry.insert(0, "20/12/2025 08:00")
        self.start_date_entry.pack(side="left", padx=5)
        
        ttk.Label(self.frame_accel, text="Duración (Horas):").pack(side="left")
        self.duration_entry = ttk.Entry(self.frame_accel, width=5)
        self.duration_entry.insert(0, "24")
        self.duration_entry.pack(side="left", padx=5)
        
        # Botones de Acción
        frame_actions = ttk.Frame(self.tab_main)
        frame_actions.pack(pady=10)
        self.btn_start = ttk.Button(frame_actions, text="INICIAR SIMULACIÓN", command=self.start_simulation)
        self.btn_start.pack(side="left", padx=10)
        self.btn_stop = ttk.Button(frame_actions, text="DETENER", command=self.stop_simulation, state="disabled")
        self.btn_stop.pack(side="left", padx=10)
        
        # Monitor Visual
        self.monitor_tree = ttk.Treeview(self.tab_main, columns=("ID", "Valor", "Estado", "Hora"), show="headings", height=12)
        self.monitor_tree.heading("ID", text="ID Punto")
        self.monitor_tree.heading("Valor", text="Consumo kWh")
        self.monitor_tree.heading("Estado", text="Estado")
        self.monitor_tree.heading("Hora", text="Última Actualización")
        self.monitor_tree.pack(padx=10, pady=10, fill="both", expand=True)

        # --- TAB CONFIG ---
        ttk.Label(self.tab_config, text="Configurar Puntos (Aplica a todas las horas por simplicidad UI)").pack(pady=5)
        
        frame_edit = ttk.Frame(self.tab_config)
        frame_edit.pack(pady=5)
        
        ttk.Label(frame_edit, text="Punto:").grid(row=0, column=0)
        self.combo_punto = ttk.Combobox(frame_edit, values=PUNTOS_ID)
        self.combo_punto.current(0)
        self.combo_punto.grid(row=0, column=1)
        self.combo_punto.bind("<<ComboboxSelected>>", self.load_point_config)

        ttk.Label(frame_edit, text="Estado:").grid(row=0, column=2)
        self.combo_estado = ttk.Combobox(frame_edit, values=["activo", "inactivo"])
        self.combo_estado.grid(row=0, column=3)

        ttk.Label(frame_edit, text="Método:").grid(row=1, column=0)
        self.combo_metodo = ttk.Combobox(frame_edit, values=["constante", "rango", "probabilistico"])
        self.combo_metodo.grid(row=1, column=1)
        
        # Params dinámicos
        ttk.Label(frame_edit, text="Min / Constante:").grid(row=2, column=0)
        self.entry_p1 = ttk.Entry(frame_edit)
        self.entry_p1.grid(row=2, column=1)
        
        ttk.Label(frame_edit, text="Max / Prob(%):").grid(row=2, column=2)
        self.entry_p2 = ttk.Entry(frame_edit)
        self.entry_p2.grid(row=2, column=3)

        ttk.Button(frame_edit, text="Guardar Cambios Punto", command=self.save_point_config).grid(row=3, column=0, columnspan=4, pady=10)

        # --- TAB LOGS ---
        self.log_area = scrolledtext.ScrolledText(self.tab_logs, state='disabled')
        self.log_area.pack(fill="both", expand=True)
        
        # Inicializar UI State
        self.toggle_inputs()
        self.load_point_config()

    def toggle_inputs(self):
        if self.mode_var.get() == "realtime":
            self.frame_real.state(["!disabled"])
            for child in self.frame_accel.winfo_children(): child.configure(state='disabled')
        else:
            self.frame_real.state(["disabled"])
            for child in self.frame_accel.winfo_children(): child.configure(state='normal')

    def log_message(self, msg):
        timestamp = datetime.now().strftime("%H:%M:%S")
        final_msg = f"[{timestamp}] {msg}\n"
        self.log_area.config(state='normal')
        self.log_area.insert(tk.END, final_msg)
        self.log_area.see(tk.END)
        self.log_area.config(state='disabled')

    # --- LÓGICA DE CONFIGURACIÓN ---
    def load_point_config(self, event=None):
        pid = self.combo_punto.get()
        cfg = self.engine.config[pid]
        self.combo_estado.set(cfg["estado"])
        self.combo_metodo.set(cfg["metodo"])
        
        if cfg["metodo"] == "constante":
            self.entry_p1.delete(0, tk.END); self.entry_p1.insert(0, cfg["constante"])
            self.entry_p2.delete(0, tk.END); self.entry_p2.insert(0, "0")
        elif cfg["metodo"] == "rango":
            self.entry_p1.delete(0, tk.END); self.entry_p1.insert(0, cfg["min"])
            self.entry_p2.delete(0, tk.END); self.entry_p2.insert(0, cfg["max"])
        elif cfg["metodo"] == "probabilistico":
            self.entry_p1.delete(0, tk.END); self.entry_p1.insert(0, cfg["prob"]) # Prob % en p1 para este ejemplo
            self.entry_p2.delete(0, tk.END); self.entry_p2.insert(0, cfg["max"])

    def save_point_config(self):
        pid = self.combo_punto.get()
        try:
            val1 = float(self.entry_p1.get())
            val2 = float(self.entry_p2.get())
            metodo = self.combo_metodo.get()
            
            new_cfg = {
                "estado": self.combo_estado.get(),
                "metodo": metodo,
                "constante": val1 if metodo == "constante" else 0,
                "min": val1 if metodo == "rango" else 0,
                "max": val2 if metodo in ["rango", "probabilistico"] else 0,
                "prob": val1 if metodo == "probabilistico" else 0
            }
            self.engine.config[pid] = new_cfg
            messagebox.showinfo("Éxito", f"Configuración guardada para {pid}")
        except ValueError:
            messagebox.showerror("Error", "Los valores numéricos deben ser válidos.")

    # --- LÓGICA DE SIMULACIÓN ---
    def start_simulation(self):
        if not self.stop_event.is_set() and self.simulation_thread is not None:
             if self.simulation_thread.is_alive(): return

        self.stop_event.clear()
        self.engine.running = True
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        
        mode = self.mode_var.get()
        
        if mode == "realtime":
            interval = int(self.recurrencia_combo.get())
            self.simulation_thread = threading.Thread(target=self.run_realtime, args=(interval,), daemon=True)
        else:
            start_str = self.start_date_entry.get()
            hours = int(self.duration_entry.get())
            self.simulation_thread = threading.Thread(target=self.run_accelerated, args=(start_str, hours), daemon=True)
            
        self.simulation_thread.start()

    def stop_simulation(self):
        self.stop_event.set()
        self.engine.running = False
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.log_message("Deteniendo simulación...")

    def update_monitor(self, batch_data):
        # Actualizar tabla visual
        for i in self.monitor_tree.get_children():
            self.monitor_tree.delete(i)
        
        for item in batch_data:
            self.monitor_tree.insert("", "end", values=(item["id_punto"], item["consumo_kwh"], item["estado"], item["fecha"]))

    def run_realtime(self, interval):
        self.log_message(f"Iniciando simulación en tiempo real (cada {interval}s)...")
        
        while not self.stop_event.is_set():
            now = datetime.now()
            batch = []
            
            for pid in PUNTOS_ID:
                val = self.engine.simular_valor(pid, now.hour)
                record = {
                    "consumo_kwh": val,
                    "fecha": self.engine.get_formatted_date(now),
                    "estado": self.engine.config[pid]["estado"],
                    "id_punto": pid
                }
                batch.append(record)
            
            # Actualizar GUI en el hilo principal
            self.root.after(0, self.update_monitor, batch)
            
            # Enviar a DB
            self.engine.enviar_datos(batch)
            
            # Esperar
            time.sleep(interval)
        
        self.log_message("Simulación Realtime finalizada.")

    def run_accelerated(self, start_str, hours):
        self.log_message("Iniciando simulación acelerada...")
        try:
            current_time = datetime.strptime(start_str, "%d/%m/%Y %H:%M")
        except ValueError:
            self.log_message("Error: Formato de fecha incorrecto.")
            self.stop_simulation()
            return

        end_time = current_time + timedelta(hours=hours)
        interval_sim = timedelta(seconds=int(self.recurrencia_combo.get()) if self.recurrencia_combo.get() else 60) # Usamos recurrencia seleccionada para granularidad
        
        total_records = []
        
        while current_time < end_time and not self.stop_event.is_set():
            batch = []
            for pid in PUNTOS_ID:
                val = self.engine.simular_valor(pid, current_time.hour)
                record = {
                    "consumo_kwh": val,
                    "fecha": self.engine.get_formatted_date(current_time),
                    "estado": self.engine.config[pid]["estado"],
                    "id_punto": pid
                }
                batch.append(record)
            
            # Guardar uno a uno en archivo de salida acelerada
            self.engine.guardar_local(batch, FILE_ACCEL_OUTPUT)
            total_records.extend(batch)
            
            # Actualizar visualmente cada cierto tiempo para no congelar si es muy rápido
            if len(total_records) % 100 == 0:
                self.root.after(0, self.update_monitor, batch)
                self.log_message(f"Simulando: {current_time}")

            current_time += interval_sim
            time.sleep(0.01) # Pequeña pausa para no bloquear CPU
            
        self.log_message(f"Simulación acelerada terminada. Enviando {len(total_records)} registros a DB...")
        
        # Enviar todo el lote a Firestore (puede tardar)
        # NOTA: Firestore tiene limites de batch (500), así que hacemos chunks
        chunk_size = 400
        for i in range(0, len(total_records), chunk_size):
            if self.stop_event.is_set(): break
            chunk = total_records[i:i + chunk_size]
            self.engine.enviar_datos(chunk)
            self.log_message(f"Subido bloque {i} a {i+len(chunk)}")
            
        self.stop_simulation()

if __name__ == "__main__":
    root = tk.Tk()
    app = SimulatorApp(root)
    root.mainloop()