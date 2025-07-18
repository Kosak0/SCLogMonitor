import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
from PIL import Image, ImageTk
import time
import re
import requests
from lxml import html
import threading
import queue
from datetime import datetime, timedelta
import json
import sys
import os
import math
import logging
from pathlib import Path
import hashlib
import sqlite3
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import webbrowser

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class PlayerInfo:
    """Clase para almacenar información de jugadores"""
    handle: str
    main_org: str = ""
    main_org_name: str = ""
    org_rank: str = ""
    enlisted: str = ""
    location: str = ""
    fluency: str = ""
    last_updated: datetime = None

@dataclass
class LogEvent:
    """Clase para eventos del log"""
    timestamp: datetime
    event_type: str
    message: str
    participants: List[str]
    raw_line: str

def get_resource_path(relative_path):
    """Obtener la ruta correcta para recursos, funciona tanto en desarrollo como compilado"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class DatabaseManager:
    """Gestor de base de datos para cache de jugadores y estadísticas"""

    def __init__(self, db_path="sc_monitor.db"):
        self.db_path = db_path
        self.init_database()

    def init_database(self):
        """Inicializar base de datos"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Tabla de jugadores
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS players (
                        handle TEXT PRIMARY KEY,
                        main_org TEXT,
                        main_org_name TEXT,
                        org_rank TEXT,
                        enlisted TEXT,
                        location TEXT,
                        fluency TEXT,
                        last_updated TIMESTAMP,
                        cache_hash TEXT
                    )
                ''')

                # Tabla de estadísticas
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS stats (
                        date TEXT,
                        player TEXT,
                        kills INTEGER DEFAULT 0,
                        deaths INTEGER DEFAULT 0,
                        vehicles_destroyed INTEGER DEFAULT 0,
                        missiles_fired INTEGER DEFAULT 0,
                        PRIMARY KEY (date, player)
                    )
                ''')

                # Tabla de eventos
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TIMESTAMP,
                        event_type TEXT,
                        message TEXT,
                        participants TEXT,
                        raw_line TEXT
                    )
                ''')

                conn.commit()
        except Exception as e:
            logger.error(f"Error inicializando base de datos: {e}")

    def get_player_info(self, handle: str) -> Optional[PlayerInfo]:
        """Obtener información de jugador desde cache"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM players WHERE handle = ? AND 
                    last_updated > datetime('now', '-7 days')
                ''', (handle,))

                row = cursor.fetchone()
                if row:
                    return PlayerInfo(
                        handle=row[0],
                        main_org=row[1] or "",
                        main_org_name=row[2] or "",
                        org_rank=row[3] or "",
                        enlisted=row[4] or "",
                        location=row[5] or "",
                        fluency=row[6] or "",
                        last_updated=datetime.fromisoformat(row[7]) if row[7] else None
                    )
        except Exception as e:
            logger.error(f"Error obteniendo info de jugador: {e}")
        return None

    def save_player_info(self, player_info: PlayerInfo):
        """Guardar información de jugador en cache"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO players 
                    (handle, main_org, main_org_name, org_rank, enlisted, location, fluency, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    player_info.handle,
                    player_info.main_org,
                    player_info.main_org_name,
                    player_info.org_rank,
                    player_info.enlisted,
                    player_info.location,
                    player_info.fluency,
                    datetime.now().isoformat()
                ))
                conn.commit()
        except Exception as e:
            logger.error(f"Error guardando info de jugador: {e}")

    def update_stats(self, date: str, player: str, stat_type: str):
        """Actualizar estadísticas de jugador"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(f'''
                    INSERT OR IGNORE INTO stats (date, player, {stat_type})
                    VALUES (?, ?, 1)
                ''', (date, player))

                cursor.execute(f'''
                    UPDATE stats SET {stat_type} = {stat_type} + 1
                    WHERE date = ? AND player = ?
                ''', (date, player))

                conn.commit()
        except Exception as e:
            logger.error(f"Error actualizando estadísticas: {e}")

    def get_player_stats(self, player: str, days: int = 7) -> Dict:
        """Obtener estadísticas de jugador"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT SUM(kills), SUM(deaths), SUM(vehicles_destroyed), SUM(missiles_fired)
                    FROM stats 
                    WHERE player = ? AND date >= date('now', '-{} days')
                '''.format(days), (player,))

                row = cursor.fetchone()
                if row:
                    return {
                        'kills': row[0] or 0,
                        'deaths': row[1] or 0,
                        'vehicles_destroyed': row[2] or 0,
                        'missiles_fired': row[3] or 0
                    }
        except Exception as e:
            logger.error(f"Error obteniendo estadísticas: {e}")
        return {'kills': 0, 'deaths': 0, 'vehicles_destroyed': 0, 'missiles_fired': 0}


class NotificationSystem:
    """Sistema de notificaciones mejorado"""

    def __init__(self, parent):
        self.parent = parent
        self.notifications = []
        self.max_notifications = 5

    def show_notification(self, title: str, message: str, notification_type: str = "info", duration: int = 5000):
        """Mostrar notificación emergente"""
        try:
            # Crear ventana de notificación
            notification = tk.Toplevel(self.parent.root)
            notification.title(title)
            notification.geometry("300x100")
            notification.configure(bg='#2a2a2a')
            notification.overrideredirect(True)
            notification.wm_attributes("-topmost", True)
            notification.wm_attributes("-alpha", 0.9)

            # Posicionar en esquina superior derecha
            x = notification.winfo_screenwidth() - 320
            y = 20 + len(self.notifications) * 110
            notification.geometry(f"300x100+{x}+{y}")

            # Configurar colores según tipo
            colors = {
                "info": "#2d4a5a",
                "warning": "#5a4a2d",
                "error": "#5a2d2d",
                "success": "#2d5a2d"
            }
            bg_color = colors.get(notification_type, "#2d4a5a")

            # Frame principal
            main_frame = tk.Frame(notification, bg=bg_color, relief=tk.RAISED, bd=1)
            main_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

            # Título
            title_label = tk.Label(main_frame, text=title, font=('Arial', 10, 'bold'),
                                 bg=bg_color, fg='white')
            title_label.pack(pady=(5, 0))

            # Mensaje
            msg_label = tk.Label(main_frame, text=message, font=('Arial', 9),
                               bg=bg_color, fg='white', wraplength=280)
            msg_label.pack(pady=(0, 5))

            # Botón cerrar
            close_btn = tk.Button(main_frame, text="×", command=lambda: self.close_notification(notification),
                                bg=bg_color, fg='white', font=('Arial', 12, 'bold'),
                                relief=tk.FLAT, width=2)
            close_btn.place(relx=1.0, rely=0.0, anchor='ne', x=-5, y=5)

            # Añadir a lista
            self.notifications.append(notification)

            # Auto-cerrar después del tiempo especificado
            notification.after(duration, lambda: self.close_notification(notification))

            # Efecto de aparición
            self.fade_in(notification)

        except Exception as e:
            logger.error(f"Error mostrando notificación: {e}")

    def close_notification(self, notification):
        """Cerrar notificación"""
        try:
            if notification in self.notifications:
                self.notifications.remove(notification)
                notification.destroy()
                self.reposition_notifications()
        except Exception as e:
            logger.error(f"Error cerrando notificación: {e}")

    def reposition_notifications(self):
        """Reposicionar notificaciones restantes"""
        for i, notification in enumerate(self.notifications):
            try:
                x = notification.winfo_screenwidth() - 320
                y = 20 + i * 110
                notification.geometry(f"300x100+{x}+{y}")
            except:
                pass

    def fade_in(self, window, alpha=0.0):
        """Efecto de aparición gradual"""
        try:
            if alpha < 0.9:
                window.wm_attributes("-alpha", alpha)
                window.after(50, lambda: self.fade_in(window, alpha + 0.1))
            else:
                window.wm_attributes("-alpha", 0.9)
        except:
            pass

class StatsWindow:
    """Ventana de estadísticas"""

    def __init__(self, parent, db_manager):
        self.parent = parent
        self.db = db_manager
        self.window = tk.Toplevel(parent.root)
        self.setup_window()
        self.setup_ui()
        self.load_stats()

    def setup_window(self):
        """Configurar ventana de estadísticas"""
        self.window.title("Estadísticas - Star Citizen Log Monitor")
        self.window.geometry("600x500")
        self.window.configure(bg='#1a1a1a')
        self.window.resizable(True, True)

        # Configurar icono
        try:
            icon_path = get_resource_path('logoStar.ico')
            if os.path.exists(icon_path):
                self.window.iconbitmap(icon_path)
        except:
            pass

        # Hacer modal
        self.window.transient(self.parent.root)
        self.window.grab_set()

    def setup_ui(self):
        """Configurar interfaz de estadísticas"""
        # Frame principal
        main_frame = tk.Frame(self.window, bg='#1a1a1a')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Título
        title_label = tk.Label(main_frame, text="📊 Estadísticas de Combate", 
                             font=('Arial', 16, 'bold'),
                             bg='#1a1a1a', fg='white')
        title_label.pack(pady=(0, 20))

        # Notebook para pestañas
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Pestaña de estadísticas personales
        self.setup_personal_stats()

        # Pestaña de estadísticas globales
        self.setup_global_stats()

        # Botón cerrar
        close_btn = tk.Button(main_frame, text="Cerrar", command=self.window.destroy,
                            bg='#404040', fg='white', width=12)
        close_btn.pack(pady=10)

    def setup_personal_stats(self):
        """Configurar pestaña de estadísticas personales"""
        personal_frame = tk.Frame(self.notebook, bg='#2a2a2a')
        self.notebook.add(personal_frame, text="Personal")

        # Estadísticas del usuario actual
        user_stats = self.db.get_player_stats(self.parent.CURRENT_USER)

        stats_frame = tk.LabelFrame(personal_frame, text=f"Estadísticas de {self.parent.CURRENT_USER}",
                                  bg='#2a2a2a', fg='white', font=('Arial', 12, 'bold'))
        stats_frame.pack(fill=tk.X, padx=10, pady=10)

        # Crear grid de estadísticas
        stats_data = [
            ("🎯 Eliminaciones", user_stats['kills']),
            ("💀 Muertes", user_stats['deaths']),
            ("🚁 Vehículos destruidos", user_stats['vehicles_destroyed']),
            ("🚀 Misiles disparados", user_stats['missiles_fired'])
        ]

        for i, (label, value) in enumerate(stats_data):
            row = i // 2
            col = i % 2

            stat_frame = tk.Frame(stats_frame, bg='#404040', relief=tk.RAISED, bd=1)
            stat_frame.grid(row=row, column=col, padx=5, pady=5, sticky='ew')

            tk.Label(stat_frame, text=label, bg='#404040', fg='white',
                   font=('Arial', 10)).pack(pady=2)
            tk.Label(stat_frame, text=str(value), bg='#404040', fg='#ffff00',
                   font=('Arial', 14, 'bold')).pack(pady=2)

        # Configurar grid
        stats_frame.grid_columnconfigure(0, weight=1)
        stats_frame.grid_columnconfigure(1, weight=1)

        # Ratio K/D
        kd_ratio = user_stats['kills'] / max(user_stats['deaths'], 1)
        ratio_label = tk.Label(personal_frame, 
                             text=f"Ratio K/D: {kd_ratio:.2f}",
                             bg='#2a2a2a', fg='#00ff00' if kd_ratio >= 1 else '#ff0000',
                             font=('Arial', 12, 'bold'))
        ratio_label.pack(pady=10)

    def setup_global_stats(self):
        """Configurar pestaña de estadísticas globales"""
        global_frame = tk.Frame(self.notebook, bg='#2a2a2a')
        self.notebook.add(global_frame, text="Global")

        # Aquí se pueden añadir estadísticas globales del servidor
        tk.Label(global_frame, text="Estadísticas globales próximamente...",
               bg='#2a2a2a', fg='white', font=('Arial', 12)).pack(expand=True)

    def load_stats(self):
        """Cargar estadísticas"""
        pass


class ConfigWindow:
    def __init__(self, parent, config_data):
        self.parent = parent
        self.config = config_data.copy()
        self.window = tk.Toplevel(parent.root)
        self.setup_window()
        self.setup_ui()

    def setup_window(self):
        """Configurar ventana de configuración"""
        self.window.title("Configuración - Star Citizen Log Monitor")
        self.window.geometry("550x750")
        self.window.configure(bg='#1a1a1a')
        self.window.resizable(False, False)

        # Configurar icono
        try:
            icon_path = get_resource_path('logoStar.ico')
            if os.path.exists(icon_path):
                self.window.iconbitmap(icon_path)
        except:
            pass

        # Hacer modal
        self.window.transient(self.parent.root)
        self.window.grab_set()

        # Centrar en la pantalla
        self.window.geometry("+{}+{}".format(
            (self.window.winfo_screenwidth() // 2) - 275,
            (self.window.winfo_screenheight() // 2) - 375
        ))

    def setup_ui(self):
        """Configurar interfaz de configuración"""
        # Frame principal con scroll
        main_frame = tk.Frame(self.window, bg='#1a1a1a')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Título
        title_label = tk.Label(main_frame, text="⚙️ Configuración", 
                             font=('Arial', 16, 'bold'),
                             bg='#1a1a1a', fg='white')
        title_label.pack(pady=(0, 20))

        # Notebook para pestañas
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Configurar estilo del notebook
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TNotebook', background='#1a1a1a')
        style.configure('TNotebook.Tab', background='#404040', foreground='white')

        # Pestañas
        self.setup_general_tab()
        self.setup_crew_tab()
        self.setup_blacklist_tab()
        self.setup_appearance_tab()
        self.setup_advanced_tab()

        # Botones
        self.setup_buttons(main_frame)

    def setup_general_tab(self):
        """Configurar pestaña general"""
        general_frame = tk.Frame(self.notebook, bg='#2a2a2a')
        self.notebook.add(general_frame, text="General")

        # Usuario actual
        user_frame = tk.LabelFrame(general_frame, text="Usuario", 
                                 bg='#2a2a2a', fg='white', font=('Arial', 10, 'bold'))
        user_frame.pack(fill=tk.X, padx=10, pady=10)

        tk.Label(user_frame, text="Tu nickname en Star Citizen:", 
               bg='#2a2a2a', fg='white').pack(anchor=tk.W, padx=5, pady=5)

        self.user_var = tk.StringVar(value=self.config.get('current_user', ''))
        self.user_entry = tk.Entry(user_frame, textvariable=self.user_var, 
                                 bg='#404040', fg='white', font=('Arial', 10))
        self.user_entry.pack(fill=tk.X, padx=5, pady=5)

        # Archivo de log
        log_frame = tk.LabelFrame(general_frame, text="Archivo de Log", 
                                bg='#2a2a2a', fg='white', font=('Arial', 10, 'bold'))
        log_frame.pack(fill=tk.X, padx=10, pady=10)

        tk.Label(log_frame, text="Ruta del archivo Game.log:", 
               bg='#2a2a2a', fg='white').pack(anchor=tk.W, padx=5, pady=5)

        log_path_frame = tk.Frame(log_frame, bg='#2a2a2a')
        log_path_frame.pack(fill=tk.X, padx=5, pady=5)

        self.log_path_var = tk.StringVar(value=self.config.get('log_filename', ''))
        self.log_path_entry = tk.Entry(log_path_frame, textvariable=self.log_path_var, 
                                     bg='#404040', fg='white', font=('Arial', 9))
        self.log_path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        browse_btn = tk.Button(log_path_frame, text="📁", command=self.browse_log_file,
                             bg='#404040', fg='white', width=3)
        browse_btn.pack(side=tk.RIGHT, padx=(5, 0))

        # Botón para detectar automáticamente
        detect_btn = tk.Button(log_frame, text="🔍 Detectar automáticamente", 
                             command=self.auto_detect_log,
                             bg='#2d5a2d', fg='white')
        detect_btn.pack(pady=5)

        # Configuración de monitoreo
        monitor_frame = tk.LabelFrame(general_frame, text="Monitoreo", 
                                    bg='#2a2a2a', fg='white', font=('Arial', 10, 'bold'))
        monitor_frame.pack(fill=tk.X, padx=10, pady=10)

        self.auto_start_var = tk.BooleanVar(value=self.config.get('auto_start', False))
        auto_start_check = tk.Checkbutton(monitor_frame, text="Iniciar monitoreo automáticamente",
                                        variable=self.auto_start_var,
                                        bg='#2a2a2a', fg='white', selectcolor='#404040')
        auto_start_check.pack(anchor=tk.W, padx=5, pady=5)

        self.save_pos_var = tk.BooleanVar(value=self.config.get('save_position', True))
        save_pos_check = tk.Checkbutton(monitor_frame, text="Recordar posición y tamaño de ventana",
                                      variable=self.save_pos_var,
                                      bg='#2a2a2a', fg='white', selectcolor='#404040')
        save_pos_check.pack(anchor=tk.W, padx=5, pady=5)

        self.show_direction_var = tk.BooleanVar(value=self.config.get('show_direction', True))
        show_direction_check = tk.Checkbutton(monitor_frame, text="Mostrar dirección del disparo",
                                            variable=self.show_direction_var,
                                            bg='#2a2a2a', fg='white', selectcolor='#404040')
        show_direction_check.pack(anchor=tk.W, padx=5, pady=5)

        self.web_info_var = tk.BooleanVar(value=self.config.get('web_info', True))
        web_info_check = tk.Checkbutton(monitor_frame, text="Obtener información de organizaciones",
                                      variable=self.web_info_var,
                                      bg='#2a2a2a', fg='white', selectcolor='#404040')
        web_info_check.pack(anchor=tk.W, padx=5, pady=5)

        self.notifications_var = tk.BooleanVar(value=self.config.get('notifications', True))
        notifications_check = tk.Checkbutton(monitor_frame, text="Mostrar notificaciones emergentes",
                                           variable=self.notifications_var,
                                           bg='#2a2a2a', fg='white', selectcolor='#404040')
        notifications_check.pack(anchor=tk.W, padx=5, pady=5)

    def setup_crew_tab(self):
        """Configurar pestaña de crew"""
        crew_frame = tk.Frame(self.notebook, bg='#2a2a2a')
        self.notebook.add(crew_frame, text="Crew")

        # Instrucciones
        tk.Label(crew_frame, text="👥 Miembros de tu Crew", 
               font=('Arial', 12, 'bold'), bg='#2a2a2a', fg='white').pack(pady=10)

        tk.Label(crew_frame, 
               text="Los miembros de tu crew aparecerán resaltados en verde.\nUno por línea:",
               bg='#2a2a2a', fg='#cccccc', justify=tk.LEFT).pack(pady=5)

        # Frame para lista de crew
        crew_list_frame = tk.Frame(crew_frame, bg='#2a2a2a')
        crew_list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Lista de crew actual
        self.crew_listbox = tk.Listbox(crew_list_frame, bg='#404040', fg='white', 
                                     font=('Arial', 10), height=8)
        self.crew_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Scrollbar para la lista
        crew_scrollbar = tk.Scrollbar(crew_list_frame, orient=tk.VERTICAL)
        crew_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.crew_listbox.config(yscrollcommand=crew_scrollbar.set)
        crew_scrollbar.config(command=self.crew_listbox.yview)

        # Cargar crew actual
        for member in self.config.get('crew_nicks', []):
            self.crew_listbox.insert(tk.END, member)

        # Frame para botones de crew
        crew_buttons_frame = tk.Frame(crew_frame, bg='#2a2a2a')
        crew_buttons_frame.pack(fill=tk.X, padx=10, pady=10)

        # Campo para añadir nuevo miembro
        add_frame = tk.Frame(crew_buttons_frame, bg='#2a2a2a')
        add_frame.pack(fill=tk.X, pady=5)

        tk.Label(add_frame, text="Añadir miembro:", bg='#2a2a2a', fg='white').pack(side=tk.LEFT)

        self.new_crew_var = tk.StringVar()
        self.new_crew_entry = tk.Entry(add_frame, textvariable=self.new_crew_var, 
                                     bg='#404040', fg='white', font=('Arial', 10))
        self.new_crew_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.new_crew_entry.bind('<Return>', lambda e: self.add_crew_member())

        add_btn = tk.Button(add_frame, text="➕", command=self.add_crew_member,
                          bg='#2d5a2d', fg='white', width=3)
        add_btn.pack(side=tk.RIGHT)

        # Botón para eliminar seleccionado
        remove_btn = tk.Button(crew_buttons_frame, text="🗑️ Eliminar seleccionado", 
                             command=self.remove_crew_member,
                             bg='#5a2d2d', fg='white')
        remove_btn.pack(pady=5)


    def setup_blacklist_tab(self):
        """Configurar pestaña de listas negras"""
        blacklist_frame = tk.Frame(self.notebook, bg='#2a2a2a')
        self.notebook.add(blacklist_frame, text="Listas")

        # Scroll para esta pestaña
        canvas = tk.Canvas(blacklist_frame, bg='#2a2a2a', highlightthickness=0)
        scrollbar = tk.Scrollbar(blacklist_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg='#2a2a2a')

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Lista negra de jugadores
        players_black_frame = tk.LabelFrame(scrollable_frame, text="🚫 Jugadores Hostiles", 
                                          bg='#2a2a2a', fg='white', font=('Arial', 10, 'bold'))
        players_black_frame.pack(fill=tk.X, padx=10, pady=10)

        self.players_blacklist = tk.Listbox(players_black_frame, bg='#404040', fg='white', 
                                          font=('Arial', 10), height=6)
        self.players_blacklist.pack(fill=tk.X, padx=5, pady=5)

        # Cargar lista negra de jugadores
        for player in self.config.get('players_blacklist', []):
            self.players_blacklist.insert(tk.END, player)

        # Controles para lista negra de jugadores
        players_black_controls = tk.Frame(players_black_frame, bg='#2a2a2a')
        players_black_controls.pack(fill=tk.X, padx=5, pady=5)

        self.new_black_player_var = tk.StringVar()
        tk.Entry(players_black_controls, textvariable=self.new_black_player_var, 
               bg='#404040', fg='white').pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(players_black_controls, text="➕", 
                command=lambda: self.add_to_list(self.players_blacklist, self.new_black_player_var),
                bg='#5a2d2d', fg='white', width=3).pack(side=tk.RIGHT, padx=(5, 0))

        tk.Button(players_black_frame, text="🗑️ Eliminar seleccionado", 
                command=lambda: self.remove_from_list(self.players_blacklist),
                bg='#5a2d2d', fg='white').pack(pady=5)

        # Lista blanca de jugadores
        players_white_frame = tk.LabelFrame(scrollable_frame, text="✅ Jugadores Amigos", 
                                          bg='#2a2a2a', fg='white', font=('Arial', 10, 'bold'))
        players_white_frame.pack(fill=tk.X, padx=10, pady=10)

        self.players_whitelist = tk.Listbox(players_white_frame, bg='#404040', fg='white', 
                                          font=('Arial', 10), height=6)
        self.players_whitelist.pack(fill=tk.X, padx=5, pady=5)

        # Cargar lista blanca de jugadores
        for player in self.config.get('players_whitelist', []):
            self.players_whitelist.insert(tk.END, player)

        # Controles para lista blanca de jugadores
        players_white_controls = tk.Frame(players_white_frame, bg='#2a2a2a')
        players_white_controls.pack(fill=tk.X, padx=5, pady=5)

        self.new_white_player_var = tk.StringVar()
        tk.Entry(players_white_controls, textvariable=self.new_white_player_var, 
               bg='#404040', fg='white').pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(players_white_controls, text="➕", 
                command=lambda: self.add_to_list(self.players_whitelist, self.new_white_player_var),
                bg='#2d5a2d', fg='white', width=3).pack(side=tk.RIGHT, padx=(5, 0))

        tk.Button(players_white_frame, text="🗑️ Eliminar seleccionado", 
                command=lambda: self.remove_from_list(self.players_whitelist),
                bg='#5a2d2d', fg='white').pack(pady=5)

        # Lista negra de organizaciones
        orgs_black_frame = tk.LabelFrame(scrollable_frame, text="🚫 Organizaciones Hostiles", 
                                       bg='#2a2a2a', fg='white', font=('Arial', 10, 'bold'))
        orgs_black_frame.pack(fill=tk.X, padx=10, pady=10)

        self.orgs_blacklist = tk.Listbox(orgs_black_frame, bg='#404040', fg='white', 
                                       font=('Arial', 10), height=6)
        self.orgs_blacklist.pack(fill=tk.X, padx=5, pady=5)

        # Cargar lista negra de organizaciones
        for org in self.config.get('orgs_blacklist', []):
            self.orgs_blacklist.insert(tk.END, org)

        # Controles para lista negra de organizaciones
        orgs_black_controls = tk.Frame(orgs_black_frame, bg='#2a2a2a')
        orgs_black_controls.pack(fill=tk.X, padx=5, pady=5)

        self.new_black_org_var = tk.StringVar()
        tk.Entry(orgs_black_controls, textvariable=self.new_black_org_var, 
               bg='#404040', fg='white').pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(orgs_black_controls, text="➕", 
                command=lambda: self.add_to_list(self.orgs_blacklist, self.new_black_org_var),
                bg='#5a2d2d', fg='white', width=3).pack(side=tk.RIGHT, padx=(5, 0))

        tk.Button(orgs_black_frame, text="🗑️ Eliminar seleccionado", 
                command=lambda: self.remove_from_list(self.orgs_blacklist),
                bg='#5a2d2d', fg='white').pack(pady=5)

        # Lista blanca de organizaciones
        orgs_white_frame = tk.LabelFrame(scrollable_frame, text="✅ Organizaciones Amigas", 
                                       bg='#2a2a2a', fg='white', font=('Arial', 10, 'bold'))
        orgs_white_frame.pack(fill=tk.X, padx=10, pady=10)

        self.orgs_whitelist = tk.Listbox(orgs_white_frame, bg='#404040', fg='white', 
                                       font=('Arial', 10), height=6)
        self.orgs_whitelist.pack(fill=tk.X, padx=5, pady=5)

        # Cargar lista blanca de organizaciones
        for org in self.config.get('orgs_whitelist', []):
            self.orgs_whitelist.insert(tk.END, org)

        # Controles para lista blanca de organizaciones
        orgs_white_controls = tk.Frame(orgs_white_frame, bg='#2a2a2a')
        orgs_white_controls.pack(fill=tk.X, padx=5, pady=5)

        self.new_white_org_var = tk.StringVar()
        tk.Entry(orgs_white_controls, textvariable=self.new_white_org_var, 
               bg='#404040', fg='white').pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(orgs_white_controls, text="➕", 
                command=lambda: self.add_to_list(self.orgs_whitelist, self.new_white_org_var),
                bg='#2d5a2d', fg='white', width=3).pack(side=tk.RIGHT, padx=(5, 0))

        tk.Button(orgs_white_frame, text="🗑️ Eliminar seleccionado", 
                command=lambda: self.remove_from_list(self.orgs_whitelist),
                bg='#5a2d2d', fg='white').pack(pady=5)

        # Empaquetar scroll
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def setup_appearance_tab(self):
        """Configurar pestaña de apariencia"""
        appearance_frame = tk.Frame(self.notebook, bg='#2a2a2a')
        self.notebook.add(appearance_frame, text="Apariencia")

        # Configuración de ventana
        window_frame = tk.LabelFrame(appearance_frame, text="Ventana", 
                                   bg='#2a2a2a', fg='white', font=('Arial', 10, 'bold'))
        window_frame.pack(fill=tk.X, padx=10, pady=10)

        # Transparencia
        transparency_frame = tk.Frame(window_frame, bg='#2a2a2a')
        transparency_frame.pack(fill=tk.X, padx=5, pady=5)

        tk.Label(transparency_frame, text="Transparencia:", 
               bg='#2a2a2a', fg='white').pack(side=tk.LEFT)

        self.transparency_var = tk.DoubleVar(value=self.config.get('transparency', 0.9))
        transparency_scale = tk.Scale(transparency_frame, variable=self.transparency_var,
                                    from_=0.3, to=1.0, resolution=0.1, orient=tk.HORIZONTAL,
                                    bg='#2a2a2a', fg='white', highlightthickness=0)
        transparency_scale.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=5)

        # Tamaño de fuente
        font_frame = tk.Frame(window_frame, bg='#2a2a2a')
        font_frame.pack(fill=tk.X, padx=5, pady=5)

        tk.Label(font_frame, text="Tamaño de fuente:", 
               bg='#2a2a2a', fg='white').pack(side=tk.LEFT)

        self.font_size_var = tk.IntVar(value=self.config.get('font_size', 10))
        font_size_spin = tk.Spinbox(font_frame, textvariable=self.font_size_var,
                                  from_=8, to=16, bg='#404040', fg='white', width=5)
        font_size_spin.pack(side=tk.RIGHT)

        # Tema de colores
        theme_frame = tk.Frame(window_frame, bg='#2a2a2a')
        theme_frame.pack(fill=tk.X, padx=5, pady=5)

        tk.Label(theme_frame, text="Tema:", bg='#2a2a2a', fg='white').pack(side=tk.LEFT)

        self.theme_var = tk.StringVar(value=self.config.get('theme', 'dark'))
        theme_combo = ttk.Combobox(theme_frame, textvariable=self.theme_var,
                                 values=['dark', 'light', 'blue'], state='readonly', width=10)
        theme_combo.pack(side=tk.RIGHT)

        # Configuración de overlay
        overlay_frame = tk.LabelFrame(appearance_frame, text="Modo Overlay", 
                                    bg='#2a2a2a', fg='white', font=('Arial', 10, 'bold'))
        overlay_frame.pack(fill=tk.X, padx=10, pady=10)

        # Posición predeterminada
        pos_frame = tk.Frame(overlay_frame, bg='#2a2a2a')
        pos_frame.pack(fill=tk.X, padx=5, pady=5)

        tk.Label(pos_frame, text="Posición predeterminada:", 
               bg='#2a2a2a', fg='white').pack(side=tk.LEFT)

        self.overlay_pos_var = tk.StringVar(value=self.config.get('overlay_position', 'top'))
        pos_combo = ttk.Combobox(pos_frame, textvariable=self.overlay_pos_var,
                               values=['top', 'bottom', 'left', 'right', 'center'],
                               state='readonly', width=10)
        pos_combo.pack(side=tk.RIGHT)

        # Configuración de colores
        colors_frame = tk.LabelFrame(appearance_frame, text="Colores", 
                                   bg='#2a2a2a', fg='white', font=('Arial', 10, 'bold'))
        colors_frame.pack(fill=tk.X, padx=10, pady=10)

        # Mostrar colores actuales
        color_info = tk.Label(colors_frame, 
                            text="🟡 Tu usuario  🟢 Crew/Amigos  🔴 Enemigos  🟠 Neutrales  🔵 Sistema",
                            bg='#2a2a2a', fg='white', font=('Arial', 9))
        color_info.pack(pady=5)


    def setup_advanced_tab(self):
        """Configurar pestaña avanzada"""
        advanced_frame = tk.Frame(self.notebook, bg='#2a2a2a')
        self.notebook.add(advanced_frame, text="Avanzado")

        # Configuración de filtros
        filters_frame = tk.LabelFrame(advanced_frame, text="Filtros de Eventos", 
                                    bg='#2a2a2a', fg='white', font=('Arial', 10, 'bold'))
        filters_frame.pack(fill=tk.X, padx=10, pady=10)

        self.show_deaths_var = tk.BooleanVar(value=self.config.get('show_deaths', True))
        deaths_check = tk.Checkbutton(filters_frame, text="Mostrar muertes",
                                    variable=self.show_deaths_var,
                                    bg='#2a2a2a', fg='white', selectcolor='#404040')
        deaths_check.pack(anchor=tk.W, padx=5, pady=2)

        self.show_missiles_var = tk.BooleanVar(value=self.config.get('show_missiles', True))
        missiles_check = tk.Checkbutton(filters_frame, text="Mostrar ataques con misiles",
                                      variable=self.show_missiles_var,
                                      bg='#2a2a2a', fg='white', selectcolor='#404040')
        missiles_check.pack(anchor=tk.W, padx=5, pady=2)

        self.show_vehicles_var = tk.BooleanVar(value=self.config.get('show_vehicles', True))
        vehicles_check = tk.Checkbutton(filters_frame, text="Mostrar destrucción de vehículos",
                                      variable=self.show_vehicles_var,
                                      bg='#2a2a2a', fg='white', selectcolor='#404040')
        vehicles_check.pack(anchor=tk.W, padx=5, pady=2)

        self.show_spawns_var = tk.BooleanVar(value=self.config.get('show_spawns', True))
        spawns_check = tk.Checkbutton(filters_frame, text="Mostrar apariciones de jugadores",
                                    variable=self.show_spawns_var,
                                    bg='#2a2a2a', fg='white', selectcolor='#404040')
        spawns_check.pack(anchor=tk.W, padx=5, pady=2)

        # Configuración de rendimiento
        performance_frame = tk.LabelFrame(advanced_frame, text="Rendimiento", 
                                        bg='#2a2a2a', fg='white', font=('Arial', 10, 'bold'))
        performance_frame.pack(fill=tk.X, padx=10, pady=10)

        # Intervalo de actualización
        update_frame = tk.Frame(performance_frame, bg='#2a2a2a')
        update_frame.pack(fill=tk.X, padx=5, pady=5)

        tk.Label(update_frame, text="Intervalo de actualización (ms):", 
               bg='#2a2a2a', fg='white').pack(side=tk.LEFT)

        self.update_interval_var = tk.IntVar(value=self.config.get('update_interval', 500))
        update_spin = tk.Spinbox(update_frame, textvariable=self.update_interval_var,
                               from_=100, to=2000, increment=100, bg='#404040', fg='white', width=8)
        update_spin.pack(side=tk.RIGHT)

        # Límite de mensajes
        msg_limit_frame = tk.Frame(performance_frame, bg='#2a2a2a')
        msg_limit_frame.pack(fill=tk.X, padx=5, pady=5)

        tk.Label(msg_limit_frame, text="Límite de mensajes en pantalla:", 
               bg='#2a2a2a', fg='white').pack(side=tk.LEFT)

        self.msg_limit_var = tk.IntVar(value=self.config.get('message_limit', 1000))
        msg_limit_spin = tk.Spinbox(msg_limit_frame, textvariable=self.msg_limit_var,
                                  from_=100, to=5000, increment=100, bg='#404040', fg='white', width=8)
        msg_limit_spin.pack(side=tk.RIGHT)

        # Configuración de base de datos
        db_frame = tk.LabelFrame(advanced_frame, text="Base de Datos", 
                               bg='#2a2a2a', fg='white', font=('Arial', 10, 'bold'))
        db_frame.pack(fill=tk.X, padx=10, pady=10)

        self.save_stats_var = tk.BooleanVar(value=self.config.get('save_stats', True))
        stats_check = tk.Checkbutton(db_frame, text="Guardar estadísticas en base de datos",
                                   variable=self.save_stats_var,
                                   bg='#2a2a2a', fg='white', selectcolor='#404040')
        stats_check.pack(anchor=tk.W, padx=5, pady=2)

        self.cache_players_var = tk.BooleanVar(value=self.config.get('cache_players', True))
        cache_check = tk.Checkbutton(db_frame, text="Cachear información de jugadores",
                                   variable=self.cache_players_var,
                                   bg='#2a2a2a', fg='white', selectcolor='#404040')
        cache_check.pack(anchor=tk.W, padx=5, pady=2)

        # Botones de mantenimiento
        maintenance_frame = tk.Frame(db_frame, bg='#2a2a2a')
        maintenance_frame.pack(fill=tk.X, padx=5, pady=10)

        clear_cache_btn = tk.Button(maintenance_frame, text="🗑️ Limpiar Cache", 
                                  command=self.clear_cache,
                                  bg='#5a2d2d', fg='white')
        clear_cache_btn.pack(side=tk.LEFT, padx=(0, 5))

        export_stats_btn = tk.Button(maintenance_frame, text="📊 Exportar Estadísticas", 
                                   command=self.export_stats,
                                   bg='#2d4a5a', fg='white')
        export_stats_btn.pack(side=tk.LEFT)

    def add_to_list(self, listbox, var):
        """Añadir elemento a lista"""
        item = var.get().strip()
        if item:
            listbox.insert(tk.END, item)
            var.set("")

    def remove_from_list(self, listbox):
        """Eliminar elemento de lista"""
        selection = listbox.curselection()
        if selection:
            listbox.delete(selection[0])

    def get_list_items(self, listbox):
        """Obtener items de una lista"""
        return [listbox.get(i) for i in range(listbox.size())]

    def setup_buttons(self, parent):
        """Configurar botones principales"""
        buttons_frame = tk.Frame(parent, bg='#1a1a1a')
        buttons_frame.pack(fill=tk.X, pady=10)

        # Botón cancelar
        cancel_btn = tk.Button(buttons_frame, text="❌ Cancelar", 
                             command=self.cancel,
                             bg='#5a2d2d', fg='white', width=12)
        cancel_btn.pack(side=tk.LEFT, padx=5)

        # Botón aplicar
        apply_btn = tk.Button(buttons_frame, text="✅ Aplicar", 
                            command=self.apply_config,
                            bg='#2d5a2d', fg='white', width=12)
        apply_btn.pack(side=tk.LEFT, padx=5)

        # Botón guardar y cerrar
        save_btn = tk.Button(buttons_frame, text="💾 Guardar", 
                           command=self.save_and_close,
                           bg='#2d4a5a', fg='white', width=12)
        save_btn.pack(side=tk.RIGHT, padx=5)

        # Botón restaurar predeterminados
        reset_btn = tk.Button(buttons_frame, text="🔄 Restaurar", 
                            command=self.restore_defaults,
                            bg='#404040', fg='white', width=12)
        reset_btn.pack(side=tk.RIGHT, padx=5)

    def browse_log_file(self):
        """Navegar para seleccionar archivo de log"""
        filename = filedialog.askopenfilename(
            title="Seleccionar archivo Game.log",
            filetypes=[("Log files", "*.log"), ("All files", "*.*")],
            initialdir=os.path.dirname(self.log_path_var.get()) if self.log_path_var.get() else None
        )
        if filename:
            self.log_path_var.set(filename)

    def auto_detect_log(self):
        """Detectar automáticamente el archivo de log"""
        possible_paths = [
            r'C:\Program Files\Roberts Space Industries\StarCitizen\LIVE\Game.log',
            r'C:\Program Files\Roberts Space Industries\StarCitizen\PTU\Game.log',
            r'D:\Program Files\Roberts Space Industries\StarCitizen\LIVE\Game.log',
            r'D:\Program Files\Roberts Space Industries\StarCitizen\PTU\Game.log',
            r'E:\Program Files\Roberts Space Industries\StarCitizen\LIVE\Game.log',
            r'F:\Program Files\Roberts Space Industries\StarCitizen\LIVE\Game.log'
        ]

        # También buscar en carpetas de usuario
        user_profile = os.path.expanduser("~")
        possible_paths.extend([
            os.path.join(user_profile, "Documents", "StarCitizen", "LIVE", "Game.log"),
            os.path.join(user_profile, "Documents", "StarCitizen", "PTU", "Game.log")
        ])

        for path in possible_paths:
            if os.path.exists(path):
                self.log_path_var.set(path)
                messagebox.showinfo("Detectado", f"Archivo de log encontrado:\n{path}")
                return

        messagebox.showwarning("No encontrado", 
                             "No se pudo detectar automáticamente el archivo de log.\n"
                             "Selecciónalo manualmente con el botón 📁")

    def add_crew_member(self):
        """Añadir miembro al crew"""
        member = self.new_crew_var.get().strip()
        if member and member not in self.get_crew_list():
            self.crew_listbox.insert(tk.END, member)
            self.new_crew_var.set("")

    def remove_crew_member(self):
        """Eliminar miembro seleccionado del crew"""
        selection = self.crew_listbox.curselection()
        if selection:
            self.crew_listbox.delete(selection[0])

    def get_crew_list(self):
        """Obtener lista actual de crew"""
        return [self.crew_listbox.get(i) for i in range(self.crew_listbox.size())]

    def clear_cache(self):
        """Limpiar cache de jugadores"""
        if messagebox.askyesno("Confirmar", "¿Limpiar cache de jugadores?"):
            try:
                if hasattr(self.parent, 'db_manager'):
                    # Limpiar cache en base de datos
                    with sqlite3.connect(self.parent.db_manager.db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM players")
                        conn.commit()

                # Limpiar cache en memoria
                self.parent.player_info_cache.clear()
                messagebox.showinfo("Completado", "Cache limpiado correctamente")
            except Exception as e:
                messagebox.showerror("Error", f"Error limpiando cache: {e}")

    def export_stats(self):
        """Exportar estadísticas a archivo"""
        try:
            filename = filedialog.asksaveasfilename(
                title="Exportar estadísticas",
                defaultextension=".json",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
            )

            if filename and hasattr(self.parent, 'db_manager'):
                with sqlite3.connect(self.parent.db_manager.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT * FROM stats")
                    stats_data = cursor.fetchall()

                    export_data = {
                        'export_date': datetime.now().isoformat(),
                        'stats': [
                            {
                                'date': row[0],
                                'player': row[1],
                                'kills': row[2],
                                'deaths': row[3],
                                'vehicles_destroyed': row[4],
                                'missiles_fired': row[5]
                            }
                            for row in stats_data
                        ]
                    }

                    with open(filename, 'w') as f:
                        json.dump(export_data, f, indent=2)

                    messagebox.showinfo("Completado", f"Estadísticas exportadas a {filename}")
        except Exception as e:
            messagebox.showerror("Error", f"Error exportando estadísticas: {e}")

    def apply_config(self):
        """Aplicar configuración sin cerrar ventana"""
        self.save_config()
        self.parent.apply_config(self.config)
        messagebox.showinfo("Aplicado", "Configuración aplicada correctamente")

    def save_and_close(self):
        """Guardar configuración y cerrar ventana"""
        self.save_config()
        self.parent.apply_config(self.config)
        self.window.destroy()

    def save_config(self):
        """Guardar configuración actual"""
        self.config.update({
            'current_user': self.user_var.get().strip(),
            'log_filename': self.log_path_var.get().strip(),
            'crew_nicks': self.get_crew_list(),
            'players_blacklist': self.get_list_items(self.players_blacklist),
            'players_whitelist': self.get_list_items(self.players_whitelist),
            'orgs_blacklist': self.get_list_items(self.orgs_blacklist),
            'orgs_whitelist': self.get_list_items(self.orgs_whitelist),
            'auto_start': self.auto_start_var.get(),
            'save_position': self.save_pos_var.get(),
            'show_direction': self.show_direction_var.get(),
            'web_info': self.web_info_var.get(),
            'notifications': self.notifications_var.get(),
            'transparency': self.transparency_var.get(),
            'font_size': self.font_size_var.get(),
            'theme': self.theme_var.get(),
            'overlay_position': self.overlay_pos_var.get(),
            'show_deaths': self.show_deaths_var.get(),
            'show_missiles': self.show_missiles_var.get(),
            'show_vehicles': self.show_vehicles_var.get(),
            'show_spawns': self.show_spawns_var.get(),
            'update_interval': self.update_interval_var.get(),
            'message_limit': self.msg_limit_var.get(),
            'save_stats': self.save_stats_var.get(),
            'cache_players': self.cache_players_var.get()
        })

    def restore_defaults(self):
        """Restaurar valores predeterminados"""
        if messagebox.askyesno("Restaurar", "¿Restaurar configuración predeterminada?"):
            defaults = {
                'current_user': 'kosako17',
                'log_filename': r'D:\Roberts Space Industries\StarCitizen\LIVE\Game.log',
                'crew_nicks': [],
                'players_blacklist': [],
                'players_whitelist': [],
                'orgs_blacklist': [],
                'orgs_whitelist': [],
                'auto_start': False,
                'save_position': True,
                'show_direction': True,
                'web_info': True,
                'notifications': True,
                'transparency': 0.9,
                'font_size': 10,
                'theme': 'dark',
                'overlay_position': 'top',
                'show_deaths': True,
                'show_missiles': True,
                'show_vehicles': True,
                'show_spawns': True,
                'update_interval': 500,
                'message_limit': 1000,
                'save_stats': True,
                'cache_players': True
            }

            # Actualizar UI
            self.user_var.set(defaults['current_user'])
            self.log_path_var.set(defaults['log_filename'])
            self.auto_start_var.set(defaults['auto_start'])
            self.save_pos_var.set(defaults['save_position'])
            self.show_direction_var.set(defaults['show_direction'])
            self.web_info_var.set(defaults['web_info'])
            self.notifications_var.set(defaults['notifications'])
            self.transparency_var.set(defaults['transparency'])
            self.font_size_var.set(defaults['font_size'])
            self.theme_var.set(defaults['theme'])
            self.overlay_pos_var.set(defaults['overlay_position'])
            self.show_deaths_var.set(defaults['show_deaths'])
            self.show_missiles_var.set(defaults['show_missiles'])
            self.show_vehicles_var.set(defaults['show_vehicles'])
            self.show_spawns_var.set(defaults['show_spawns'])
            self.update_interval_var.set(defaults['update_interval'])
            self.msg_limit_var.set(defaults['message_limit'])
            self.save_stats_var.set(defaults['save_stats'])
            self.cache_players_var.set(defaults['cache_players'])

            # Limpiar listas
            self.crew_listbox.delete(0, tk.END)
            self.players_blacklist.delete(0, tk.END)
            self.players_whitelist.delete(0, tk.END)
            self.orgs_blacklist.delete(0, tk.END)
            self.orgs_whitelist.delete(0, tk.END)

    def cancel(self):
        """Cancelar y cerrar ventana"""
        self.window.destroy()


class StarCitizenLogMonitor:
    def __init__(self):
        self.root = tk.Tk()
        self.load_config()
        self.setup_database()
        self.setup_window()
        self.setup_variables()
        self.setup_ui()
        self.setup_monitoring()
        self.setup_notifications()

        # Auto-start si está configurado
        if self.config.get('auto_start', False):
            self.root.after(1000, self.start_monitoring)

    def save_config(self):
        try:
            with open("sc_monitor_config.json", "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            logger.info("Configuración guardada correctamente")
        except Exception as e:
            logger.error(f"Error guardando configuración: {e}")

    def setup_database(self):
        """Configurar base de datos"""
        try:
            self.db_manager = DatabaseManager()
        except Exception as e:
            logger.error(f"Error configurando base de datos: {e}")
            self.db_manager = None

    def setup_notifications(self):
        """Configurar sistema de notificaciones"""
        self.notification_system = NotificationSystem(self)

    def load_logo(self):
        """Cargar el logo de la aplicación"""
        try:
            # Intentar cargar PNG primero
            png_path = get_resource_path('logoStar.png')
            if os.path.exists(png_path):
                image = Image.open(png_path)
                image = image.resize((32, 32), Image.Resampling.LANCZOS)
                self.logo = ImageTk.PhotoImage(image)
                return True

            # Si no hay PNG, intentar ICO
            ico_path = get_resource_path('logoStar.ico')
            if os.path.exists(ico_path):
                image = Image.open(ico_path)
                image = image.resize((32, 32), Image.Resampling.LANCZOS)
                self.logo = ImageTk.PhotoImage(image)
                return True

        except Exception as e:
            logger.error(f"Error cargando logo: {e}")

        return False

    def load_config(self):
        """Cargar configuración desde archivo"""
        self.config = {
            'current_user': 'Por defecto',
            'log_filename': r'C:\Program Files\Roberts Space Industries\StarCitizen\LIVE\Game.log',
            'crew_nicks': [],
            'players_blacklist': [],
            'players_whitelist': [],
            'orgs_blacklist': [],
            'orgs_whitelist': [],
            'auto_start': False,
            'save_position': True,
            'show_direction': True,
            'web_info': True,
            'notifications': True,
            'transparency': 0.9,
            'font_size': 10,
            'theme': 'dark',
            'overlay_position': 'top',
            'window_geometry': '900x250+100+100',
            'overlay_geometry': '800x120+100+10',
            'show_deaths': True,
            'show_missiles': True,
            'show_vehicles': True,
            'show_spawns': True,
            'update_interval': 500,
            'message_limit': 1000,
            'save_stats': True,
            'cache_players': True
        }

        try:
            if os.path.exists("sc_monitor_config.json"):
                with open("sc_monitor_config.json", 'r') as f:
                    saved_config = json.load(f)
                    self.config.update(saved_config)
        except Exception as e:
            logger.error(f"Error cargando configuración: {e}")

    def setup_window(self):
        """Configurar la ventana principal"""
        self.root.title("Star Citizen Log Monitor v2.0")

        # Configurar icono de la ventana y barra de tareas
        try:
            # Obtener ruta correcta del icono
            icon_path = get_resource_path('logoStar.ico')

            # Para Windows - icono en barra de tareas y ventana
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
                logger.info("Icono configurado correctamente")
            else:
                logger.warning("Archivo de icono no encontrado")

            # Cargar logo para UI si existe
            if self.load_logo():
                # También usar como icono de ventana (alternativo)
                self.root.iconphoto(False, self.logo)
                logger.info("Logo cargado para UI")
        except Exception as e:
            logger.error(f"Error configurando icono: {e}")

        # Aplicar geometría guardada
        geometry = self.config.get('window_geometry', '900x250+100+100')
        self.root.geometry(geometry)

        self.root.configure(bg='#1a1a1a')

        # Aplicar transparencia
        transparency = self.config.get('transparency', 0.9)
        self.root.wm_attributes("-alpha", transparency)

        # Permitir redimensionar
        self.root.resizable(True, True)

        # Configurar para cerrar correctamente
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Guardar posición cuando se mueva/redimensione
        if self.config.get('save_position', True):
            self.root.bind('<Configure>', self.on_window_configure)

    def setup_variables(self):
        """Configurar variables del monitor"""
        self.player_info_cache = {}
        self.messages_shown = set()
        self.message_queue = queue.Queue()
        self.monitoring = False
        self.monitor_thread = None
        self.last_file_position = 0
        self.message_count = 0

        # Variables de la configuración
        self.CURRENT_USER = self.config.get('current_user', 'Por defecto')
        self.LOG_FILENAME = self.config.get('log_filename', r'C:\Program Files\Roberts Space Industries\StarCitizen\LIVE\Game.log')
        self.CREW_NICKS = self.config.get('crew_nicks', [])
        self.PLAYERS_BLACKLIST = self.config.get('players_blacklist', [])
        self.PLAYERS_WHITELIST = self.config.get('players_whitelist', [])
        self.ORGS_BLACKLIST = self.config.get('orgs_blacklist', [])
        self.ORGS_WHITELIST = self.config.get('orgs_whitelist', [])

        # Colores ANSI (para uso interno)
        self.GREEN = "\033[92m"
        self.YELLOW = "\033[93m"
        self.RED = "\033[91m"
        self.RESET = "\033[0m"

    def setup_ui(self):
        """Configurar la interfaz de usuario"""
        # Frame principal
        main_frame = tk.Frame(self.root, bg='#1a1a1a')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        header_frame = tk.Frame(main_frame, bg='#1a1a1a')
        header_frame.pack(fill=tk.X, pady=(0, 5))

        # Añadir logo al header si existe
        if hasattr(self, 'logo'):
            logo_label = tk.Label(header_frame, image=self.logo, bg='#1a1a1a')
            logo_label.pack(side=tk.LEFT, padx=(0, 10))

        # Título con versión
        title_label = tk.Label(header_frame, text="Star Citizen Log Monitor v2.0", 
                             font=('Arial', 14, 'bold'), bg='#1a1a1a', fg='white')
        title_label.pack(side=tk.LEFT)

        # Estado de conexión
        self.status_label = tk.Label(header_frame, text="● Desconectado", 
                                   font=('Arial', 10), bg='#1a1a1a', fg='#ff0000')
        self.status_label.pack(side=tk.RIGHT)

        # Frame de controles
        control_frame = tk.Frame(main_frame, bg='#1a1a1a')
        control_frame.pack(fill=tk.X, pady=(0, 5))

        # Botones de control
        self.start_button = tk.Button(control_frame, text="▶ Iniciar", 
            command=self.start_monitoring,
            bg='#2d5a2d', fg='white', relief=tk.FLAT, width=10)
        self.start_button.pack(side=tk.LEFT, padx=(0, 5))

        self.stop_button = tk.Button(control_frame, text="⏹ Detener", 
            command=self.stop_monitoring,
            bg='#5a2d2d', fg='white', relief=tk.FLAT, width=10,
            state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=(0, 5))

        self.clear_button = tk.Button(control_frame, text="🗑 Limpiar", 
            command=self.clear_messages,
            bg='#404040', fg='white', relief=tk.FLAT, width=10)
        self.clear_button.pack(side=tk.LEFT, padx=(0, 5))

        # Botón de configuración
        self.config_button = tk.Button(control_frame, text="⚙️ Config", 
            command=self.open_config,
            bg='#404040', fg='white', relief=tk.FLAT, width=10)
        self.config_button.pack(side=tk.LEFT, padx=(0, 5))

        # Botón de estadísticas
        self.stats_button = tk.Button(control_frame, text="📊 Stats", 
            command=self.open_stats,
            bg='#404040', fg='white', relief=tk.FLAT, width=10)
        self.stats_button.pack(side=tk.LEFT, padx=(0, 5))

        # Checkbox para overlay mode
        self.overlay_var = tk.BooleanVar()
        self.overlay_check = tk.Checkbutton(control_frame, text="Modo Overlay", 
            variable=self.overlay_var,
            command=self.toggle_overlay_mode,
            bg='#1a1a1a', fg='white', 
            selectcolor='#404040')
        self.overlay_check.pack(side=tk.LEFT, padx=(10, 0))

        # Frame para información rápida
        info_frame = tk.Frame(control_frame, bg='#1a1a1a')
        info_frame.pack(side=tk.RIGHT)

        tk.Label(info_frame, text="Usuario:", bg='#1a1a1a', fg='white').pack(side=tk.LEFT)
        self.user_label = tk.Label(info_frame, text=self.CURRENT_USER, 
                                 bg='#1a1a1a', fg='#ffff00', font=('Arial', 10, 'bold'))
        self.user_label.pack(side=tk.LEFT, padx=(2, 10))

        tk.Label(info_frame, text="Crew:", bg='#1a1a1a', fg='white').pack(side=tk.LEFT)
        crew_count = len(self.CREW_NICKS)
        self.crew_label = tk.Label(info_frame, text=f"{crew_count} miembros", 
                                 bg='#1a1a1a', fg='#00ff00', font=('Arial', 10, 'bold'))
        self.crew_label.pack(side=tk.LEFT, padx=(2, 10))

        # Contador de mensajes
        self.msg_count_label = tk.Label(info_frame, text="Mensajes: 0", 
                                      bg='#1a1a1a', fg='#cccccc', font=('Arial', 9))
        self.msg_count_label.pack(side=tk.LEFT, padx=(2, 0))

        # Área de mensajes
        self.setup_message_area(main_frame)

    def setup_message_area(self, parent):
        """Configurar el área de mensajes"""
        # Frame para el área de mensajes
        message_frame = tk.Frame(parent, bg='#1a1a1a')
        message_frame.pack(fill=tk.BOTH, expand=True)

        # Texto con scroll
        font_size = self.config.get('font_size', 10)
        self.text_area = scrolledtext.ScrolledText(
            message_frame,
            wrap=tk.WORD,
            bg='#2a2a2a',
            fg='#ffffff',
            insertbackground='white',
            font=('Consolas', font_size),
            height=10
        )
        self.text_area.pack(fill=tk.BOTH, expand=True)

        # Configurar tags para colores
        self.text_area.tag_configure("user", foreground="#ffff00")      # Amarillo
        self.text_area.tag_configure("crew", foreground="#00ff00")      # Verde
        self.text_area.tag_configure("enemy", foreground="#ff0000")     # Rojo
        self.text_area.tag_configure("friendly", foreground="#00ff00")  # Verde
        self.text_area.tag_configure("neutral", foreground="#ffa500")   # Naranja
        self.text_area.tag_configure("info", foreground="#00ffff")      # Cyan
        self.text_area.tag_configure("timestamp", foreground="#888888") # Gris
        self.text_area.tag_configure("warning", foreground="#ff8800")   # Naranja oscuro
        self.text_area.tag_configure("success", foreground="#88ff88")   # Verde claro

        # Configurar menú contextual
        self.setup_context_menu()

    def setup_context_menu(self):
        """Configurar menú contextual para el área de texto"""
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Copiar", command=self.copy_text)
        self.context_menu.add_command(label="Seleccionar todo", command=self.select_all_text)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Limpiar", command=self.clear_messages)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Exportar log", command=self.export_log)

        # Bind del menú contextual
        self.text_area.bind("<Button-3>", self.show_context_menu)

    def show_context_menu(self, event):
        """Mostrar menú contextual"""
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def copy_text(self):
        """Copiar texto seleccionado"""
        try:
            selected_text = self.text_area.selection_get()
            self.root.clipboard_clear()
            self.root.clipboard_append(selected_text)
        except tk.TclError:
            pass

    def select_all_text(self):
        """Seleccionar todo el texto"""
        self.text_area.tag_add(tk.SEL, "1.0", tk.END)
        self.text_area.mark_set(tk.INSERT, "1.0")
        self.text_area.see(tk.INSERT)

    def export_log(self):
        """Exportar log actual a archivo"""
        try:
            filename = filedialog.asksaveasfilename(
                title="Exportar log",
                defaultextension=".txt",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
            )

            if filename:
                content = self.text_area.get("1.0", tk.END)
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(content)

                self.add_message(f"Log exportado a {filename}", "success")

                if self.config.get('notifications', True):
                    self.notification_system.show_notification(
                        "Exportación completada",
                        f"Log guardado en {os.path.basename(filename)}",
                        "success"
                    )
        except Exception as e:
            logger.error(f"Error exportando log: {e}")
            messagebox.showerror("Error", f"Error exportando log: {e}")

    def setup_monitoring(self):
        """Configurar el sistema de monitoreo"""
        # Iniciar el procesador de mensajes
        update_interval = self.config.get('update_interval', 100)
        self.root.after(update_interval, self.process_message_queue)


    def open_config(self):
        """Abrir ventana de configuración"""
        config_window = ConfigWindow(self, self.config)

    def open_stats(self):
        """Abrir ventana de estadísticas"""
        if self.db_manager:
            stats_window = StatsWindow(self, self.db_manager)
        else:
            messagebox.showwarning("Base de datos no disponible", 
                                 "No se puede acceder a las estadísticas sin base de datos")

    def apply_config(self, new_config):
        """Aplicar nueva configuración"""
        self.config.update(new_config)
        self.save_config()

        # Actualizar variables
        self.CURRENT_USER = self.config.get('current_user', 'Por defecto')
        self.LOG_FILENAME = self.config.get('log_filename', '')
        self.CREW_NICKS = self.config.get('crew_nicks', [])
        self.PLAYERS_BLACKLIST = self.config.get('players_blacklist', [])
        self.PLAYERS_WHITELIST = self.config.get('players_whitelist', [])
        self.ORGS_BLACKLIST = self.config.get('orgs_blacklist', [])
        self.ORGS_WHITELIST = self.config.get('orgs_whitelist', [])

        # Actualizar UI
        self.user_label.config(text=self.CURRENT_USER)
        crew_count = len(self.CREW_NICKS)
        self.crew_label.config(text=f"{crew_count} miembros")

        # Aplicar transparencia
        transparency = self.config.get('transparency', 0.9)
        self.root.wm_attributes("-alpha", transparency)

        # Aplicar tamaño de fuente
        font_size = self.config.get('font_size', 10)
        self.text_area.config(font=('Consolas', font_size))

        # Guardar configuración
        self.save_config()

        self.add_message("Configuración aplicada correctamente", "info")

    def get_actor_info(self, actor_name, actor_id=None):
        """Obtener información mejorada del actor"""
        if actor_id and actor_id in actor_name:
            # Es un PNJ, limpiar nombre
            return actor_name[:-(len(actor_id)+1)]
        else:
            # Verificar si es un PNJ con patrón
            match = re.search(r"(.+)_\d{6,14}", actor_name)
            if match:
                return match.group(1)
            else:
                # Es un jugador real, obtener info web si está habilitado
                return self.get_web_info(actor_name)

    def get_web_info(self, player_handle):
        """Obtener información web del jugador"""
        if not self.config.get('web_info', True):
            return player_handle

        # Verificar cache en memoria primero
        if player_handle in self.player_info_cache:
            player_info = self.player_info_cache[player_handle]
        else:
            # Verificar cache en base de datos
            if self.db_manager and self.config.get('cache_players', True):
                player_info = self.db_manager.get_player_info(player_handle)
                if player_info:
                    # Convertir a dict para compatibilidad
                    player_info = {
                        "mainOrgName": player_info.main_org_name,
                        "mainOrg": player_info.main_org,
                        "orgRang": player_info.org_rank,
                        "enlisted": player_info.enlisted,
                        "location": player_info.location,
                        "fluency": player_info.fluency
                    }
                else:
                    # Obtener información de la web
                    player_info = self.fetch_player_info(player_handle)

                    # Guardar en base de datos
                    if self.db_manager and player_info:
                        db_player_info = PlayerInfo(
                            handle=player_handle,
                            main_org=player_info.get("mainOrg", ""),
                            main_org_name=player_info.get("mainOrgName", ""),
                            org_rank=player_info.get("orgRang", ""),
                            enlisted=player_info.get("enlisted", ""),
                            location=player_info.get("location", ""),
                            fluency=player_info.get("fluency", "")
                        )
                        self.db_manager.save_player_info(db_player_info)
            else:
                # Obtener información de la web directamente
                player_info = self.fetch_player_info(player_handle)

            # Guardar en cache de memoria
            self.player_info_cache[player_handle] = player_info

        # Determinar color y información adicional
        return self.format_player_info(player_handle, player_info)

    def fetch_player_info(self, player_handle):
        """Obtener información del jugador desde RSI con timeout mejorado"""
        player_info = {
            "mainOrgName": "",
            "mainOrg": "",
            "orgRang": "",
            "enlisted": "",
            "location": "",
            "fluency": ""
        }

        try:
            url = f"https://robertsspaceindustries.com/en/citizens/{player_handle}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            resp = requests.get(url, timeout=10, headers=headers)

            if resp.status_code == 200:
                text = resp.text

                # Extraer información de la organización con patrones mejorados
                patterns = {
                    'mainOrg': r'(?s)<span class="label data\d+">Spectrum Identification \(SID\)</span>.+<strong class="value data\d+">(\w+)</strong>',
                    'mainOrgName': r'(?s)<a href="\/orgs\/[\w\d]+" class="value data\d+" style="background-position:-\d+px center">\s*([\w\d\s]+)\s*</a>',
                    'enlisted': r'(?s)<span class="label">Enlisted</span>[\s]+<strong class="value">\s*([\w\d\s]+, \d{4})\s*</strong>',
                    'fluency': r'(?s)<span class="label">Fluency</span>[\s]+<strong class="value">\s*([\w\d\s,]+[\w\d])\s*</strong>'
                }

                for key, pattern in patterns.items():
                    match = re.search(pattern, text)
                    if match:
                        value = match.group(1).strip()
                        if key == 'fluency':
                            value = value.replace(' ', '')
                        player_info[key] = value

        except requests.exceptions.Timeout:
            logger.warning(f"Timeout obteniendo info de {player_handle}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"Error de red obteniendo info de {player_handle}: {e}")
        except Exception as e:
            logger.error(f"Error inesperado obteniendo info de {player_handle}: {e}")

        return player_info

    def format_player_info(self, player_handle, player_info):
        """Formatear información del jugador con colores"""
        # Información adicional
        info_parts = []
        if player_info.get("mainOrg"):
            org_info = player_info['mainOrg']
            if player_info.get("mainOrgName"):
                org_info += f"-{player_info['mainOrgName']}"
            info_parts.append(org_info)

        if player_info.get("enlisted"):
            info_parts.append(player_info["enlisted"])
        if player_info.get("fluency"):
            info_parts.append(player_info["fluency"])

        info_text = f" [{' | '.join(info_parts)}]" if info_parts else ""

        # Determinar tipo de jugador
        if player_handle.upper() == self.CURRENT_USER.upper():
            return ("user", f"{player_handle}{info_text}")
        elif player_handle == 'unknown':
            return ("neutral", f"{player_handle}{info_text}")
        elif (player_handle.upper() in [p.upper() for p in self.PLAYERS_BLACKLIST] or
              player_info.get("mainOrg", "").upper() in [o.upper() for o in self.ORGS_BLACKLIST]):
            return ("enemy", f"{player_handle}{info_text}")
        elif (player_handle.upper() in [p.upper() for p in self.PLAYERS_WHITELIST] or
              player_info.get("mainOrg", "").upper() in [o.upper() for o in self.ORGS_WHITELIST] or
              player_handle.upper() in [c.upper() for c in self.CREW_NICKS]):
            return ("friendly", f"{player_handle}{info_text}")
        else:
            return ("neutral", f"{player_handle}{info_text}")

    def get_direction_info(self, x, y, z):
        """Obtener información de dirección del disparo mejorada"""
        if not self.config.get('show_direction', True):
            return ""

        try:
            angle = math.degrees(math.atan2(float(x), float(y)))
            if angle < 0:
                angle = angle + 360

            # Convertir ángulo a dirección cardinal
            directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
            direction_index = int((angle + 22.5) / 45) % 8
            cardinal = directions[direction_index]

            return f" [{round(angle, 1)}° {cardinal}]"
        except (ValueError, TypeError):
            return " [?°]"

    def on_window_configure(self, event):
        """Manejar cambios en la ventana"""
        if event.widget == self.root and self.config.get('save_position', True):
            # Guardar geometría actual
            geometry = self.root.geometry()
            if self.overlay_var.get():
                self.config['overlay_geometry'] = geometry
            else:
                self.config['window_geometry'] = geometry

    def toggle_overlay_mode(self):
        """Activar/desactivar modo overlay"""
        if self.overlay_var.get():
            # Guardar posición actual antes de cambiar
            if self.config.get('save_position', True):
                self.config['window_geometry'] = self.root.geometry()

            # Modo overlay: ventana sin bordes, siempre arriba
            self.root.wm_attributes("-topmost", True)
            self.root.overrideredirect(True)

            # Aplicar geometría guardada para overlay o posición predeterminada
            overlay_geometry = self.config.get('overlay_geometry', '800x120+100+10')
            self.root.geometry(overlay_geometry)

            # Hacer que se pueda mover arrastrando
            self.root.bind('<Button-1>', self.start_drag)
            self.root.bind('<B1-Motion>', self.drag_window)

            # Cambiar transparencia para overlay
            self.root.wm_attributes("-alpha", 0.8)

        else:
            # Guardar posición overlay actual
            if self.config.get('save_position', True):
                self.config['overlay_geometry'] = self.root.geometry()

            # Modo normal
            self.root.wm_attributes("-topmost", False)
            self.root.overrideredirect(False)

            # Restaurar geometría normal
            window_geometry = self.config.get('window_geometry', '900x250+100+100')
            self.root.geometry(window_geometry)

            # Remover bindings de arrastre
            self.root.unbind('<Button-1>')
            self.root.unbind('<B1-Motion>')

            # Restaurar transparencia normal
            transparency = self.config.get('transparency', 0.9)
            self.root.wm_attributes("-alpha", transparency)

    def start_drag(self, event):
        """Iniciar arrastre de ventana"""
        self.drag_start_x = event.x
        self.drag_start_y = event.y

    def drag_window(self, event):
        """Arrastrar ventana"""
        x = self.root.winfo_pointerx() - self.drag_start_x
        y = self.root.winfo_pointery() - self.drag_start_y
        self.root.geometry(f"+{x}+{y}")

    def start_monitoring(self):
        """Iniciar el monitoreo del log"""
        if not self.monitoring:
            # Verificar que existe el archivo de log
            if not os.path.exists(self.LOG_FILENAME):
                error_msg = f"No se encuentra el archivo de log: {self.LOG_FILENAME}"
                self.add_message(error_msg, "warning")
                messagebox.showerror("Error", error_msg)
                return

            self.monitoring = True
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL)
            self.status_label.config(text="● Conectado", fg='#00ff00')

            # Obtener posición actual del archivo
            try:
                with open(self.LOG_FILENAME, 'r', encoding="latin1") as f:
                    f.seek(0, 2)  # Ir al final
                    self.last_file_position = f.tell()
            except Exception as e:
                logger.error(f"Error obteniendo posición del archivo: {e}")
                self.last_file_position = 0

            # Iniciar thread de monitoreo
            self.monitor_thread = threading.Thread(target=self.monitor_log, daemon=True)
            self.monitor_thread.start()

            self.add_message("Sistema iniciado - Monitoreando eventos de combate", "success")

            if self.config.get('notifications', True):
                self.notification_system.show_notification(
                    "Monitor iniciado",
                    "Monitoreando eventos de Star Citizen",
                    "success"
                )

    def stop_monitoring(self):
        """Detener el monitoreo"""
        self.monitoring = False
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.status_label.config(text="● Desconectado", fg='#ff0000')
        self.add_message("Sistema detenido", "warning")

        if self.config.get('notifications', True):
            self.notification_system.show_notification(
                "Monitor detenido",
                "Monitoreo pausado",
                "warning"
            )

    def clear_messages(self):
        """Limpiar el área de mensajes"""
        self.text_area.delete(1.0, tk.END)
        self.messages_shown.clear()
        self.message_count = 0
        self.msg_count_label.config(text="Mensajes: 0")
        self.add_message("Área de mensajes limpiada", "info")

    def add_message(self, message, msg_type="normal"):
        """Añadir mensaje a la cola"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.message_queue.put((timestamp, message, msg_type))

    def process_message_queue(self):
        """Procesar cola de mensajes con límite"""
        try:
            processed = 0
            max_process = 10  # Procesar máximo 10 mensajes por ciclo

            while processed < max_process:
                timestamp, message, msg_type = self.message_queue.get_nowait()

                # Verificar límite de mensajes
                message_limit = self.config.get('message_limit', 1000)
                if self.message_count >= message_limit:
                    # Eliminar las primeras líneas
                    lines_to_remove = min(100, self.message_count - message_limit + 100)
                    for _ in range(lines_to_remove):
                        self.text_area.delete("1.0", "2.0")
                    self.message_count -= lines_to_remove

                # Insertar timestamp
                self.text_area.insert(tk.END, f"[{timestamp}] ", "timestamp")

                # Procesar mensaje con colores
                self.insert_colored_message(message, msg_type)

                # Nueva línea
                self.text_area.insert(tk.END, "\n")

                # Incrementar contador
                self.message_count += 1

                # Scroll automático
                self.text_area.see(tk.END)

                processed += 1

            # Actualizar contador en UI
            self.msg_count_label.config(text=f"Mensajes: {self.message_count}")

        except queue.Empty:
            pass

        # Programar siguiente procesamiento
        update_interval = self.config.get('update_interval', 100)
        self.root.after(update_interval, self.process_message_queue)

    def insert_colored_message(self, message, msg_type):
        """Insertar mensaje con colores apropiados"""
        if msg_type in ["info", "user", "crew", "enemy", "friendly", "neutral", "warning", "success"]:
            self.text_area.insert(tk.END, message, msg_type)
        else:
            self.text_area.insert(tk.END, message)

    def process_log_line(self, line):
        """Process a single log line and extract relevant information"""
        try:
            # Parse timestamp
            timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z)', line)
            if not timestamp_match:
                return

            timestamp_str = timestamp_match.group(1)
            timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))

            # Check for different message types
            message_data = None

            # Chat messages
            chat_match = re.search(r'<(.+?)>\s*(.+)', line)
            if chat_match and 'Chat' in line:
                player_name = chat_match.group(1).strip()
                message_content = chat_match.group(2).strip()

                # Determine channel
                channel = 'Global'
                if 'Party' in line:
                    channel = 'Party'
                elif 'Org' in line:
                    channel = 'Organization'
                elif 'Local' in line:
                    channel = 'Local'

                message_data = MessageData(
                    timestamp=timestamp,
                    player_name=player_name,
                    message=message_content,
                    message_type='chat',
                    channel=channel
                )

            # System messages
            elif any(keyword in line.lower() for keyword in ['joined', 'left', 'disconnected', 'connected']):
                if 'joined' in line.lower():
                    player_match = re.search(r'(.+?)\s+joined', line, re.IGNORECASE)
                    if player_match:
                        player_name = player_match.group(1).strip()
                        message_data = MessageData(
                            timestamp=timestamp,
                            player_name=player_name,
                            message=f"{player_name} joined the server",
                            message_type='system',
                            channel='System'
                        )
                elif 'left' in line.lower() or 'disconnected' in line.lower():
                    player_match = re.search(r'(.+?)\s+(?:left|disconnected)', line, re.IGNORECASE)
                    if player_match:
                        player_name = player_match.group(1).strip()
                        message_data = MessageData(
                            timestamp=timestamp,
                            player_name=player_name,
                            message=f"{player_name} left the server",
                            message_type='system',
                            channel='System'
                        )

            # Death messages
            elif any(keyword in line.lower() for keyword in ['killed', 'died', 'destroyed']):
                death_match = re.search(r'(.+?)\s+(?:killed|died|was destroyed)', line, re.IGNORECASE)
                if death_match:
                    player_name = death_match.group(1).strip()
                    message_data = MessageData(
                        timestamp=timestamp,
                        player_name=player_name,
                        message=line.strip(),
                        message_type='death',
                        channel='System'
                    )

            # Trade/Economy messages
            elif any(keyword in line.lower() for keyword in ['purchased', 'sold', 'transaction']):
                trade_match = re.search(r'(.+?)\s+(?:purchased|sold)', line, re.IGNORECASE)
                if trade_match:
                    player_name = trade_match.group(1).strip()
                    message_data = MessageData(
                        timestamp=timestamp,
                        player_name=player_name,
                        message=line.strip(),
                        message_type='trade',
                        channel='System'
                    )

            if message_data:
                self.process_message(message_data)

        except Exception as e:
            print(f"Error processing log line: {e}")

    def update_display(self):
        """Update the main display with recent messages"""
        try:
            # Clear current display
            for item in self.tree.get_children():
                self.tree.delete(item)

            # Get recent messages from database
            messages = self.db_manager.get_recent_messages(limit=self.config.max_display_messages)

            for msg in messages:
                # Apply filters
                if not self.should_display_message(msg):
                    continue

                # Format timestamp
                local_time = msg.timestamp.replace(tzinfo=timezone.utc).astimezone()
                time_str = local_time.strftime("%H:%M:%S")

                # Color coding based on message type
                tags = []
                if msg.message_type == 'chat':
                    if msg.channel == 'Party':
                        tags.append('party')
                    elif msg.channel == 'Organization':
                        tags.append('org')
                    elif msg.channel == 'Local':
                        tags.append('local')
                    else:
                        tags.append('global')
                elif msg.message_type == 'system':
                    tags.append('system')
                elif msg.message_type == 'death':
                    tags.append('death')
                elif msg.message_type == 'trade':
                    tags.append('trade')

                # Insert into tree
                self.tree.insert('', 0, values=(
                    time_str,
                    msg.player_name or 'System',
                    msg.channel,
                    msg.message
                ), tags=tags)

            # Auto-scroll to top (most recent)
            if self.tree.get_children():
                self.tree.see(self.tree.get_children()[0])

        except Exception as e:
            print(f"Error updating display: {e}")

    def should_display_message(self, message_data):
        """Check if message should be displayed based on filters"""
        # Check blacklist
        if message_data.player_name and message_data.player_name.lower() in [name.lower() for name in self.config.blacklisted_players]:
            return False

        # Check keyword blacklist
        if any(keyword.lower() in message_data.message.lower() for keyword in self.config.blacklisted_keywords):
            return False

        # Check channel filters
        if message_data.channel == 'Global' and not self.config.show_global_chat:
            return False
        if message_data.channel == 'Local' and not self.config.show_local_chat:
            return False
        if message_data.channel == 'Party' and not self.config.show_party_chat:
            return False
        if message_data.channel == 'Organization' and not self.config.show_org_chat:
            return False
        if message_data.message_type == 'system' and not self.config.show_system_messages:
            return False
        if message_data.message_type == 'death' and not self.config.show_death_messages:
            return False
        if message_data.message_type == 'trade' and not self.config.show_trade_messages:
            return False

        return True

    def setup_styles(self):
        """Setup custom styles for the treeview"""
        style = ttk.Style()

        # Configure tag colors
        self.tree.tag_configure('global', background='#f0f0f0')
        self.tree.tag_configure('local', background='#e6f3ff')
        self.tree.tag_configure('party', background='#e6ffe6')
        self.tree.tag_configure('org', background='#fff0e6')
        self.tree.tag_configure('system', background='#ffe6e6', foreground='#666666')
        self.tree.tag_configure('death', background='#ffcccc', foreground='#cc0000')
        self.tree.tag_configure('trade', background='#ffffcc', foreground='#cc6600')

    def on_closing(self):
        """Handle application closing"""
        try:
            # Save current window position and size
            self.config.window_x = self.root.winfo_x()
            self.config.window_y = self.root.winfo_y()
            self.config.window_width = self.root.winfo_width()
            self.config.window_height = self.root.winfo_height()

            # Save configuration
            self.save_config()

            # Stop monitoring
            self.monitoring = False

            # Close database connection
            if hasattr(self, 'db_manager'):
                self.db_manager.close()

            # Destroy window
            self.root.destroy()

        except Exception as e:
            print(f"Error during closing: {e}")
            self.root.destroy()

    def run(self):
        """Start the application"""
        try:
            self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
            self.root.mainloop()
        except Exception as e:
            print(f"Error running application: {e}")


def main():
    """Main entry point"""
    try:
        app = StarCitizenLogMonitor()
        app.run()
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()


# Funciones auxiliares adicionales para el monitor de Star Citizen

class LogFileWatcher:
    """Clase auxiliar para monitorear cambios en archivos de log"""

    def __init__(self, file_path, callback):
        self.file_path = file_path
        self.callback = callback
        self.last_position = 0
        self.last_modified = 0

    def check_for_changes(self):
        """Verifica si el archivo ha cambiado y procesa nuevas líneas"""
        try:
            if not os.path.exists(self.file_path):
                return

            # Verificar si el archivo fue modificado
            current_modified = os.path.getmtime(self.file_path)
            if current_modified <= self.last_modified:
                return

            self.last_modified = current_modified

            # Leer nuevas líneas
            with open(self.file_path, 'r', encoding='utf-8', errors='ignore') as f:
                f.seek(self.last_position)
                new_lines = f.readlines()
                self.last_position = f.tell()

                # Procesar cada nueva línea
                for line in new_lines:
                    line = line.strip()
                    if line:
                        self.callback(line)

        except Exception as e:
            print(f"Error watching log file: {e}")


class MessageFilter:
    """Clase para filtrado avanzado de mensajes"""

    def __init__(self, config):
        self.config = config
        self.compiled_patterns = {}
        self._compile_patterns()

    def _compile_patterns(self):
        """Compila patrones regex para filtrado eficiente"""
        try:
            # Compilar patrones de palabras clave bloqueadas
            if self.config.blacklisted_keywords:
                pattern = '|'.join(re.escape(keyword) for keyword in self.config.blacklisted_keywords)
                self.compiled_patterns['keywords'] = re.compile(pattern, re.IGNORECASE)

            # Compilar patrones de jugadores bloqueados
            if self.config.blacklisted_players:
                pattern = '|'.join(re.escape(player) for player in self.config.blacklisted_players)
                self.compiled_patterns['players'] = re.compile(pattern, re.IGNORECASE)

        except Exception as e:
            print(f"Error compiling filter patterns: {e}")

    def should_filter_message(self, message_data):
        """Determina si un mensaje debe ser filtrado"""
        try:
            # Filtro por palabras clave
            if 'keywords' in self.compiled_patterns:
                if self.compiled_patterns['keywords'].search(message_data.message):
                    return True

            # Filtro por jugadores
            if 'players' in self.compiled_patterns and message_data.player_name:
                if self.compiled_patterns['players'].search(message_data.player_name):
                    return True

            return False

        except Exception as e:
            print(f"Error filtering message: {e}")
            return False


class ExportManager:
    """Clase para exportar datos del monitor"""

    @staticmethod
    def export_to_csv(messages, filename):
        """Exporta mensajes a archivo CSV"""
        try:
            import csv

            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['timestamp', 'player_name', 'channel', 'message_type', 'message']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                writer.writeheader()
                for msg in messages:
                    writer.writerow({
                        'timestamp': msg.timestamp.isoformat(),
                        'player_name': msg.player_name or '',
                        'channel': msg.channel,
                        'message_type': msg.message_type,
                        'message': msg.message
                    })

            return True

        except Exception as e:
            print(f"Error exporting to CSV: {e}")
            return False

    @staticmethod
    def export_to_json(messages, filename):
        """Exporta mensajes a archivo JSON"""
        try:
            import json

            data = []
            for msg in messages:
                data.append({
                    'timestamp': msg.timestamp.isoformat(),
                    'player_name': msg.player_name,
                    'channel': msg.channel,
                    'message_type': msg.message_type,
                    'message': msg.message
                })

            with open(filename, 'w', encoding='utf-8') as jsonfile:
                json.dump(data, jsonfile, indent=2, ensure_ascii=False)

            return True

        except Exception as e:
            print(f"Error exporting to JSON: {e}")
            return False


class PerformanceMonitor:
    """Clase para monitorear el rendimiento de la aplicación"""

    def __init__(self):
        self.start_time = time.time()
        self.message_count = 0
        self.last_update = time.time()
        self.update_times = []

    def record_message(self):
        """Registra el procesamiento de un mensaje"""
        self.message_count += 1

    def record_update_time(self, update_time):
        """Registra el tiempo de actualización de la UI"""
        self.update_times.append(update_time)
        # Mantener solo los últimos 100 tiempos
        if len(self.update_times) > 100:
            self.update_times.pop(0)

    def get_stats(self):
        """Obtiene estadísticas de rendimiento"""
        current_time = time.time()
        uptime = current_time - self.start_time

        avg_update_time = 0
        if self.update_times:
            avg_update_time = sum(self.update_times) / len(self.update_times)

        return {
            'uptime': uptime,
            'messages_processed': self.message_count,
            'messages_per_second': self.message_count / uptime if uptime > 0 else 0,
            'average_update_time': avg_update_time,
            'memory_usage': self._get_memory_usage()
        }

    def _get_memory_usage(self):
        """Obtiene el uso de memoria actual"""
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss / 1024 / 1024  # MB
        except ImportError:
            return 0

class ThemeManager:
    """Sistema de gestión de temas mejorado y funcional"""

    def __init__(self, root):
        self.root = root
        self.current_theme = 'dark'
        self.registered_widgets = []

        # Definir temas completos
        self.themes = {
            'dark': {
                'bg_primary': '#1a1a1a',
                'bg_secondary': '#2a2a2a', 
                'bg_tertiary': '#404040',
                'fg_primary': '#ffffff',
                'fg_secondary': '#cccccc',
                'accent': '#0078d4',
                'success': '#2d5a2d',
                'warning': '#5a4a2d',
                'error': '#5a2d2d',
                'user_color': '#ffff00',
                'crew_color': '#00ff00',
                'enemy_color': '#ff0000',
                'neutral_color': '#ffa500',
                'info_color': '#00ffff'
            },
            'light': {
                'bg_primary': '#ffffff',
                'bg_secondary': '#f5f5f5',
                'bg_tertiary': '#e0e0e0',
                'fg_primary': '#000000',
                'fg_secondary': '#333333',
                'accent': '#0078d4',
                'success': '#28a745',
                'warning': '#ffc107',
                'error': '#dc3545',
                'user_color': '#ff8c00',
                'crew_color': '#228b22',
                'enemy_color': '#dc143c',
                'neutral_color': '#4682b4',
                'info_color': '#17a2b8'
            },
            'blue': {
                'bg_primary': '#0d1117',
                'bg_secondary': '#161b22',
                'bg_tertiary': '#21262d',
                'fg_primary': '#c9d1d9',
                'fg_secondary': '#8b949e',
                'accent': '#58a6ff',
                'success': '#238636',
                'warning': '#d29922',
                'error': '#f85149',
                'user_color': '#ffd700',
                'crew_color': '#7ee787',
                'enemy_color': '#ff7b72',
                'neutral_color': '#79c0ff',
                'info_color': '#58a6ff'
            }
        }

    def register_widget(self, widget, widget_type='frame'):
        """Registrar widget para aplicar tema"""
        self.registered_widgets.append((widget, widget_type))

    def apply_theme(self, theme_name):
        """Aplicar tema a todos los widgets registrados"""
        if theme_name not in self.themes:
            return False

        self.current_theme = theme_name
        theme = self.themes[theme_name]

        try:
            # Aplicar al root
            self.root.configure(bg=theme['bg_primary'])

            # Aplicar a widgets registrados
            for widget, widget_type in self.registered_widgets:
                self._apply_widget_theme(widget, widget_type, theme)

            # Configurar ttk styles
            self._configure_ttk_styles(theme)

            return True

        except Exception as e:
            print(f"Error aplicando tema: {e}")
            return False

    def _apply_widget_theme(self, widget, widget_type, theme):
        """Aplicar tema a un widget específico"""
        try:
            if widget_type == 'frame':
                widget.configure(bg=theme['bg_primary'])
            elif widget_type == 'label':
                widget.configure(bg=theme['bg_primary'], fg=theme['fg_primary'])
            elif widget_type == 'button':
                widget.configure(bg=theme['bg_tertiary'], fg=theme['fg_primary'])
            elif widget_type == 'entry':
                widget.configure(bg=theme['bg_tertiary'], fg=theme['fg_primary'], 
                               insertbackground=theme['fg_primary'])
            elif widget_type == 'text':
                widget.configure(bg=theme['bg_secondary'], fg=theme['fg_primary'],
                               insertbackground=theme['fg_primary'])
                # Reconfigurar tags de colores
                widget.tag_configure("user", foreground=theme['user_color'])
                widget.tag_configure("crew", foreground=theme['crew_color'])
                widget.tag_configure("enemy", foreground=theme['enemy_color'])
                widget.tag_configure("neutral", foreground=theme['neutral_color'])
                widget.tag_configure("info", foreground=theme['info_color'])
                widget.tag_configure("success", foreground=theme['success'])
                widget.tag_configure("warning", foreground=theme['warning'])
                widget.tag_configure("timestamp", foreground=theme['fg_secondary'])
            elif widget_type == 'listbox':
                widget.configure(bg=theme['bg_tertiary'], fg=theme['fg_primary'])
            elif widget_type == 'checkbutton':
                widget.configure(bg=theme['bg_primary'], fg=theme['fg_primary'],
                               selectcolor=theme['bg_tertiary'])
        except:
            pass  # Widget puede haber sido destruido

    def _configure_ttk_styles(self, theme):
        """Configurar estilos de ttk"""
        try:
            import tkinter.ttk as ttk
            style = ttk.Style()

            # Notebook
            style.configure('TNotebook', background=theme['bg_primary'])
            style.configure('TNotebook.Tab', 
                          background=theme['bg_tertiary'], 
                          foreground=theme['fg_primary'])
            style.map('TNotebook.Tab',
                     background=[('selected', theme['accent'])])

            # Combobox
            style.configure('TCombobox',
                          fieldbackground=theme['bg_tertiary'],
                          background=theme['bg_tertiary'],
                          foreground=theme['fg_primary'])

        except Exception as e:
            print(f"Error configurando estilos ttk: {e}")

    def get_current_theme(self):
        """Obtener tema actual"""
        return self.current_theme

    def get_theme_colors(self, theme_name=None):
        """Obtener colores del tema"""
        if theme_name is None:
            theme_name = self.current_theme
        return self.themes.get(theme_name, self.themes['dark'])

    @classmethod
    def apply_theme(cls, root, theme_name):
        """Aplica un tema a la aplicación"""
        if theme_name not in cls.THEMES:
            theme_name = 'default'

        theme = cls.THEMES[theme_name]

        try:
            style = ttk.Style()
            style.theme_use('clam')

            # Configurar colores del tema
            style.configure('Treeview', 
                          background=theme['bg'],
                          foreground=theme['fg'],
                          selectbackground=theme['select_bg'],
                          selectforeground=theme['select_fg'])

            style.configure('Treeview.Heading',
                          background=theme['select_bg'],
                          foreground=theme['select_fg'])

            root.configure(bg=theme['bg'])

        except Exception as e:
            print(f"Error applying theme: {e}")


# Funciones de utilidad adicionales

def validate_log_path(path):
    """Valida que la ruta del log sea correcta"""
    if not path:
        return False, "Ruta vacía"

    if not os.path.exists(path):
        return False, "El archivo no existe"

    if not os.path.isfile(path):
        return False, "La ruta no es un archivo"

    if not path.lower().endswith('.log'):
        return False, "El archivo no es un log"

    try:
        with open(path, 'r', encoding='utf-8') as f:
            f.read(1)  # Intentar leer un carácter
        return True, "Ruta válida"
    except Exception as e:
        return False, f"Error al acceder al archivo: {e}"


def find_star_citizen_logs():
    """Busca automáticamente los logs de Star Citizen"""
    possible_paths = []

    # Rutas comunes de Star Citizen
    user_profile = os.path.expanduser("~")

    sc_paths = [
        os.path.join(user_profile, "Documents", "StarCitizen", "LIVE", "Logs"),
        os.path.join(user_profile, "Documents", "StarCitizen", "PTU", "Logs"),
        os.path.join(user_profile, "AppData", "Local", "Star Citizen", "Logs"),
        "C:\Program Files\Roberts Space Industries\StarCitizen\LIVE\Logs",
        "C:\Program Files (x86)\Roberts Space Industries\StarCitizen\LIVE\Logs"
    ]

    for path in sc_paths:
        if os.path.exists(path):
            # Buscar archivos .log en el directorio
            for file in os.listdir(path):
                if file.endswith('.log'):
                    possible_paths.append(os.path.join(path, file))

    return possible_paths


def create_backup(config_path):
    """Crea una copia de seguridad del archivo de configuración"""
    try:
        if os.path.exists(config_path):
            backup_path = f"{config_path}.backup.{int(time.time())}"
            import shutil
            shutil.copy2(config_path, backup_path)
            return backup_path
    except Exception as e:
        print(f"Error creating backup: {e}")
    return None


# Constantes adicionales
VERSION = "2.0.0"
AUTHOR = "Star Citizen Log Monitor"
GITHUB_URL = "https://github.com/example/sc-log-monitor"

# Configuración de logging para debug
import logging

def setup_logging(debug=False):
    """Configura el sistema de logging"""
    level = logging.DEBUG if debug else logging.INFO

    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('sc_monitor.log'),
            logging.StreamHandler()
        ]
    )

    return logging.getLogger(__name__)


# Fin del archivo - Todas las partes están completas

