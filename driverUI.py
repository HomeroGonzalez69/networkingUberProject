#driver_gui.py
# Tkinter UI for the driver. It talks to the server with the SAME messages as driver.py,
# so UDPServer.py does not change. It reuses helpers from customer_gui.py, so keep both files in the same folder.
# Screens (from the sketches):
#   login -> Drop Headshot -> menu (View past rides / View requested rides)
#   -> past rides table, or Requested Rides (table + map) -> Pick current zone
#   -> On your way (pickup) -> On your way (drop-off) -> done
import json
import queue
import re
import socket
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk

from customerUI import (BG, BLUE, FONT, GRAY, GREEN, HAVE_PIL, HERE, INK, MUTED, RED, RIDE_HEADERS,
                          SERVER_ADDRESS, make_button, make_table, parse_table, prepare_headshot)

if HAVE_PIL:
    from PIL import ImageTk

PURPLE = "#8e44ad"


# ------------------------------------------------------------------ the map (3x3 zones)
class ZoneMap(tk.Canvas):
    def __init__(self, parent, size=270):
        super().__init__(parent, width=size, height=size, bg="white", highlightthickness=2, highlightbackground=INK)
        self.size = size
        self.cell = size // 3
        self.show()

    def center(self, zone):
        row, col = (zone - 1) // 3, (zone - 1) % 3
        return col * self.cell + self.cell // 2, row * self.cell + self.cell // 2

    #draws the grid, a colored circle for each of pickup (blue), drop-off (red) and the driver (purple),
    # and arrows given as (from_zone, to_zone, color, width)
    def show(self, pickup=None, drop=None, current=None, arrows=()):
        self.delete("all")
        c = self.cell
        for i in range(1, 3):
            self.create_line(i * c, 0, i * c, self.size, fill="#bdbdbd")
            self.create_line(0, i * c, self.size, i * c, fill="#bdbdbd")
        for zone in range(1, 10):
            x, y = self.center(zone)
            self.create_text(x - c // 2 + 12, y - c // 2 + 12, text=str(zone), fill="#9a9a9a", font=(FONT, 9))
        for start, end, color, width in arrows:
            if start and end and start != end:
                x1, y1 = self.center(start)
                x2, y2 = self.center(end)
                length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
                ux, uy = (x2 - x1) / length, (y2 - y1) / length
                gap = 30                                         # keep the arrow clear of the circles
                self.create_line(x1 + ux * gap, y1 + uy * gap, x2 - ux * gap, y2 - uy * gap, fill=color,
                                 width=width, arrow=tk.LAST, arrowshape=(14, 16, 6), tags="arrow")
        roles = {}
        for color, zone in ((BLUE, pickup), (RED, drop), (PURPLE, current)):
            if zone:
                roles.setdefault(zone, []).append(color)
        spots = {1: [(0, 0)], 2: [(-20, 0), (20, 0)], 3: [(-20, 14), (20, 14), (0, -16)]}
        for zone, colors in roles.items():                       # several roles in one zone sit side by side
            x, y = self.center(zone)
            radius = 24 if len(colors) == 1 else 17
            for (dx, dy), color in zip(spots[len(colors)], colors):
                self.create_oval(x + dx - radius, y + dy - radius, x + dx + radius, y + dy + radius,
                                 fill=color, outline="", tags="marker")


# ------------------------------------------------------------------ the app
class DriverApp:
    def __init__(self, root):
        self.root = root
        root.title("UBER HJ - Driver")
        root.geometry("1240x680")
        root.minsize(1100, 640)
        root.configure(bg=BG)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", rowheight=32, font=(FONT, 10), background="white", fieldbackground="white")
        style.configure("Treeview.Heading", font=(FONT, 10, "bold"))

        self.sock = None
        self.inbox = queue.Queue()
        self.new_connection()

        self.main = tk.Frame(root, bg=BG)
        self.main.pack(fill="both", expand=True, padx=30, pady=20)

        self.reset_state()
        self.show_login()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.poll_job = root.after(100, self.poll)

    # ---------------------------------------------------------- state and networking
    def reset_state(self):                       # everything that belongs to ONE login session
        self.screen = None
        self.username = None
        self.try_user = ""
        self.login_deadline = None
        self.pending_payload = None             # headshot waiting for the server's "please upload"
        self.uploaded = False
        self.stage = None                       # what the server is waiting for:
        #                                         "ask_requested" (see requested rides?), "pick" (ride id),
        #                                         "accepting" (current zone), "pickup", "dropoff", "done"
        self.past_ready = None                  # (headers, rows) of the driver's earlier rides
        self.requested = None                   # (headers, rows) of the requested rides
        self.waiting_requested = False          # "View requested rides" was pressed, the list is on its way
        self.selected = None                    # the ride picked in the table
        self.zone = None                        # the driver's current zone (purple)
        self.ride = None                        # the accepted ride: id, customer, pickup, drop, cost
        self.leg = "pickup"
        self.images = []

    #a NEW socket (new port) for every login, because the server remembers which address belongs to which user
    def new_connection(self):
        old = self.sock
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("", 0))
        if old is not None:
            old.close()
        threading.Thread(target=self.listen, args=(self.sock,), daemon=True).start()

    def listen(self, sock):
        while sock is self.sock:                 # background thread so the window never freezes
            try:
                data, _ = sock.recvfrom(65535)
                self.inbox.put(("msg", data.decode("utf-8"), sock))
            except OSError as error:
                if sock is not self.sock:
                    return
                self.inbox.put(("error", str(error), sock))
                time.sleep(0.3)

    def send(self, payload):
        try:
            self.sock.sendto(json.dumps(payload).encode("utf-8"), SERVER_ADDRESS)
        except OSError as error:
            self.on_error(str(error))

    def poll(self):                              # checks for server messages every 100 ms
        try:
            while True:
                kind, value, sock = self.inbox.get_nowait()
                if sock is not self.sock:
                    continue
                if kind == "msg":
                    self.on_message(value)
                else:
                    self.on_error(value)
        except queue.Empty:
            pass
        if self.login_deadline and time.time() > self.login_deadline:
            self.login_failed("The server did not answer. Is UDPServer.py running?")
        self.poll_job = self.root.after(100, self.poll)

    def on_error(self, text):
        if self.screen == "login" and self.login_deadline:
            self.login_failed("Can't reach the server. Is UDPServer.py running?")

    def on_message(self, text):
        if text == "passVerified":
            self.login_deadline = None
            self.username = self.try_user
            self.send({"text": "ack"})
            self.show_headshot()
        elif self.screen == "login" and self.login_deadline:
            self.login_failed("Login failed. Check your username and password.")
        elif text == "kill":
            pass
        elif "upload a driver headshot" in text:
            pass                                 # the headshot screen is already showing
        elif "Please upload your driver headshot" in text:
            if self.pending_payload:
                self.send(self.pending_payload)
                self.pending_payload = None
                self.uploaded = True
                self.set_status(f"Uploaded. The server saved it as {self.username}.jpg", GREEN)
                self.action_button.config(text="Continue")
        elif "previous rides?" in text:          # fetch the earlier rides right away so both menu buttons always work
            self.send({"text": "yes"})
        elif "Here is a list of your previous drives" in text:
            self.past_ready = parse_table(text)
            self.stage = "ask_requested"         # the server now waits for "see requested rides?"
            self.refresh_menu()
        elif "Here is a list of requested rides" in text:
            self.requested = parse_table(text)
            self.stage = "pick"                  # the server now waits for a ride id (or R / Q)
            notice = "That ride is no longer available. The list was refreshed." if "not in the list" in text else ""
            if self.waiting_requested or self.screen in ("requested", "zone"):
                self.waiting_requested = False
                self.show_requested(notice)
        elif "What is your current zone" in text:
            if self.stage == "accepting":
                self.send({"currentZone": str(self.zone)})
        elif "Sorry, ride" in text:
            self.stage = "done"
            self.show_sorry(text)
        elif "Ride request accepted" in text:
            self.accepted(text)
        elif "picked up. You are on the way to dropoff" in text:
            self.stage = "dropoff"
            self.leg = "dropoff"
            self.show_route()
        elif "is done" in text:
            self.stage = "done"
            self.show_done(text)

    #tells the server we are leaving, so it ends this session cleanly
    def end_session(self):
        if self.stage == "ask_requested":
            self.send({"text": "no"})            # no requested rides
        elif self.stage == "pick":
            self.send({"rideId": "q"})           # quit

    def back_to_login(self):
        self.end_session()
        self.new_connection()
        self.reset_state()
        self.show_login()

    def on_close(self):
        if self.stage in ("pickup", "dropoff") and not messagebox.askyesno(
                "Ride in progress", "You are in the middle of a ride. Quit anyway?"):
            return
        self.end_session()
        self.quit_app()

    def quit_app(self):
        self.root.after_cancel(self.poll_job)
        self.root.destroy()

    # ---------------------------------------------------------- small widgets
    def clear(self):
        for child in self.main.winfo_children():
            child.destroy()
        self.images = []

    def title(self, text, size=30):
        tk.Label(self.main, text=text, font=(FONT, size, "bold"), bg=BG, fg=INK).pack(pady=(10, 14))

    def set_status(self, text, color=MUTED):
        if getattr(self, "status", None) and self.status.winfo_exists():
            self.status.config(text=text, fg=color)

    def legend(self, parent, items):
        for color, text in items:
            line = tk.Frame(parent, bg=BG)
            line.pack(anchor="w", pady=5)
            tk.Label(line, bg=color, width=3, height=1).pack(side="left", padx=(0, 10))
            tk.Label(line, text=text, font=(FONT, 13), bg=BG, fg=INK).pack(side="left")

    # ---------------------------------------------------------- screen 1: login
    def show_login(self, error=""):
        self.screen = "login"
        self.clear()
        logo = None
        logo_path = f"{HERE}/logo.png"                       # put your own logo.png next to this file
        try:
            logo = tk.PhotoImage(file=logo_path)
            if logo.width() > 360:
                logo = logo.subsample(max(1, logo.width() // 360))
            self.images.append(logo)
        except tk.TclError:
            logo = None
        if logo:
            tk.Label(self.main, image=logo, bg=BG).pack(pady=(20, 6))
        else:
            tk.Label(self.main, text="UBER HJ", font=(FONT, 46, "bold"), bg=BG, fg=INK).pack(pady=(20, 6))
        tk.Label(self.main, text="Driver", font=(FONT, 13), bg=BG, fg=MUTED).pack(pady=(0, 24))

        self.user_var = tk.StringVar(value=self.try_user)
        self.pass_var = tk.StringVar()
        for label, variable, hidden in (("username", self.user_var, ""), ("password", self.pass_var, "\u2022")):
            tk.Label(self.main, text=label, font=(FONT, 12), bg=BG, fg=INK).pack(anchor="center")
            entry = tk.Entry(self.main, textvariable=variable, show=hidden, width=28, font=(FONT, 14),
                             relief="solid", bd=1)
            entry.pack(pady=(2, 14), ipady=5)
            entry.bind("<Return>", lambda event: self.do_login())
            if (label == "username") != bool(self.try_user):
                entry.focus_set()

        self.login_message = tk.Label(self.main, text=error, font=(FONT, 11), bg=BG, fg=RED)
        self.login_message.pack(pady=(0, 8))
        buttons = tk.Frame(self.main, bg=BG)
        buttons.pack()
        self.login_button = make_button(buttons, "Try again" if error else "Login", self.do_login)
        self.login_button.pack(side="left", padx=6)
        make_button(buttons, "Quit", self.on_close, dark=False).pack(side="left", padx=6)

    def do_login(self):
        user = self.user_var.get().strip()
        password = self.pass_var.get()
        if not user or not password:
            self.login_message.config(text="Enter your username and password.", fg=RED)
            return
        self.try_user = user
        self.login_button.config(state="disabled")
        self.login_message.config(text="Logging in...", fg=MUTED)
        self.login_deadline = time.time() + 5
        self.send({"id": user, "password": password, "tag": "driver"})

    def login_failed(self, message):
        self.login_deadline = None
        if self.screen == "login":
            self.show_login(error=message)

    # ---------------------------------------------------------- screen 2: Drop Headshot
    def show_headshot(self):
        self.screen = "headshot"
        self.clear()
        self.title("Drop Headshot")
        row = tk.Frame(self.main, bg=BG)
        row.pack(pady=6)
        tk.Label(row, text="File name", font=(FONT, 12), bg=BG, fg=INK).pack(side="left", padx=(0, 8))
        self.path_var = tk.StringVar()
        entry = tk.Entry(row, textvariable=self.path_var, width=42, font=(FONT, 12), relief="solid", bd=1)
        entry.pack(side="left", ipady=4)
        entry.bind("<Return>", lambda event: self.do_enter())
        entry.focus_set()
        self.enter_button = make_button(row, "Enter", self.do_enter)
        self.enter_button.pack(side="left", padx=(10, 4))
        make_button(row, "Browse...", self.do_browse, dark=False).pack(side="left", padx=4)

        box = tk.Frame(self.main, width=240, height=240, bg="white", highlightbackground=INK, highlightthickness=2)
        box.pack(pady=18)
        box.pack_propagate(False)
        note = ".jpg" if HAVE_PIL else ".jpg\n(install Pillow\nfor a preview)"
        self.preview = tk.Label(box, text=note, font=(FONT, 20), bg="white", fg=MUTED)
        self.preview.pack(expand=True)

        self.status = tk.Label(self.main, text="", font=(FONT, 11), bg=BG, fg=MUTED)
        self.status.pack()
        self.action_button = make_button(self.main, "Skip", self.skip_or_continue, dark=False)
        self.action_button.pack(pady=14)

    def do_browse(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(title="Choose your headshot",
                                          filetypes=[("Images", "*.jpg *.jpeg *.png *.webp *.gif"), ("All files", "*.*")])
        if path:
            self.path_var.set(path)
            self.do_enter()

    def do_enter(self):
        if self.uploaded or self.pending_payload:
            return
        path = self.path_var.get().strip().strip('"')
        if not path:
            self.set_status("Type a file name or press Browse.", RED)
            return
        try:
            payload, image = prepare_headshot(path)
        except ValueError as error:
            self.set_status(str(error), RED)
            return
        if image is not None:
            photo = ImageTk.PhotoImage(image)
            self.images.append(photo)
            self.preview.config(image=photo, text="")
        else:
            self.preview.config(text="(no preview)")
        self.pending_payload = payload
        self.enter_button.config(state="disabled")
        self.set_status("Uploading...")
        self.send({"text": "yes"})               # the server answers "Please upload your driver headshot."

    def skip_or_continue(self):
        if not self.uploaded:
            self.send({"text": "no"})
        self.show_menu()

    # ---------------------------------------------------------- screen 3: menu
    def show_menu(self):
        self.screen = "menu"
        self.clear()
        self.title(f"Welcome, {self.username}")
        tk.Label(self.main, text="What would you like to do?", font=(FONT, 14), bg=BG, fg=MUTED).pack(pady=(0, 24))
        self.view_button = make_button(self.main, "View past rides", self.view_past, width=24)
        self.view_button.pack(pady=8)
        self.requested_button = make_button(self.main, "View requested rides", self.view_requested, width=24)
        self.requested_button.pack(pady=8)
        self.menu_status = tk.Label(self.main, text="", font=(FONT, 11), bg=BG, fg=MUTED)
        self.menu_status.pack(pady=(10, 0))
        make_button(self.main, "Back to login", self.back_to_login, dark=False, width=24).pack(pady=(24, 0))
        self.refresh_menu()

    #the buttons wait until the earlier rides arrived, so every click has a matching answer
    def refresh_menu(self):
        if self.screen != "menu":
            return
        ready = self.past_ready is not None and self.stage in ("ask_requested", "pick") and not self.waiting_requested
        state = "normal" if ready else "disabled"
        self.view_button.config(state=state)
        self.requested_button.config(state=state)
        self.menu_status.config(text="" if ready else "Loading...")

    def view_past(self):
        self.show_past()

    def view_requested(self):
        self.waiting_requested = True
        self.refresh_menu()
        if self.stage == "ask_requested":
            self.send({"text": "yes"})           # "see requested rides?" -> yes
        else:
            self.send({"rideId": "r"})           # already asked once: R refreshes the list

    # ---------------------------------------------------------- screen 3b: past rides
    def show_past(self):
        self.screen = "past"
        self.clear()
        self.title("Your past rides")
        headers, rows = self.past_ready
        make_table(self.main, headers or RIDE_HEADERS, rows, height=9).pack(fill="x", pady=6)
        if not rows:
            tk.Label(self.main, text="No rides yet.", font=(FONT, 11), bg=BG, fg=MUTED).pack(pady=(4, 0))
        buttons = tk.Frame(self.main, bg=BG)
        buttons.pack(pady=22)
        make_button(buttons, "Back", self.show_menu, dark=False).pack(side="left", padx=8)
        make_button(buttons, "Back to login", self.back_to_login, dark=False).pack(side="left", padx=8)

    # ---------------------------------------------------------- screen 4: Requested Rides (table + map)
    def show_requested(self, notice=""):
        self.screen = "requested"
        self.selected = None
        self.clear()
        self.title("Requested Rides")
        headers, rows = self.requested
        headers = headers or RIDE_HEADERS
        self.requested_rows = rows

        body = tk.Frame(self.main, bg=BG)
        body.pack(fill="both", expand=True)
        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True)
        right = tk.Frame(body, bg=BG)
        right.pack(side="left", padx=(24, 0), anchor="n")

        tk.Label(left, text="Click a ride to pick it", font=(FONT, 11), bg=BG, fg=MUTED).pack(anchor="w", pady=(0, 4))
        tree = ttk.Treeview(left, columns=headers, show="headings", height=9, selectmode="browse")
        font = tkfont.nametofont("TkDefaultFont")
        total = 0
        for i, header in enumerate(headers):
            width = max([font.measure(header)] + [font.measure(r[i]) for r in rows if i < len(r)]) + 22
            total += width
            tree.heading(header, text=header)
            tree.column(header, width=width, minwidth=40, anchor="w", stretch=False)
        for index, row in enumerate(rows):
            tree.insert("", "end", iid=str(index), values=row)
        tree.pack(fill="both", expand=True)
        if total > 860:                          # only if the window is too narrow for all the columns
            scroll = ttk.Scrollbar(left, orient="horizontal", command=tree.xview)
            tree.configure(xscrollcommand=scroll.set)
            scroll.pack(fill="x")
        tree.bind("<<TreeviewSelect>>", self.on_select)
        self.rides_tree = tree
        if not rows:
            tk.Label(left, text="No requested rides right now.", font=(FONT, 11), bg=BG, fg=MUTED).pack(pady=(6, 0))
        self.status = tk.Label(left, text=notice, font=(FONT, 11), bg=BG, fg=RED)
        self.status.pack(pady=(6, 0))

        tk.Label(right, text="Map", font=(FONT, 18, "bold"), bg=BG, fg=INK).pack()
        self.map = ZoneMap(right)
        self.map.pack(pady=8)
        self.legend(right, ((BLUE, "Pickup"), (RED, "Drop-off")))

        buttons = tk.Frame(self.main, bg=BG)
        buttons.pack(pady=16)
        self.accept_button = make_button(buttons, "Accept ride", self.accept_selected)
        self.accept_button.config(state="disabled")
        self.accept_button.pack(side="left", padx=6)
        make_button(buttons, "Refresh", self.refresh_requested, dark=False).pack(side="left", padx=6)
        make_button(buttons, "Back", self.show_menu, dark=False).pack(side="left", padx=6)
        make_button(buttons, "Back to login", self.back_to_login, dark=False).pack(side="left", padx=6)

    def on_select(self, event=None):
        chosen = self.rides_tree.selection()
        if not chosen:
            return
        headers = self.requested[0] or RIDE_HEADERS
        row = self.requested_rows[int(chosen[0])]
        value = dict(zip(headers, row))
        self.selected = {"id": value["ID"], "customer": value["Customer"], "pickup": int(value["From"]),
                         "drop": int(value["To"]), "cost": value["Cost"]}
        self.map.show(pickup=self.selected["pickup"], drop=self.selected["drop"],
                      arrows=[(self.selected["pickup"], self.selected["drop"], INK, 3)])
        self.accept_button.config(state="normal")

    def refresh_requested(self):
        self.set_status("Refreshing...", MUTED)
        self.send({"rideId": "r"})

    def accept_selected(self):
        if self.selected:
            self.show_zone()                     # nothing is sent yet, so Back is free until Submit

    # ---------------------------------------------------------- screen 5: Pick current zone
    def show_zone(self):
        self.screen = "zone"
        self.zone = None
        self.clear()
        self.title("Pick current zone")
        body = tk.Frame(self.main, bg=BG)
        body.pack(pady=6)

        left = tk.Frame(body, bg=BG)
        left.grid(row=0, column=0, padx=40, sticky="n")
        self.legend(left, ((BLUE, "Blue = Pickup"), (RED, "Red = Drop-off"), (PURPLE, "Purple = Your zone")))
        tk.Label(left, text="Your pickup and drop-off\nare already marked.\n\nClick the zone you are in now.",
                 font=(FONT, 11), bg=BG, fg=MUTED, justify="left").pack(anchor="w", pady=(16, 0))

        grid = tk.Frame(body, bg=BG)
        grid.grid(row=0, column=1)
        self.zone_buttons = {}
        for zone in range(1, 10):
            button = tk.Button(grid, text=str(zone), width=5, height=2, font=(FONT, 22, "bold"), relief="flat",
                               bd=0, bg=GRAY, activebackground="#cfcfcf", cursor="hand2",
                               command=lambda z=zone: self.zone_click(z))
            button.grid(row=(zone - 1) // 3, column=(zone - 1) % 3, padx=4, pady=4)
            self.zone_buttons[zone] = button

        self.status = tk.Label(self.main, text="", font=(FONT, 12), bg=BG, fg=INK)
        self.status.pack(pady=(10, 0))
        buttons = tk.Frame(self.main, bg=BG)
        buttons.pack(pady=(14, 6))
        self.clear_button = make_button(buttons, "Clear", self.zone_clear, dark=False)
        self.clear_button.pack(side="left", padx=8)
        self.submit_button = make_button(buttons, "Submit", self.zone_submit)
        self.submit_button.pack(side="left", padx=8)
        more = tk.Frame(self.main, bg=BG)
        more.pack()
        self.back_button = make_button(more, "Back", lambda: self.show_requested(), dark=False)
        self.back_button.pack(side="left", padx=8)
        make_button(more, "Back to login", self.back_to_login, dark=False).pack(side="left", padx=8)
        self.refresh_zone()

    def zone_click(self, zone):
        if self.stage == "accepting":
            return
        self.zone = zone
        self.refresh_zone()

    def zone_clear(self):
        self.zone = None
        self.refresh_zone()

    def refresh_zone(self):
        pickup, drop = self.selected["pickup"], self.selected["drop"]
        for zone, button in self.zone_buttons.items():
            fill, text, rim = GRAY, INK, None
            if zone == pickup:
                fill, text = BLUE, "white"
            elif zone == drop:
                fill, text = RED, "white"
            if zone == self.zone:                # your zone is purple; if it is also the pickup or drop-off, the rim keeps that color
                rim = fill if fill != GRAY else None
                fill, text = PURPLE, "white"
            button.config(bg=fill, fg=text, activebackground=fill, activeforeground=text,
                          highlightthickness=5 if rim else 0, highlightbackground=rim or fill, highlightcolor=rim or fill)
        self.status.config(text=f"Pickup: {pickup}      Drop-off: {drop}      Your zone: {self.zone or '-'}")
        self.submit_button.config(state="normal" if self.zone and self.stage != "accepting" else "disabled")

    def zone_submit(self):
        self.stage = "accepting"
        self.refresh_zone()
        self.clear_button.config(state="disabled")
        self.back_button.config(state="disabled")
        self.status.config(text="Accepting the ride...")
        self.send({"rideId": str(self.selected["id"])})      # the server then asks for the current zone

    # ---------------------------------------------------------- screen 6: On your way
    def accepted(self, text):
        customer = re.search(r"Customer ID: (\w+)", text)
        pickup = re.search(r"Pickup Zone: (\d+)", text)
        drop = re.search(r"Dropoff Zone: (\d+)", text)
        cost = re.search(r"Cost: ([\d.]+)", text)
        self.ride = {"id": self.selected["id"] if self.selected else "?",
                     "customer": customer.group(1) if customer else "?",
                     "pickup": int(pickup.group(1)) if pickup else self.selected["pickup"],
                     "drop": int(drop.group(1)) if drop else self.selected["drop"],
                     "cost": f"${float(cost.group(1)):.2f}" if cost else self.selected["cost"]}
        self.stage = "pickup"
        self.leg = "pickup"
        self.show_route()

    def show_route(self):
        self.screen = "route"
        self.clear()
        self.title("On your way")
        ride = self.ride
        body = tk.Frame(self.main, bg=BG)
        body.pack(fill="x", pady=10)
        info = tk.Frame(body, bg=BG)
        info.pack(side="left", padx=(30, 0), anchor="n")
        for label, value in (("Customer ID", ride["customer"]), ("Pickup zone", ride["pickup"]),
                             ("Drop-off zone", ride["drop"]), ("Cost", ride["cost"])):
            line = tk.Frame(info, bg=BG)
            line.pack(anchor="w", pady=9)
            tk.Label(line, text=f"{label}:", font=(FONT, 17), bg=BG, fg=MUTED).pack(side="left")
            tk.Label(line, text=f"  {value}", font=(FONT, 17, "bold"), bg=BG, fg=INK).pack(side="left")
        right = tk.Frame(body, bg=BG)
        right.pack(side="right", padx=(0, 40))
        self.map = ZoneMap(right, size=300)
        self.map.pack()
        self.legend(right, ((BLUE, "Pickup"), (RED, "Drop-off"), (PURPLE, "You")))
        if self.leg == "pickup":
            arrows = [(self.zone, ride["pickup"], INK, 5)]
            question = "Have you reached the pickup zone?"
        else:
            arrows = [(self.zone, ride["pickup"], "#b8b8b8", 4), (ride["pickup"], ride["drop"], INK, 5)]
            question = "Have you reached the drop-off zone?"
        self.map.show(pickup=ride["pickup"], drop=ride["drop"], current=self.zone, arrows=arrows)

        tk.Label(self.main, text=question, font=(FONT, 18, "bold"), bg=BG, fg=INK).pack(pady=(14, 8))
        buttons = tk.Frame(self.main, bg=BG)
        buttons.pack()
        self.yes_button = make_button(buttons, "yes", self.route_yes, width=8)
        self.yes_button.pack(side="left", padx=10)
        self.no_button = make_button(buttons, "no", self.route_no, dark=False, width=8)
        self.no_button.pack(side="left", padx=10)
        self.status = tk.Label(self.main, text="", font=(FONT, 11), bg=BG, fg=MUTED)
        self.status.pack(pady=8)

    def route_yes(self):
        self.yes_button.config(state="disabled")
        self.no_button.config(state="disabled")
        self.send({"text": "yes"})               # the server answers with the next step

    def route_no(self):
        where = "pickup" if self.leg == "pickup" else "drop-off"
        self.set_status(f"Keep driving. Press yes when you reach the {where} zone.")

    # ---------------------------------------------------------- the end
    def show_done(self, text):
        self.screen = "done"
        self.clear()
        self.title("Done!")
        tk.Label(self.main, text=text.strip(), font=(FONT, 18), bg=BG, fg=GREEN, wraplength=800).pack(pady=(30, 30))
        make_button(self.main, "Done", self.quit_app).pack()

    def show_sorry(self, text):
        self.screen = "sorry"
        self.clear()
        self.title("Ride not available")
        tk.Label(self.main, text=text.strip(), font=(FONT, 16), bg=BG, fg=RED, wraplength=800).pack(pady=(20, 20))
        make_button(self.main, "Back to login", self.back_to_login).pack()


if __name__ == "__main__":
    window = tk.Tk()
    DriverApp(window)
    window.mainloop()