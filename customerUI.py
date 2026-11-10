#customerUI.py
# Tkinter UI for the customer. It talks to the server with the SAME messages as customer.py,
# so UDPServer.py does not change. Screens (from the sketches):
#   login -> Drop Headshot -> menu (View past rides / Request ride) -> past rides table or Pick zone
#   -> waiting -> driver found.   "Back to login" is on the menu, the past rides and the Pick zone screens.
import base64
import io
import json
import os
import queue
import re
import socket
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, ttk

try:                                    # Pillow is optional: it gives the headshot preview and
    from PIL import Image, ImageTk      # shrinks big images so they fit in ONE message.
    HAVE_PIL = True                     # Install it with:  pip install pillow
except ImportError:
    HAVE_PIL = False

SERVER_ADDRESS = ("localhost", 12000)
MAX_HEADSHOT_BYTES = 6000               # the headshot has to fit in one UDP message
HERE = os.path.dirname(os.path.abspath(__file__))

BG = "#ffffff"
INK = "#111111"
MUTED = "#6b6b6b"
GRAY = "#e4e4e4"
BLUE = "#1e6bff"
RED = "#e5383b"
GREEN = "#1b8a3a"
FONT = "Segoe UI"

RIDE_HEADERS = ["ID", "Customer", "Driver", "From", "To", "Miles", "Cost",
                "Requested", "Picked up", "Dropped off", "Status"]


# ------------------------------------------------------------------ helpers
#turns the text table sent by the server ("| a | b |" lines) into (headers, rows)
def parse_table(text):
    lines = [l.strip() for l in text.splitlines() if l.strip().startswith("|")]
    rows = [[cell.strip() for cell in l.strip("|").split("|")] for l in lines]
    if not rows:
        return [], []
    return rows[0], rows[1:]


#reads an image and builds the message that uploads it. With Pillow any image (jpg, png, webp...)
# is shrunk until it fits in one message and is sent as .jpg, so the server saves it as A.jpg.
#Returns (payload, preview_image_or_None). Raises ValueError with a message for the screen.
def prepare_headshot(path):
    if not os.path.isfile(path):
        raise ValueError("File not found. Check the name or press Browse.")
    if HAVE_PIL:
        try:
            image = Image.open(path).convert("RGB")
        except Exception:
            raise ValueError("That file is not an image I can open.")
        for size in (160, 128, 96, 64, 48, 32):
            small = image.copy()
            small.thumbnail((size, size))
            for quality in (75, 55, 35):
                buffer = io.BytesIO()
                small.save(buffer, "JPEG", quality=quality)
                if len(buffer.getvalue()) <= MAX_HEADSHOT_BYTES:
                    name = os.path.splitext(os.path.basename(path))[0] + ".jpg"
                    data = base64.b64encode(buffer.getvalue()).decode("ascii")
                    return {"headshot": name, "data": data}, small
        raise ValueError("Could not shrink that image enough.")
    extension = os.path.splitext(path)[1].lower()
    if extension not in (".jpg", ".jpeg", ".png", ".gif"):
        raise ValueError("Use a .jpg file, or install Pillow to use other types (pip install pillow).")
    with open(path, "rb") as imageFile:
        raw = imageFile.read()
    if len(raw) > MAX_HEADSHOT_BYTES:
        raise ValueError(f"File is too big ({len(raw)} bytes, max {MAX_HEADSHOT_BYTES}). "
                         "Install Pillow to shrink it automatically (pip install pillow).")
    return {"headshot": os.path.basename(path), "data": base64.b64encode(raw).decode("ascii")}, None


def make_button(parent, text, command, dark=True, width=None):
    colors = dict(bg=INK, fg="white", activebackground="#333333", activeforeground="white") if dark \
        else dict(bg=GRAY, fg=INK, activebackground="#cfcfcf", activeforeground=INK)
    return tk.Button(parent, text=text, command=command, relief="flat", bd=0, padx=24, pady=10, width=width,
                     font=(FONT, 11, "bold"), cursor="hand2", disabledforeground="#9a9a9a", **colors)


#a table widget (the "Table" box in the sketch)
def make_table(parent, headers, rows, height):
    frame = tk.Frame(parent, bg=BG)
    tree = ttk.Treeview(frame, columns=headers, show="headings", height=height)
    font = tkfont.nametofont("TkDefaultFont")
    total = 0
    for i, header in enumerate(headers):
        width = max([font.measure(header)] + [font.measure(r[i]) for r in rows if i < len(r)]) + 28
        total += width
        tree.heading(header, text=header)
        tree.column(header, width=width, minwidth=40, anchor="w", stretch=False)
    for row in rows:
        tree.insert("", "end", values=row)
    tree.pack(fill="both", expand=True)
    if total > 900:                              # only needed when the columns do not fit
        scroll = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(xscrollcommand=scroll.set)
        scroll.pack(fill="x")
    return frame


# ------------------------------------------------------------------ the app
class CustomerApp:
    def __init__(self, root):
        self.root = root
        root.title("UBER HJ - Customer")
        root.geometry("980x640")
        root.minsize(900, 600)
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
        self.stage = None                       # which question the server is waiting for:
        #                                         "ask_prev" (see previous rides?), "ask_request" (request a ride?),
        #                                         "zones", "waiting"
        self.table_ready = None                 # (headers, rows) of the past rides, once the server sent them
        self.waiting_table = False              # the user pressed "View past rides" and the list is on its way
        self.intent = None                      # "request" after the user pressed "Request ride"
        self.pick = None
        self.drop = None
        self.images = []                        # keeps images alive (Tk drops unreferenced ones)

    #a NEW socket (new port) for every login: the server remembers which address belongs to which user,
    # so going back to the login page must not reuse the old address
    def new_connection(self):
        old = self.sock
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("", 0))                 # bound first so the listener can wait on it
        if old is not None:
            old.close()
        threading.Thread(target=self.listen, args=(self.sock,), daemon=True).start()

    def listen(self, sock):
        while sock is self.sock:                 # runs in a background thread so the window never freezes
            try:
                data, _ = sock.recvfrom(65535)
                self.inbox.put(("msg", data.decode("utf-8"), sock))
            except OSError as error:
                if sock is not self.sock:
                    return                       # this socket was closed on purpose
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
                    continue                     # a late message from an old connection
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
        elif "upload a customer headshot" in text:
            pass                                 # the headshot screen is already showing
        elif "Please upload your headshot" in text:
            if self.pending_payload:
                self.send(self.pending_payload)
                self.pending_payload = None
                self.uploaded = True
                self.set_status(f"Uploaded. The server saved it as {self.username}.jpg", GREEN)
                self.action_button.config(text="Continue")
        elif "Here is a list of your previous rides" in text:
            self.table_ready = parse_table(text)
            self.stage = "ask_request"           # the server now waits for "request another ride?"
            if self.waiting_table:
                self.waiting_table = False
                self.show_past()
            else:
                self.refresh_menu()
        elif "previous rides?" in text:
            self.stage = "ask_prev"              # the server waits for yes/no to "see previous rides?"
            self.refresh_menu()
        elif "request another ride?" in text:    # only arrives alone after we answered "no" to the list
            self.stage = "ask_request"
            if self.intent == "request":
                self.send({"text": "yes"})
        elif "What is your desired pickup" in text:
            self.stage = "zones"
            self.show_zones()
        elif "Your ride request has been sent" in text:
            self.stage = "waiting"
            self.show_waiting()
        elif "initiated" in text:
            self.show_driver(text)

    #tells the server we are leaving, so it ends this session cleanly
    def end_session(self):
        if self.stage == "ask_prev":
            self.send({"text": "no"})            # no past rides...
            self.send({"text": "no"})            # ...and no ride
        elif self.stage == "ask_request":
            self.send({"text": "no"})

    def back_to_login(self):
        self.end_session()
        self.new_connection()
        self.reset_state()
        self.show_login()

    def on_close(self):
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

    # ---------------------------------------------------------- screen 1: login
    def show_login(self, error=""):
        self.screen = "login"
        self.clear()
        logo = None
        logo_path = os.path.join(HERE, "logo.png")           # put your own logo.png next to this file
        if os.path.exists(logo_path):
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
        tk.Label(self.main, text="Customer", font=(FONT, 13), bg=BG, fg=MUTED).pack(pady=(0, 24))

        self.user_var = tk.StringVar(value=self.try_user)
        self.pass_var = tk.StringVar()
        for label, variable, hidden in (("username", self.user_var, ""), ("password", self.pass_var, "\u2022")):
            tk.Label(self.main, text=label, font=(FONT, 12), bg=BG, fg=INK).pack(anchor="center")
            entry = tk.Entry(self.main, textvariable=variable, show=hidden, width=28, font=(FONT, 14),
                             relief="solid", bd=1)
            entry.pack(pady=(2, 14), ipady=5)
            entry.bind("<Return>", lambda event: self.do_login())
            if (label == "username") != bool(self.try_user):     # first time: username box, after a failure: password box
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
        self.send({"id": user, "password": password, "tag": "customer"})

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
        self.send({"text": "yes"})               # the server answers "Please upload your headshot."

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
        self.view_button = make_button(self.main, "View past rides", self.view_past, width=22)
        self.view_button.pack(pady=8)
        self.request_button = make_button(self.main, "Request ride", self.request_ride, width=22)
        self.request_button.pack(pady=8)
        self.menu_status = tk.Label(self.main, text="", font=(FONT, 11), bg=BG, fg=MUTED)
        self.menu_status.pack(pady=(10, 0))
        make_button(self.main, "Back to login", self.back_to_login, dark=False, width=22).pack(pady=(24, 0))
        self.refresh_menu()

    #the buttons wait until the server has asked its question, so every click has a matching answer
    def refresh_menu(self):
        if self.screen != "menu":
            return
        ready = self.stage in ("ask_prev", "ask_request") and not self.waiting_table and self.intent is None
        state = "normal" if ready else "disabled"
        self.view_button.config(state=state)
        self.request_button.config(state=state)
        self.menu_status.config(text="" if ready else "Loading...")

    def view_past(self):
        if self.table_ready is not None:         # already received, no need to ask again
            self.show_past()
            return
        self.waiting_table = True
        self.refresh_menu()
        self.send({"text": "yes"})               # "see your previous rides?" -> yes

    def request_ride(self):
        self.intent = "request"
        self.refresh_menu()
        if self.stage == "ask_prev":
            self.send({"text": "no"})            # skip the list; the server then asks "request another ride?"
        else:
            self.send({"text": "yes"})           # "request another ride?" -> yes

    # ---------------------------------------------------------- screen 3b: past rides
    def show_past(self):
        self.screen = "past"
        self.clear()
        self.title("Your past rides")
        headers, rows = self.table_ready
        make_table(self.main, headers or RIDE_HEADERS, rows, height=9).pack(fill="x", pady=6)
        if not rows:
            tk.Label(self.main, text="No rides yet.", font=(FONT, 11), bg=BG, fg=MUTED).pack(pady=(4, 0))
        buttons = tk.Frame(self.main, bg=BG)
        buttons.pack(pady=22)
        make_button(buttons, "Back", self.show_menu, dark=False).pack(side="left", padx=8)
        make_button(buttons, "Back to login", self.back_to_login, dark=False).pack(side="left", padx=8)

    # ---------------------------------------------------------- screen 4: Pick zone
    def show_zones(self):
        self.screen = "zones"
        self.pick = None
        self.drop = None
        self.clear()
        self.title("Pick zone!")
        body = tk.Frame(self.main, bg=BG)
        body.pack(pady=6)

        left = tk.Frame(body, bg=BG)
        left.grid(row=0, column=0, padx=40, sticky="n")
        for color, text in ((BLUE, "Blue = Pickup"), (RED, "Red = Drop-off")):
            line = tk.Frame(left, bg=BG)
            line.pack(anchor="w", pady=6)
            tk.Label(line, bg=color, width=3, height=1).pack(side="left", padx=(0, 10))
            tk.Label(line, text=text, font=(FONT, 14), bg=BG, fg=INK).pack(side="left")
        tk.Label(left, text="Click the pickup zone first,\nthen the drop-off zone.",
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
        buttons.pack(pady=14)
        make_button(buttons, "Clear", self.zone_clear, dark=False).pack(side="left", padx=8)
        self.submit_button = make_button(buttons, "Submit", self.zone_submit)
        self.submit_button.pack(side="left", padx=8)
        make_button(self.main, "Back to login", self.back_to_login, dark=False).pack()
        self.refresh_zones()

    def zone_click(self, zone):
        if self.pick is None:
            self.pick = zone
        elif self.drop is None and zone != self.pick:
            self.drop = zone
        else:
            return
        self.refresh_zones()

    def zone_clear(self):
        self.pick = None
        self.drop = None
        self.refresh_zones()

    def refresh_zones(self):
        for zone, button in self.zone_buttons.items():
            if zone == self.pick:
                button.config(bg=BLUE, fg="white", activebackground=BLUE, activeforeground="white")
            elif zone == self.drop:
                button.config(bg=RED, fg="white", activebackground=RED, activeforeground="white")
            else:
                button.config(bg=GRAY, fg=INK, activebackground="#cfcfcf", activeforeground=INK)
        self.status.config(text=f"Pickup: {self.pick or '-'}      Drop-off: {self.drop or '-'}")
        self.submit_button.config(state="normal" if self.pick and self.drop else "disabled")

    def zone_submit(self):
        self.submit_button.config(state="disabled")
        self.send({"pickupZone": str(self.pick), "dropoffZone": str(self.drop)})

    # ---------------------------------------------------------- screen 5: waiting for a driver
    def show_waiting(self):
        self.screen = "waiting"
        self.clear()
        self.title("Looking for a driver...")
        tk.Label(self.main, text=f"Ride from zone {self.pick} to zone {self.drop}", font=(FONT, 14),
                 bg=BG, fg=INK).pack(pady=(10, 20))
        bar = ttk.Progressbar(self.main, mode="indeterminate", length=360)
        bar.pack()
        bar.start(12)
        tk.Label(self.main, text="Keep this window open. It updates when a driver accepts your ride.",
                 font=(FONT, 11), bg=BG, fg=MUTED).pack(pady=20)

    # ---------------------------------------------------------- screen 6: driver found
    def show_driver(self, text):
        self.screen = "driver"
        self.clear()
        ride = re.search(r"Ride (\d+) initiated", text)
        self.title("Driver found!")
        if ride:
            tk.Label(self.main, text=f"Ride {ride.group(1)} was accepted", font=(FONT, 14), bg=BG, fg=INK).pack(pady=(0, 14))
        headers, rows = parse_table(text)
        if rows:
            make_table(self.main, headers, rows, height=1).pack(fill="x", pady=6)
        else:                                    # unknown format: just show what the server said
            tk.Label(self.main, text=text.strip(), font=(FONT, 12), bg=BG, fg=INK, justify="left").pack(pady=10)
        tk.Label(self.main, text="Your driver is on the way.", font=(FONT, 13), bg=BG, fg=GREEN).pack(pady=(18, 10))
        make_button(self.main, "Done", self.quit_app).pack(pady=10)


if __name__ == "__main__":
    window = tk.Tk()
    CustomerApp(window)
    window.mainloop()