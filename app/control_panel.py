"""Small Tkinter control panel running independently from asyncio."""

from __future__ import annotations

import gc
import queue
import threading
import tkinter as tk
from collections.abc import Callable

from app.runtime_state import RuntimeState


class ControlPanel:
    def __init__(self, runtime_state: RuntimeState, on_stop: Callable[[], None]) -> None:
        self._runtime_state = runtime_state
        self._on_stop = on_stop
        self._actions: queue.Queue[str] = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run_in_thread,
            name="twitch-bot-control-panel",
            daemon=False,
        )
        self._thread.start()

    def _run_in_thread(self) -> None:
        try:
            self._run()
        finally:
            gc.collect()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._actions.put("close")
        if threading.current_thread() is not self._thread:
            self._thread.join()
        self._thread = None

    def _run(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError:
            return

        root.title("Twitch Bot Control")
        root.minsize(300, 360)
        root.geometry("340x420")
        root.resizable(True, True)

        background = "#1e1e1e"
        panel_background = "#252526"
        control_background = "#2d2d30"
        main_text = "#e6e6e6"
        secondary_text = "#a0a0a0"
        root.configure(bg=background)

        def request_stop() -> None:
            self._on_stop()
            root.quit()

        root.protocol("WM_DELETE_WINDOW", request_stop)

        frame = tk.Frame(root, bg=background, padx=12, pady=10)
        frame.pack(fill="both", expand=True)

        tk.Label(
            frame,
            text="Twitch Bot Control",
            font=("TkDefaultFont", 11, "bold"),
            bg=background,
            fg=main_text,
        ).pack(
            anchor="w"
        )
        status_label = tk.Label(frame, anchor="w", bg=background, fg=secondary_text)
        status_label.pack(fill="x", pady=(6, 8))

        commands_frame = tk.LabelFrame(
            frame,
            text="Commands",
            bg=panel_background,
            fg=main_text,
            padx=8,
            pady=4,
        )
        commands_frame.pack(fill="x")
        command_variables: dict[str, tk.BooleanVar] = {}
        for command_name in ("ask", "weather", "forecast", "tg"):
            variable = tk.BooleanVar(value=self._runtime_state.command_enabled(command_name))
            command_variables[command_name] = variable
            tk.Checkbutton(
                commands_frame,
                text=f"!{command_name}",
                variable=variable,
                bg=panel_background,
                fg=main_text,
                activebackground=panel_background,
                activeforeground=main_text,
                selectcolor=control_background,
                highlightthickness=0,
                bd=0,
                command=lambda name=command_name, value=variable: self._runtime_state.set_command_enabled(
                    name, value.get()
                ),
            ).pack(anchor="w")

        ai_frame = tk.LabelFrame(
            frame,
            text="AI",
            bg=panel_background,
            fg=main_text,
            padx=8,
            pady=4,
        )
        ai_frame.pack(fill="x", pady=(8, 0))
        ai_variable = tk.BooleanVar(value=self._runtime_state.ai_enabled)
        tk.Checkbutton(
            ai_frame,
            text="AI enabled",
            variable=ai_variable,
            bg=panel_background,
            fg=main_text,
            activebackground=panel_background,
            activeforeground=main_text,
            selectcolor=control_background,
            highlightthickness=0,
            bd=0,
            command=lambda: self._runtime_state.set_ai_enabled(ai_variable.get()),
        ).pack(anchor="w")

        ai_memory_variable = tk.BooleanVar(value=self._runtime_state.ai_memory_enabled)
        tk.Checkbutton(
            ai_frame,
            text="AI Memory",
            variable=ai_memory_variable,
            bg=panel_background,
            fg=main_text,
            activebackground=panel_background,
            activeforeground=main_text,
            selectcolor=control_background,
            highlightthickness=0,
            bd=0,
            command=lambda: self._runtime_state.set_ai_memory_enabled(
                ai_memory_variable.get()
            ),
        ).pack(anchor="w")

        personality_variable = tk.StringVar(value=self._runtime_state.active_ai_personality)
        tk.Label(ai_frame, text="Personality:", bg=panel_background, fg=secondary_text).pack(
            anchor="w", pady=(4, 0)
        )
        personality_menu = tk.OptionMenu(
            ai_frame,
            personality_variable,
            *self._runtime_state.available_personalities,
            command=self._runtime_state.set_active_ai_personality,
        )
        personality_menu.configure(
            bg=control_background,
            fg=main_text,
            activebackground="#3a3a3d",
            activeforeground=main_text,
            highlightthickness=0,
            bd=0,
        )
        personality_menu["menu"].configure(
            bg=control_background,
            fg=main_text,
            activebackground="#4a4a4f",
            activeforeground=main_text,
        )
        personality_menu.pack(anchor="w")

        tk.Button(
            ai_frame,
            text="Stop Bot",
            bg=control_background,
            fg=main_text,
            activebackground="#3a3a3d",
            activeforeground=main_text,
            highlightthickness=0,
            bd=0,
            padx=8,
            pady=3,
            command=request_stop,
        ).pack(
            anchor="w", pady=(12, 0)
        )

        def refresh() -> None:
            try:
                action = self._actions.get_nowait()
            except queue.Empty:
                action = ""
            if action == "close":
                root.quit()
                return

            running, uptime = self._runtime_state.status()
            state_text = "RUNNING" if running else "STOPPED"
            status_label.configure(text=f"Bot: {state_text}    Uptime: {uptime}s")
            root.after(500, refresh)

        refresh()
        try:
            root.mainloop()
        finally:
            root.destroy()
