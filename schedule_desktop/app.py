import os, sys, re, json, sqlite3, shutil
from datetime import date, timedelta
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import tkinter.font as tkfont
import generator as G

APP = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
RES = getattr(sys, "_MEIPASS", APP)
DB, BELLS = os.path.join(APP, "school.db"), os.path.join(APP, "bells.json")
DAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница"]
BLUE, INK, BG = "#0c5ac8", "#0d2150", "#f1f4f9"

# ---------- данные (та же school.db, что у бота) ----------
def q(sql, args=()):
    c = sqlite3.connect(DB)
    try:
        r = c.execute(sql, args).fetchall(); c.commit(); return r
    finally: c.close()

def init_db():
    q("""CREATE TABLE IF NOT EXISTS schedule(id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, lesson INTEGER,
         class_name TEXT, subject TEXT, cabinet TEXT, teacher TEXT DEFAULT '')""")
    q("""CREATE TABLE IF NOT EXISTS schedule_changes(id INTEGER PRIMARY KEY AUTOINCREMENT, class_name TEXT,
         day TEXT, lesson INTEGER, teacher TEXT, cabinet TEXT, valid_date TEXT)""")

GEN = {  # таблицы с данными для составления расписания: колонки, заголовки, ширины
    "gen_teachers": (("name", "subjects", "classes"), ("Учитель", "Предметы (через запятую)", "Классы (через запятую)"), (260, 230, 280)),
    "gen_rooms": (("name", "subject"), ("Кабинет", "Предмет (если кабинет специальный)"), (200, 280)),
    "gen_plan": (("subject", "g5", "g6", "g7", "g8", "g9", "g10", "g11"), ("Предмет", "5", "6", "7", "8", "9", "10", "11"), (200,) + (55,) * 7),
    "gen_limits": (("grade", "week"), ("Параллель", "Макс. уроков в неделю"), (140, 220)),
}

def gen_init():
    for t, (cols, _, _) in GEN.items():
        q(f"CREATE TABLE IF NOT EXISTS {t}(id INTEGER PRIMARY KEY AUTOINCREMENT, {','.join(c + ' TEXT' for c in cols)})")

def gen_replace(table, rows):
    cols = GEN[table][0]; q(f"DELETE FROM {table}")
    for r in rows: q(f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join('?' * len(cols))})", list(r))

EXTRA = set()  # новые классы, в которых ещё нет уроков

def classes(): return sorted({r[0] for r in q("SELECT DISTINCT class_name FROM schedule")} | EXTRA)

def week_dates():
    t = date.today(); w = t.weekday()
    m = t + timedelta(days=7 - w if w >= 5 else -w)
    return [m + timedelta(days=i) for i in range(5)]

def bells():
    try: return json.load(open(BELLS, encoding="utf-8"))
    except Exception: return {}

def effective(d):
    """Расписание на дату с учётом замен."""
    ch = {(r[0].lower(), r[1]): r for r in q(
        "SELECT class_name,lesson,teacher,cabinet FROM schedule_changes WHERE valid_date=?", (d.isoformat(),))}
    out = []
    for les, cls, subj, cab, tea in q(
            "SELECT lesson,class_name,subject,cabinet,teacher FROM schedule WHERE LOWER(day)=LOWER(?) ORDER BY lesson",
            (DAYS[d.weekday()],)):
        r = dict(lesson=les, cls=cls, subject=subj, cab=cab or "", teacher=tea or "", changed=False, old_t="", old_c="")
        c = ch.get((cls.lower(), les))
        if c:
            r.update(changed=True, old_t=r["teacher"], old_c=r["cab"])
            if c[2]: r["teacher"] = c[2]
            if c[3]: r["cab"] = c[3]
        out.append(r)
    return out

def free(d, lesson, cls, absent=""):
    rows = [r for r in effective(d) if r["lesson"] == lesson and r["cls"].lower() != cls.lower()]
    at = {r[0].strip() for r in q("SELECT teacher FROM schedule") if r[0] and r[0].strip()}
    ac = {r[0].strip() for r in q("SELECT cabinet FROM schedule") if r[0] and r[0].strip()}
    return (sorted(at - {r["teacher"].strip() for r in rows} - {absent.strip()}),
            sorted(ac - {r["cab"].strip() for r in rows}))

def del_change(cls, d, lesson):
    q("DELETE FROM schedule_changes WHERE LOWER(class_name)=LOWER(?) AND valid_date=? AND lesson=?", (cls, d, lesson))

def set_change(cls, d, lesson, teacher, cab):
    del_change(cls, d.isoformat(), lesson)
    q("INSERT INTO schedule_changes(class_name,day,lesson,teacher,cabinet,valid_date) VALUES(?,?,?,?,?,?)",
      (cls, DAYS[d.weekday()], lesson, teacher, cab, d.isoformat()))

def all_changes():
    q("DELETE FROM schedule_changes WHERE valid_date < ?", (date.today().isoformat(),))
    return q("""SELECT c.class_name,c.valid_date,c.lesson,s.subject,s.teacher,c.teacher,s.cabinet,c.cabinet
        FROM schedule_changes c LEFT JOIN schedule s ON LOWER(s.class_name)=LOWER(c.class_name)
        AND LOWER(s.day)=LOWER(c.day) AND s.lesson=c.lesson ORDER BY c.valid_date,c.class_name,c.lesson""")

def lesson_rows(cls, day):
    return q("SELECT id,lesson,subject,teacher,cabinet FROM schedule WHERE LOWER(class_name)=LOWER(?) AND LOWER(day)=LOWER(?) ORDER BY lesson", (cls, day))

def add_lesson(day, les, cls, subj, cab, tea):
    q("INSERT INTO schedule(day,lesson,class_name,subject,cabinet,teacher) VALUES(?,?,?,?,?,?)", (day, les, cls.lower(), subj, cab, tea))

def update_lesson(rid, les, subj, cab, tea):
    q("UPDATE schedule SET lesson=?,subject=?,cabinet=?,teacher=? WHERE id=?", (les, subj, cab, tea, rid))

def conflicts(day, les, cls, tea, cab):
    out = []
    for c, t, k in q("SELECT class_name,teacher,cabinet FROM schedule WHERE LOWER(day)=LOWER(?) AND lesson=? AND LOWER(class_name)!=LOWER(?)", (day, les, cls)):
        if tea and (t or "").strip().lower() == tea.lower(): out.append(f"Учитель {tea} в это время уже ведёт урок у {c.upper()}")
        if cab and (k or "").strip().lower() == cab.lower(): out.append(f"Кабинет {cab} в это время занят классом {c.upper()}")
    return out

def save_bells(b): json.dump(b, open(BELLS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

def read_xlsx(path):
    try: from openpyxl import load_workbook
    except ImportError: raise ValueError("Установите openpyxl: pip install openpyxl")
    try: return list(load_workbook(path, data_only=True).active.iter_rows(values_only=True))
    except Exception: raise ValueError("Не удалось прочитать Excel-файл")

S = lambda v: "" if v is None else str(v).strip()

SKIP = {"", "каб", "каб.", "кабинет", "учитель", "предмет", "урок", "день"}

def parse_schedule(rows):
    """Находит шапку сам: строку со словом «День» (или первую строку с названиями классов)."""
    dl = {d.lower() for d in DAYS}; hdr = None
    for i, r in enumerate(rows):
        if r and S(r[0]).lower() == "день": hdr = i; break
    if hdr is None:
        for i, r in enumerate(rows):
            if (len(r) > 2 and S(r[2]) and S(r[0]).lower() not in dl and not S(r[0]).isdigit()
                    and not S(r[1]).replace(".0", "").isdigit()): hdr = i; break
    if hdr is None: raise ValueError("Не найдена строка с названиями классов (в ней должно быть слово «День»)")
    h = rows[hdr]
    cols = [(S(h[c]).lower(), c) for c in range(2, len(h)) if S(h[c]).lower() not in SKIP]
    if not cols: raise ValueError("В шапке не найдено ни одного класса")
    items = []
    for r in rows[hdr + 1:]:
        day = next((d for d in DAYS if d.lower() == S(r[0]).lower()), None) if r else None
        try: les = int(float(S(r[1])))
        except Exception: continue
        if not day: continue
        g = lambda i: S(r[i]) if i < len(r) else ""
        for cls, c in cols:
            if g(c): items.append((day, les, cls, g(c), g(c + 1), g(c + 2)))
    return items, cols

def import_schedule(path):
    items, cols = parse_schedule(read_xlsx(path))
    if not items: raise ValueError("Не найдено ни одного урока. Старое расписание не тронуто.")
    con = sqlite3.connect(DB); con.execute("DELETE FROM schedule")
    con.executemany("INSERT INTO schedule(day,lesson,class_name,subject,cabinet,teacher) VALUES(?,?,?,?,?,?)", items)
    con.commit(); con.close()
    return len(items), len(cols)

def import_bells(path):
    b = {}
    for r in read_xlsx(path)[1:]:
        try:
            if r[0] is not None and S(r[1]): b[str(int(r[0]))] = S(r[1])
        except Exception: continue
    if not b: raise ValueError("В файле не найдено расписание звонков")
    json.dump(b, open(BELLS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return len(b)

def export_schedule_xlsx(path, rows=None):
    """Выгрузка расписания в Excel в том же формате, что принимает «Загрузить расписание»."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    rows = rows if rows is not None else q("SELECT day,lesson,class_name,subject,cabinet,teacher FROM schedule")
    if not rows: raise ValueError("Расписание пустое")
    norm = lambda d: next((x for x in DAYS if x.lower() == (d or "").strip().lower()), None)
    cl = sorted({r[2] for r in rows}, key=lambda c: (G.grade(c) or 99, c)); P = max(r[1] for r in rows)
    idx = {(norm(r[0]), r[1], r[2]): r for r in rows}
    wb = Workbook(); ws = wb.active; ws.title = "Расписание"
    ws.append(["День", "Урок"] + [x for c in cl for x in (c.upper(), "каб", "учитель")])
    thin, thick = Side(style="thin", color="BBBBBB"), Side(style="medium", color="0C5AC8")
    for d in DAYS:
        for n in range(1, P + 1):
            ws.append([d, n] + [x for c in cl for x in ((idx[(d, n, c)][3], idx[(d, n, c)][4], idx[(d, n, c)][5]) if (d, n, c) in idx else ("", "", ""))])
    for row in ws.iter_rows():
        for c in row:
            c.border = Border(left=thin, right=thin, bottom=thin, top=thick if c.row > 1 and ws.cell(c.row, 2).value == 1 else thin)
            c.alignment = Alignment(vertical="center", wrap_text=True)
            if c.row == 1: c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="0C5AC8")
            elif c.column <= 2: c.font = Font(bold=True)
    for i in range(1, ws.max_column + 1):
        ws.column_dimensions[get_column_letter(i)].width = 14 if i == 1 else 6 if i == 2 else (22, 7, 26)[(i - 3) % 3]
    ws.freeze_panes = "C2"; wb.save(path)

class DBSource:
    """Таблица работает с текущим расписанием в базе."""
    def load(self):
        out = {}
        for rid, day, les, cls, subj, cab, tea in q("SELECT id,day,lesson,class_name,subject,cabinet,teacher FROM schedule"):
            d = next((i for i, x in enumerate(DAYS) if x.lower() == (day or "").strip().lower()), None)
            if d is not None: out[(cls, d, les)] = dict(id=rid, subject=subj or "", cabinet=cab or "", teacher=tea or "")
        return out
    def move(self, a, adst, b, bdst):
        q("UPDATE schedule SET day=?, lesson=? WHERE id=?", (DAYS[adst[0]], adst[1], a))
        if b is not None: q("UPDATE schedule SET day=?, lesson=? WHERE id=?", (DAYS[bdst[0]], bdst[1], b))
    def rows(self): return q("SELECT day,lesson,class_name,subject,cabinet,teacher FROM schedule")

class MemSource:
    """Таблица работает с только что составленным расписанием (в памяти, до нажатия «Применить»)."""
    def __init__(self, rows):
        self.items = [dict(id=i, day=r[0], lesson=r[1], cls=r[2], subject=r[3], cabinet=r[4], teacher=r[5]) for i, r in enumerate(rows)]
    def load(self):
        return {(it["cls"], DAYS.index(it["day"]), it["lesson"]): dict(id=it["id"], subject=it["subject"] or "", cabinet=it["cabinet"] or "", teacher=it["teacher"] or "")
                for it in self.items if it["day"] in DAYS}
    def move(self, a, adst, b, bdst):
        for it in self.items:
            if it["id"] == a: it["day"], it["lesson"] = DAYS[adst[0]], adst[1]
            elif b is not None and it["id"] == b: it["day"], it["lesson"] = DAYS[bdst[0]], bdst[1]
    def rows(self): return [(i["day"], i["lesson"], i["cls"], i["subject"], i["cabinet"], i["teacher"]) for i in self.items]

class Grid:
    """Таблица расписания: классы по горизонтали, день и урок по вертикали; уроки перетаскиваются мышью."""
    CW, CH, HW, HH = 150, 58, 64, 30
    PALETTE = ["#dbeafe", "#dcfce7", "#fef9c3", "#fce7f3", "#ede9fe", "#ffedd5", "#cffafe", "#e0e7ff", "#f1f5f9", "#fae8ff", "#ecfccb", "#fee2e2"]

    def __init__(self, parent, src, status=None):
        self.src, self.status, self.parent = src, status, parent
        box = tk.Frame(parent, bg="white"); box.pack(fill="both", expand=True, padx=14, pady=10)
        self.cv = tk.Canvas(box, bg="white", highlightthickness=0, height=420)
        xs = ttk.Scrollbar(box, orient="horizontal", command=self.cv.xview); ys = ttk.Scrollbar(box, command=self.cv.yview)
        xs.pack(side="bottom", fill="x"); ys.pack(side="right", fill="y"); self.cv.pack(side="left", fill="both", expand=True)
        self.cv.configure(xscrollcommand=lambda a, b: (xs.set(a, b), self.sync()), yscrollcommand=lambda a, b: (ys.set(a, b), self.sync()))
        self.cv.bind("<ButtonPress-1>", self.press); self.cv.bind("<B1-Motion>", self.motion); self.cv.bind("<ButtonRelease-1>", self.release)
        self.cv.bind("<MouseWheel>", lambda e: self.cv.yview_scroll(-1 * (e.delta // 120), "units"))
        self.cv.bind("<Shift-MouseWheel>", lambda e: self.cv.xview_scroll(-1 * (e.delta // 120), "units"))
        self.drag, self.ox, self.oy = None, 0, 0
        self.reload(); self.build()

    @staticmethod
    def short(name):
        p = (name or "").split()
        return " ".join([p[0]] + [x[0] + "." for x in p[1:3]]) if len(p) > 1 else (name or "")

    def reload(self):
        self.cells = self.src.load()
        self.classes = sorted({k[0] for k in self.cells}, key=lambda c: (G.grade(c) or 99, c))
        self.P = max([7] + [k[2] for k in self.cells])

    def xy(self, k): return self.HW + self.classes.index(k[0]) * self.CW, self.HH + (k[1] * self.P + k[2] - 1) * self.CH

    def at(self, x, y):
        col, row = int((x - self.HW) // self.CW), int((y - self.HH) // self.CH)
        if x < self.HW or y < self.HH or col >= len(self.classes) or row >= 5 * self.P: return None
        d, p = divmod(row, self.P); return (self.classes[col], d, p + 1)

    def build(self):
        cv = self.cv; cv.delete("all")
        if not self.cells:
            cv.create_text(20, 20, anchor="nw", fill="#6f7d97", font=("Segoe UI", 11), text="Расписания пока нет. Составьте его во вкладке «Создать расписание» или загрузите из Excel.")
            return self.update_status()
        n, P = len(self.classes), self.P
        cv.configure(scrollregion=(0, 0, self.HW + n * self.CW, self.HH + 5 * P * self.CH))
        for i, c in enumerate(self.classes):
            cv.create_rectangle(self.HW + i * self.CW, 0, self.HW + (i + 1) * self.CW, self.HH, fill=BLUE, outline="white", tags=("colhdr",))
            cv.create_text(self.HW + i * self.CW + self.CW // 2, self.HH // 2, text=c.upper(), fill="white", font=("Segoe UI", 10, "bold"), tags=("colhdr",))
        for d in range(5):
            for p in range(P):
                y = self.HH + (d * P + p) * self.CH
                cv.create_rectangle(0, y, self.HW, y + self.CH, fill="#e8f0fc" if d % 2 == 0 else "#d7e5fb", outline="white", tags=("rowhdr",))
                cv.create_text(self.HW // 2, y + self.CH // 2, text=f"{DAYS[d][:2]} {p + 1}", font=("Segoe UI", 10, "bold"), fill=INK, tags=("rowhdr",))
        cv.create_rectangle(0, 0, self.HW, self.HH, fill=BLUE, outline="white", tags=("rowhdr", "colhdr"))
        self.ox = self.oy = 0; self.draw()

    def draw(self):
        cv, P = self.cv, self.P; cv.delete("cell"); bad = G.cell_conflicts(self.cells)
        for d in range(5):
            for c in self.classes:
                for p in range(1, P + 1):
                    x0, y0 = self.xy((c, d, p)); r = self.cells.get((c, d, p)); x1, y1 = x0 + self.CW, y0 + self.CH
                    if not r:
                        cv.create_rectangle(x0, y0, x1, y1, fill="#fafbfd", outline="#e3e8f0", tags=("cell",)); continue
                    key = G.canon(r["subject"]); sc = G.difficulty(key, G.grade(c) or 0); out, w = "#cfd8e8", 1
                    if (c, d, p) in bad: out, w = "#d93025", 3
                    elif sc >= G.HARD_FROM and not 2 <= p <= 4: out, w = "#f29900", 3
                    cv.create_rectangle(x0, y0, x1, y1, fill=self.PALETTE[sum(map(ord, key)) % len(self.PALETTE)], outline=out, width=w, tags=("cell",))
                    cv.create_text(x0 + self.CW // 2, y0 + 18, text=r["subject"][:26], width=self.CW - 8, font=("Segoe UI", 9, "bold"), fill=INK, tags=("cell",))
                    cv.create_text(x0 + self.CW // 2, y0 + 40, text=(f"{self.short(r['teacher'])} · {r['cabinet']}" if r["teacher"] or r["cabinet"] else "")[:30],
                                   width=self.CW - 8, font=("Segoe UI", 8), fill="#44536e", tags=("cell",))
            y = self.HH + d * P * self.CH
            cv.create_line(0, y, self.HW + len(self.classes) * self.CW, y, fill=BLUE, width=2, tags=("cell",))
        cv.tag_raise("rowhdr"); cv.tag_raise("colhdr"); self.update_status()

    def sync(self):
        if not getattr(self, "cells", None): return
        x, y = self.cv.canvasx(0), self.cv.canvasy(0)
        self.cv.move("rowhdr", x - self.ox, 0); self.cv.move("colhdr", 0, y - self.oy); self.ox, self.oy = x, y

    def update_status(self):
        self.A = G.check_rows(self.src.rows(), self.P)
        if self.status is not None:
            A = self.A
            self.status.config(text=f"Конфликтов: {len(G.cell_conflicts(self.cells))}  ·  СанПиН: больше нормы {A['norm'][0]}, сложные не на 2–4 уроке {A['hard'][0]}, "
                                    f"окна {A['gap'][0]}, пик нагрузки не вт/ср {A['peak'][0]}")

    def report(self):
        w = tk.Toplevel(self.parent); w.title("Отчёт по СанПиН"); w.geometry("760x520")
        t = tk.Text(w, wrap="word", font=("Segoe UI", 10)); t.pack(fill="both", expand=True)
        t.insert("1.0", "\n".join(["ПРОВЕРКА РАСПИСАНИЯ", ""] + G.violation_lines(self.A)))

    def press(self, e):
        if e.x < self.HW or e.y < self.HH or not self.cells: return
        x, y = self.cv.canvasx(e.x), self.cv.canvasy(e.y); k = self.at(x, y)
        if k not in self.cells: return
        self.drag, self.gx, self.gy = k, x, y; x0, y0 = self.xy(k)
        self.cv.create_rectangle(x0, y0, x0 + self.CW, y0 + self.CH, outline=BLUE, width=3, tags=("ghost",))
        self.cv.create_rectangle(x0, y0, x0 + self.CW, y0 + self.CH, fill="#bcd4fb", outline=BLUE, width=2, tags=("ghost", "gmove"))
        self.cv.create_text(x0 + self.CW // 2, y0 + self.CH // 2, text=self.cells[k]["subject"][:26], font=("Segoe UI", 9, "bold"), fill=INK, tags=("ghost", "gmove"))

    def motion(self, e):
        if not self.drag: return
        x, y = self.cv.canvasx(e.x), self.cv.canvasy(e.y)
        self.cv.move("gmove", x - self.gx, y - self.gy); self.gx, self.gy = x, y
        self.cv.delete("hl"); k = self.at(x, y)
        if k and k != self.drag:
            x0, y0 = self.xy(k)
            self.cv.create_rectangle(x0, y0, x0 + self.CW, y0 + self.CH, outline="#1d8a4e" if k[0] == self.drag[0] else "#d93025", width=4, tags=("hl",))

    def release(self, e):
        if not self.drag: return
        src, self.drag = self.drag, None
        dst = self.at(self.cv.canvasx(e.x), self.cv.canvasy(e.y)); self.cv.delete("ghost", "hl")
        if not dst or dst == src: return
        if dst[0] != src[0]: return messagebox.showinfo("Таблица", "Урок можно переносить только внутри одного класса.")
        msgs = G.move_messages(self.cells, src, dst)
        if msgs and not messagebox.askyesno("Конфликт", "\n".join(sorted(set(msgs))) + "\n\nВсё равно переместить?"): return
        a, b = self.cells[src], self.cells.get(dst)
        self.src.move(a["id"], dst[1:], b["id"] if b else None, src[1:])
        self.reload(); self.draw()

SCHEMES = {"blue": ("#e8f0fc", "#0c5ac8"), "green": ("#e4f4ea", "#1d8a4e"), "purple": ("#f0e8fd", "#7e3fcf"), "orange": ("#fff0dc", "#d9780a")}
ICON = ("Segoe UI Symbol", 15, "bold")

def rounded(cv, x0, y0, x1, y1, r, **kw):
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return cv.create_polygon(pts, smooth=True, **kw)

class RButton(tk.Canvas):
    """Обычная скруглённая кнопка (замена ttk.Button). primary=True: синяя, для главного действия."""
    def __init__(self, parent, text="", command=None, state="normal", primary=False):
        f = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        try: bg = parent.cget("bg")
        except Exception: bg = "white"
        super().__init__(parent, width=f.measure(text) + 34, height=38, bg=bg, highlightthickness=0)
        self.text, self.cmd, self.state, self.primary, self.hover = text, command, state, primary, False
        self.bind("<Enter>", lambda e: self.set_hover(True)); self.bind("<Leave>", lambda e: self.set_hover(False))
        self.bind("<Button-1>", lambda e: self.cmd() if self.state == "normal" and self.cmd else None)
        self.draw()

    def set_hover(self, v): self.hover = v and self.state == "normal"; self.draw()

    def configure(self, cnf=None, **kw):
        if "state" in kw: self.state = kw.pop("state"); self.draw()
        if "text" in kw: self.text = kw.pop("text"); self.draw()
        if cnf or kw: return super().configure(cnf, **kw)
    config = configure

    def draw(self):
        self.delete("all"); off = self.state != "normal"
        if self.primary: fill, out, fg = ("#0a48a6" if self.hover else BLUE), BLUE, "white"
        else: fill, out, fg = ("#eef4ff" if self.hover else "white"), (BLUE if self.hover else "#d3ddee"), INK
        if off: fill, out, fg = "#f1f4f9", "#e3e8f0", "#9aa7bd"
        rounded(self, 1, 1, int(self["width"]) - 1, 37, 11, fill=fill, outline=out)
        self.create_text(int(self["width"]) // 2, 19, text=self.text, fill=fg, font=("Segoe UI", 10, "bold"))
        self.configure(cursor="hand2" if not off else "arrow")

class NavButton(tk.Canvas):
    """Пункт бокового меню: скруглённая плашка."""
    def __init__(self, parent, text, command):
        super().__init__(parent, height=46, bg=BLUE, highlightthickness=0, cursor="hand2")
        self.text, self.cmd, self.active, self.hover = text, command, False, False
        self.bind("<Configure>", lambda e: self.draw(e.width))
        self.bind("<Enter>", lambda e: self.set_hover(True)); self.bind("<Leave>", lambda e: self.set_hover(False))
        self.bind("<Button-1>", lambda e: self.cmd())

    def set_hover(self, v): self.hover = v; self.draw(self.winfo_width())
    def set_active(self, v): self.active = v; self.draw(self.winfo_width())

    def draw(self, w):
        self.delete("all")
        rounded(self, 1, 2, w - 1, 44, 12, fill="#5b95e6" if self.active else ("#3a7de0" if self.hover else "#2a6dd4"), outline="")
        self.create_text(16, 23, text=self.text, anchor="w", fill="white", font=("Segoe UI", 11, "bold"))

class Segmented(tk.Canvas):
    """Переключатель из нескольких вариантов в скруглённой плашке; выбранный вариант синий."""
    def __init__(self, parent, items, var, command=None):
        f = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        try: bg = parent.cget("bg")
        except Exception: bg = "white"
        ws = [f.measure(t) + 30 for _, t in items]
        super().__init__(parent, width=sum(ws) + 8, height=40, bg=bg, highlightthickness=0, cursor="hand2")
        self.items, self.ws, self.var, self.cmd = items, ws, var, command
        self.bind("<Button-1>", self.click); self.draw()

    def draw(self):
        self.delete("all"); rounded(self, 1, 1, sum(self.ws) + 7, 39, 12, fill="#f1f4f9", outline="#d3ddee"); x = 4
        for (v, t), w in zip(self.items, self.ws):
            on = self.var.get() == v
            if on: rounded(self, x, 4, x + w, 36, 9, fill=BLUE, outline="")
            self.create_text(x + w // 2, 20, text=t, fill="white" if on else INK, font=("Segoe UI", 10, "bold")); x += w

    def click(self, e):
        x = 4
        for (v, _), w in zip(self.items, self.ws):
            if x <= e.x < x + w:
                self.var.set(v); self.draw()
                if self.cmd: self.cmd()
                return
            x += w

class RowButton(tk.Canvas):
    """Кнопка-строка: скруглённая рамка, цветная иконка слева, жирная подпись."""
    def __init__(self, parent, text, glyph, scheme, command):
        super().__init__(parent, height=56, bg="white", highlightthickness=0, cursor="hand2")
        self.text, self.glyph, self.scheme, self.cmd, self.hover = text, glyph, scheme, command, False
        self.bind("<Configure>", lambda e: self.draw(e.width))
        self.bind("<Enter>", lambda e: self.set_hover(True)); self.bind("<Leave>", lambda e: self.set_hover(False))
        self.bind("<Button-1>", lambda e: self.cmd())

    def set_hover(self, v): self.hover = v; self.draw(self.winfo_width())

    def draw(self, w):
        self.delete("all"); bg, fg = SCHEMES[self.scheme]
        rounded(self, 2, 2, w - 2, 54, 10, fill="#f4f8ff" if self.hover else "white", outline="#b9cff5" if self.hover else "#e3e8f0")
        rounded(self, 12, 10, 48, 46, 9, fill=bg, outline=bg)
        self.create_text(30, 28, text=self.glyph, fill=fg, font=ICON)
        self.create_text(62, 28, text=self.text, anchor="w", fill=INK, font=("Segoe UI", 10, "bold"))

class Card(tk.Canvas):
    """Карточка раздела: иконка и заголовок сверху, под ними кнопки-строки."""
    def __init__(self, parent, title, glyph, scheme, items, on_click):
        super().__init__(parent, bg=BG, highlightthickness=0, height=200)
        self.inner = tk.Frame(self, bg="white"); self.win = self.create_window(18, 18, anchor="nw", window=self.inner)
        head = tk.Frame(self.inner, bg="white"); head.pack(fill="x", pady=(0, 12))
        tk.Label(head, text=title, bg="white", fg=INK, font=("Segoe UI", 13, "bold")).pack(side="left")
        for text, g, key in items: RowButton(self.inner, text, g, scheme, lambda k=key: on_click(k)).pack(fill="x", pady=3)
        self.inner.bind("<Configure>", lambda e: self.configure(height=e.height + 36))
        self.bind("<Configure>", self.draw)

    def draw(self, e):
        self.delete("bg"); rounded(self, 1, 1, e.width - 1, e.height - 1, 16, fill="white", outline="#e3e8f0", tags=("bg",))
        self.tag_lower("bg"); self.itemconfigure(self.win, width=e.width - 36)

HOME = [("Расписание", "☰", "blue", [("Расписание на день и неделю", "☰", "sched"), ("Таблица расписания", "▦", "grid")]),
        ("Замены и изменения", "↔", "green", [("Изменить расписание на день", "✎", "edit"), ("Просмотр изменений", "☷", "changes")]),
        ("Составление расписания", "✚", "purple", [("Создать расписание", "★", "create"), ("Редактор расписания", "✐", "editor")]),
        ("Данные", "↑", "orange", [("Загрузить расписание из Excel", "↑", "upload"), ("Расписание звонков", "♪", "bells")])]

# ---------- окно ----------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        init_db(); gen_init()
        self.title("Расписание"); self.geometry("1050x680"); self.minsize(820, 520); self.configure(bg=BG)
        st = ttk.Style(self); st.theme_use("clam")
        st.configure("Treeview", rowheight=36, font=("Segoe UI", 10), borderwidth=0, background="white", fieldbackground="white", foreground=INK)
        st.map("Treeview", background=[("selected", "#dbe8ff")], foreground=[("selected", INK)])
        st.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), background="#eef3fb", foreground=INK, relief="flat", padding=(10, 9),
                     borderwidth=0, bordercolor="#e3e8f0", lightcolor="#eef3fb", darkcolor="#eef3fb")
        st.map("Treeview.Heading", background=[("active", "#e1ebfa")])
        st.configure("TNotebook", background="white", borderwidth=0, tabmargins=(0, 0, 0, 0))
        st.configure("TNotebook.Tab", padding=(18, 9), font=("Segoe UI", 10, "bold"), background="#eef3fb", foreground=INK, borderwidth=0)
        st.map("TNotebook.Tab", background=[("selected", "white")], foreground=[("selected", BLUE)])
        st.configure("TCombobox", fieldbackground="white", background="white", bordercolor="#d3ddee", lightcolor="white", darkcolor="white", arrowcolor=BLUE, padding=7)
        st.map("TCombobox", fieldbackground=[("readonly", "white")], bordercolor=[("focus", BLUE)])
        st.configure("TScrollbar", background="#c9d6ea", troughcolor="#f1f4f9", bordercolor="#f1f4f9", lightcolor="#c9d6ea", darkcolor="#c9d6ea", arrowcolor=BLUE, relief="flat")
        st.configure("TButton", background="white", foreground=INK, bordercolor="#d3ddee", lightcolor="white", darkcolor="white",
                     focuscolor="white", padding=(14, 7), font=("Segoe UI", 10, "bold"))
        st.map("TButton", background=[("pressed", "#dce9ff"), ("active", "#eef4ff")], bordercolor=[("active", BLUE)]); st.configure("TRadiobutton", background="white")
        self.mode, self.cls, self.dayvar, self.edvar = tk.StringVar(value="week" if date.today().weekday() >= 5 else "today"), tk.StringVar(), tk.StringVar(), tk.StringVar()
        side = tk.Frame(self, bg=BLUE, width=230); side.pack(side="left", fill="y"); side.pack_propagate(False)
        tk.Label(side, text="Расписание", bg=BLUE, fg="white", font=("Segoe UI", 17, "bold")).pack(anchor="w", padx=18, pady=(20, 0))
        tk.Label(side, text="Школа", bg=BLUE, fg="#8fd3ff", font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=18, pady=(0, 18))
        self.nav = {}
        for key, text in (("home", "Главная"), ("sched", "Расписание"), ("grid", "Таблица расписания"), ("edit", "Изменить расписание"), ("editor", "Редактор расписания"), ("create", "Создать расписание"), ("changes", "Просмотр изменений"),
                          ("upload", "Загрузить расписание"), ("bells", "Расписание звонков")):
            b = NavButton(side, text, lambda k=key: self.show(k))
            b.pack(fill="x", padx=10, pady=2); self.nav[key] = b
        right = tk.Frame(self, bg=BG); right.pack(side="left", fill="both", expand=True, padx=16, pady=14)
        self.body = tk.Frame(right, bg="white", highlightbackground="#e3e8f0", highlightthickness=1)
        self.body.pack(fill="both", expand=True)
        self.show("home")

    def report_callback_exception(self, exc, val, tb):
        import traceback
        msg = "".join(traceback.format_exception(exc, val, tb))
        try: open(os.path.join(APP, "error.log"), "a", encoding="utf-8").write(msg + "\n")
        except OSError: pass
        messagebox.showerror("Ошибка в программе", msg[-1500:])

    def show(self, key):
        for k, b in self.nav.items(): b.set_active(k == key)
        for w in self.body.winfo_children(): w.destroy()
        self.key = key; getattr(self, "page_" + key)()

    def bar(self):
        f = tk.Frame(self.body, bg="white"); f.pack(fill="x", padx=14, pady=10); return f

    def class_box(self, bar, cmd):
        cl = classes()
        if self.cls.get() not in cl: self.cls.set(cl[0] if cl else "")
        label = lambda: f"Класс: {self.cls.get().upper()}  ▾"
        btn = RButton(bar, text=label()); btn.pack(side="left", padx=(14, 0))
        menu = tk.Menu(btn, tearoff=0, font=("Segoe UI", 11))
        def choose(c): self.cls.set(c); btn.configure(text=label()); cmd()
        for i, c in enumerate(cl): menu.add_command(label=c.upper(), columnbreak=bool(i and i % 10 == 0), command=lambda c=c: choose(c))
        def popup():
            try: menu.tk_popup(btn.winfo_rootx(), btn.winfo_rooty() + btn.winfo_height())
            finally: menu.grab_release()
        btn.cmd = popup

    def tree(self, cols, heads, widths):
        f = tk.Frame(self.body, bg="white"); f.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        t = ttk.Treeview(f, columns=cols, show="headings" if heads[0] else "tree headings")
        for c, h, w in zip(cols, heads, widths): t.heading(c, text=h); t.column(c, width=w, anchor="w")
        sb = ttk.Scrollbar(f, command=t.yview); t.configure(yscrollcommand=sb.set)
        t.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        t.tag_configure("day", background="#e8f0fc", font=("Segoe UI", 10, "bold"))
        t.tag_configure("chg", background="#fff4d6"); return t

    def fill(self, t, days):
        b = bells(); cls = self.cls.get()
        for d in days:
            rows = [r for r in effective(d) if r["cls"].lower() == cls.lower()]
            mark = " (изменено)" if any(r["changed"] for r in rows) else ""
            t.insert("", "end", iid=f"h{d}", text="", values=(f"{DAYS[d.weekday()].upper()}{mark} – {d:%d.%m.%Y}", "", "", ""), tags=("day",))
            if not rows: t.insert("", "end", values=("", "Нет уроков", "", ""))
            for r in rows:
                tm = b.get(str(r["lesson"]), "").replace(" ", "").replace("-", " – ") or f"{r['lesson']} урок"
                tea = r["teacher"] + (f"   (было: {r['old_t']})" if r["old_t"] else "")
                cab = r["cab"] + (f" (было {r['old_c']})" if r["old_c"] else "")
                t.insert("", "end", iid=f"{d.isoformat()}|{r['lesson']}",
                         values=(f"{r['lesson']}. {tm}", r["subject"] + (" (изменено)" if r["changed"] else ""), tea, cab),
                         tags=("chg",) if r["changed"] else ())

    def page_sched(self):
        bar = self.bar()
        Segmented(bar, (("today", "Сегодня"), ("tomorrow", "Завтра"), ("week", "Неделя")), self.mode, self.page_refresh).pack(side="left")
        self.class_box(bar, self.page_refresh)
        self.t = self.tree(("a", "b", "c", "d"), ("Время", "Предмет", "Учитель", "Каб."), (170, 260, 280, 120))
        self.empty = tk.Label(self.body, bg="white", fg="#6f7d97", font=("Segoe UI", 15, "bold"))
        self.page_refresh()

    def page_refresh(self):
        for i in self.t.get_children(): self.t.delete(i)
        w, wk, m = date.today().weekday(), week_dates(), self.mode.get()
        if m == "today": days = [wk[w]] if w <= 4 else []
        elif m == "tomorrow": days = [wk[w + 1]] if w < 4 else []
        else: days = wk
        if days:
            self.empty.pack_forget(); self.t.master.pack(fill="both", expand=True, padx=14, pady=(0, 14)); self.fill(self.t, days)
        else:
            self.t.master.pack_forget(); self.empty.config(text="Сегодня выходной" if m == "today" else "Завтра выходной"); self.empty.pack(pady=70)

    def page_edit(self):
        bar = self.bar(); wk = week_dates()
        self.class_box(bar, self.edit_refresh)
        vals = [f"{DAYS[i]} {d:%d.%m}" for i, d in enumerate(wk)]
        if self.dayvar.get() not in vals: self.dayvar.set(vals[min(date.today().weekday(), 4)])
        Segmented(bar, [(v, f"{v[:2]} {v[-5:]}") for v in vals], self.dayvar, self.edit_refresh).pack(side="left", padx=(14, 0))
        RButton(bar, text="Изменить выбранный урок", command=self.edit_dialog).pack(side="right")
        tk.Label(self.body, text="Выберите урок и нажмите кнопку (или дважды щёлкните по нему). Замена действует только на этот день.",
                 bg="white", fg="#6f7d97").pack(anchor="w", padx=14)
        self.t = self.tree(("a", "b", "c", "d"), ("Время", "Предмет", "Учитель", "Каб."), (170, 260, 280, 120))
        self.t.bind("<Double-1>", lambda e: self.edit_dialog()); self.edit_refresh()

    def edit_day(self):
        names = [f"{DAYS[i]} {d:%d.%m}" for i, d in enumerate(week_dates())]
        return week_dates()[names.index(self.dayvar.get())]

    def edit_refresh(self):
        for i in self.t.get_children(): self.t.delete(i)
        self.fill(self.t, [self.edit_day()])

    def edit_dialog(self):
        sel = self.t.selection()
        if not sel or "|" not in sel[0]: return messagebox.showinfo("Изменить", "Выберите урок в списке.")
        ds, les = sel[0].split("|"); d, les, cls = date.fromisoformat(ds), int(les), self.cls.get()
        r = next(x for x in effective(d) if x["lesson"] == les and x["cls"].lower() == cls.lower())
        ft, fc = free(d, les, cls, r["old_t"] or r["teacher"])
        w = tk.Toplevel(self); w.title("Замена"); w.geometry("380x290"); w.configure(bg="white"); w.transient(self); w.grab_set()
        tk.Label(w, text=f"{cls.upper()}, {les} урок, {r['subject']}", bg="white", font=("Segoe UI", 11, "bold")).pack(pady=(14, 8))
        NO = "(без изменений)"; vt, vc = tk.StringVar(value=NO), tk.StringVar(value=NO)
        for lab, var, vals in (("Учитель", vt, ft), ("Кабинет", vc, fc)):
            tk.Label(w, text=lab, bg="white").pack(anchor="w", padx=20)
            ttk.Combobox(w, textvariable=var, values=[NO] + vals, state="readonly").pack(fill="x", padx=20, pady=(0, 8))
        def save():
            set_change(cls, d, les, None if vt.get() == NO else vt.get(), None if vc.get() == NO else vc.get())
            w.destroy(); self.edit_refresh()
        def undo(): del_change(cls, ds, les); w.destroy(); self.edit_refresh()
        f = tk.Frame(w, bg="white"); f.pack(pady=10)
        RButton(f, text="Сохранить", command=save).pack(side="left", padx=4)
        RButton(f, text="Отменить изменение", command=undo).pack(side="left", padx=4)

    def form(self, title, fields):
        """fields: [(подпись, значение, подсказки или None)] -> список введённых значений или None."""
        w = tk.Toplevel(self); w.title(title); w.configure(bg="white"); w.transient(self); w.grab_set(); w.resizable(False, False)
        vs = []
        for lab, val, opts in fields:
            tk.Label(w, text=lab, bg="white").pack(anchor="w", padx=20, pady=(10, 0))
            v = tk.StringVar(value=val); vs.append(v)
            (ttk.Combobox(w, textvariable=v, values=opts, width=34) if opts is not None
             else ttk.Entry(w, textvariable=v, width=37)).pack(padx=20)
        res = []
        def ok(): res.append([v.get().strip() for v in vs]); w.destroy()
        f = tk.Frame(w, bg="white"); f.pack(pady=14)
        RButton(f, text="Сохранить", command=ok).pack(side="left", padx=4)
        RButton(f, text="Отмена", command=w.destroy).pack(side="left", padx=4)
        self.wait_window(w); return res[0] if res else None

    def page_editor(self):
        bar = self.bar(); self.class_box(bar, self.ed_refresh)
        if self.edvar.get() not in DAYS: self.edvar.set(DAYS[0])
        Segmented(bar, [(d, d[:2]) for d in DAYS], self.edvar, self.ed_refresh).pack(side="left", padx=(14, 0))
        RButton(bar, text="Удалить класс", command=self.del_class).pack(side="right")
        RButton(bar, text="Новый класс", command=self.new_class).pack(side="right", padx=6)
        b2 = self.bar()
        RButton(b2, text="Добавить урок", command=lambda: self.lesson_edit(None)).pack(side="left")
        RButton(b2, text="Изменить", command=lambda: self.lesson_edit(self.sel_lesson())).pack(side="left", padx=6)
        RButton(b2, text="Удалить урок", command=self.lesson_del).pack(side="left")
        self.t = self.tree(("a", "b", "c", "d"), ("Урок", "Предмет", "Учитель", "Каб."), (80, 280, 280, 100))
        self.t.bind("<Double-1>", lambda e: self.lesson_edit(self.sel_lesson())); self.ed_refresh()

    def ed_refresh(self):
        for i in self.t.get_children(): self.t.delete(i)
        for rid, les, subj, tea, cab in lesson_rows(self.cls.get(), self.edvar.get()):
            self.t.insert("", "end", iid=str(rid), values=(les, subj, tea or "", cab or ""))

    def sel_lesson(self):
        sel = self.t.selection()
        if not sel: messagebox.showinfo("Редактор", "Выберите урок в списке."); return None
        return q("SELECT id,lesson,subject,teacher,cabinet FROM schedule WHERE id=?", (int(sel[0]),))[0]

    def new_class(self):
        v = self.form("Новый класс", [("Название класса (например, 9а)", "", None)])
        if v and v[0]: EXTRA.add(v[0].lower()); self.cls.set(v[0].lower()); self.show("editor")

    def del_class(self):
        c = self.cls.get()
        if c and messagebox.askyesno("Удалить класс", f"Удалить класс {c.upper()} и всё его расписание?"):
            q("DELETE FROM schedule WHERE LOWER(class_name)=LOWER(?)", (c,)); EXTRA.discard(c); self.show("editor")

    def lesson_edit(self, row):
        cls, day = self.cls.get(), self.edvar.get()
        if not cls: return messagebox.showinfo("Редактор", "Сначала создайте класс (кнопка «Новый класс»).")
        pre = row or (None, "", "", "", "")
        uniq = lambda col: sorted({r[0].strip() for r in q(f"SELECT {col} FROM schedule") if r[0] and r[0].strip()})
        nums = sorted(set(list(bells()) + [str(i) for i in range(1, 9)]), key=int)
        v = self.form(f"{cls.upper()} · {day}", [("Номер урока", str(pre[1]), nums), ("Предмет", pre[2], uniq("subject")),
                                                 ("Учитель", pre[3] or "", uniq("teacher")), ("Кабинет", pre[4] or "", uniq("cabinet"))])
        if not v: return
        try: num = int(v[0])
        except ValueError: return messagebox.showerror("Ошибка", "Номер урока должен быть числом.")
        if not v[1]: return messagebox.showerror("Ошибка", "Введите предмет.")
        if any(r[0] != pre[0] and r[1] == num for r in lesson_rows(cls, day)):
            return messagebox.showerror("Ошибка", f"У {cls.upper()} в этот день уже есть {num} урок.")
        bad = conflicts(day, num, cls, v[2], v[3])
        if bad and not messagebox.askyesno("Конфликт", "\n".join(bad) + "\n\nВсё равно сохранить?"): return
        if pre[0] is None: add_lesson(day, num, cls, v[1], v[3], v[2])
        else: update_lesson(pre[0], num, v[1], v[3], v[2])
        self.ed_refresh()

    def lesson_del(self):
        r = self.sel_lesson()
        if r and messagebox.askyesno("Удалить", f"Удалить {r[1]} урок ({r[2]})?"):
            q("DELETE FROM schedule WHERE id=?", (r[0],)); self.ed_refresh()

    def bell_edit(self):
        sel = self.t.selection(); b = bells(); k = sel[0] if sel else ""
        v = self.form("Звонок", [("Номер урока", k, None), ("Время (например, 8:10 - 08:50)", b.get(k, ""), None)])
        if not v: return
        if not v[0].isdigit() or not re.fullmatch(r"\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}", v[1]):
            return messagebox.showerror("Ошибка", "Номер урока — число, время — в виде 8:10 - 08:50.")
        b[str(int(v[0]))] = v[1]; save_bells(b); self.show("bells")

    def bell_del(self):
        sel = self.t.selection()
        if sel and messagebox.askyesno("Удалить", f"Удалить {sel[0]} урок из расписания звонков?"):
            b = bells(); b.pop(sel[0], None); save_bells(b); self.show("bells")

    # ---------- вкладка «Создать расписание» ----------
    def page_create(self):
        nb = ttk.Notebook(self.body); nb.pack(fill="both", expand=True, padx=10, pady=10)
        d, b, g = (tk.Frame(nb, bg="white") for _ in range(3))
        nb.add(d, text="1. Данные"); nb.add(b, text="2. Звонки"); nb.add(g, text="3. Составить")
        top = tk.Frame(d, bg="white"); top.pack(fill="x", pady=8, padx=6)
        RButton(top, text="Загрузить данные из Excel", primary=True, command=self.data_import).pack(side="left")
        RButton(top, text="Скачать пример файла", command=self.data_template).pack(side="left", padx=6)
        tk.Label(top, text="или заполните таблицы вручную:", bg="white", fg="#6f7d97").pack(side="left", padx=8)
        inner = ttk.Notebook(d); inner.pack(fill="both", expand=True)
        for t, name in (("gen_teachers", "Учителя"), ("gen_rooms", "Кабинеты"), ("gen_plan", "Учебный план (часов в неделю)"),
                        ("gen_limits", "Лимит нагрузки")):
            inner.add(self.crud(inner, t), text=name)
        self.bells_tab(b); self.gen_tab(g)

    def crud(self, parent, table):
        cols, heads, widths = GEN[table]; f = tk.Frame(parent, bg="white")
        bar = tk.Frame(f, bg="white"); bar.pack(fill="x", pady=6)
        box = tk.Frame(f, bg="white"); box.pack(fill="both", expand=True)
        t = ttk.Treeview(box, columns=cols, show="headings")
        for c, h, w in zip(cols, heads, widths): t.heading(c, text=h); t.column(c, width=w, anchor="w")
        sb = ttk.Scrollbar(box, command=t.yview); t.configure(yscrollcommand=sb.set)
        t.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        def refresh():
            for i in t.get_children(): t.delete(i)
            for r in q(f"SELECT id,{','.join(cols)} FROM {table} ORDER BY id"): t.insert("", "end", iid=str(r[0]), values=[x or "" for x in r[1:]])
        def edit(new):
            sel = t.selection()
            if not new and not sel: return messagebox.showinfo("Данные", "Выберите строку в таблице.")
            cur = [""] * len(cols) if new else [x or "" for x in q(f"SELECT {','.join(cols)} FROM {table} WHERE id=?", (int(sel[0]),))[0]]
            v = self.form("Запись", [(h, c, None) for h, c in zip(heads, cur)])
            if not v: return
            if new: q(f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join('?' * len(cols))})", v)
            else: q(f"UPDATE {table} SET {','.join(c + '=?' for c in cols)} WHERE id=?", v + [int(sel[0])])
            refresh()
        def delete():
            for i in t.selection(): q(f"DELETE FROM {table} WHERE id=?", (int(i),))
            refresh()
        RButton(bar, text="Добавить", command=lambda: edit(True)).pack(side="left")
        RButton(bar, text="Изменить", command=lambda: edit(False)).pack(side="left", padx=6)
        RButton(bar, text="Удалить", command=delete).pack(side="left")
        t.bind("<Double-1>", lambda e: edit(False)); refresh(); return f

    def data_template(self):
        p = filedialog.asksaveasfilename(defaultextension=".xlsx", initialfile="Пример_данных.xlsx")
        if p: shutil.copy(os.path.join(RES, "templates", "data.xlsx"), p)

    def data_import(self):
        p = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx")])
        if not p: return
        try: d = G.parse_excel(read_xlsx(p))
        except ValueError as e: return messagebox.showerror("Ошибка", str(e))
        if q("SELECT 1 FROM gen_teachers LIMIT 1") and not messagebox.askyesno("Загрузка", "Данные в таблицах будут заменены. Продолжить?"): return
        gen_replace("gen_teachers", d["teachers"]); gen_replace("gen_rooms", d["rooms"])
        gen_replace("gen_plan", d["plan"]); gen_replace("gen_limits", d["limits"])
        messagebox.showinfo("Готово", f"Учителей: {len(d['teachers'])}\nКабинетов: {len(d['rooms'])}\n"
                                      f"Предметов в плане: {len(d['plan'])}\nЛимитов нагрузки: {len(d['limits'])}")
        self.show("create")

    def bells_tab(self, parent):
        bar = tk.Frame(parent, bg="white"); bar.pack(fill="x", pady=8, padx=6)
        box = tk.Frame(parent, bg="white"); box.pack(fill="both", expand=True, padx=6)
        t = ttk.Treeview(box, columns=("a", "b"), show="headings")
        for c, h, w in (("a", "Урок", 100), ("b", "Время", 220)): t.heading(c, text=h); t.column(c, width=w)
        t.pack(side="left", fill="both", expand=True)
        def refresh():
            for i in t.get_children(): t.delete(i)
            for k, v in sorted(bells().items(), key=lambda x: int(x[0])): t.insert("", "end", iid=k, values=(f"{k} урок", v.replace(" ", "")))
        def edit():
            sel = t.selection(); k = sel[0] if sel else str(len(bells()) + 1)
            v = self.form("Звонок", [("Номер урока", k, None), ("Время (например, 8:10 - 08:50)", bells().get(k, ""), None)])
            if not v: return
            if not v[0].isdigit() or not re.fullmatch(r"\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}", v[1]):
                return messagebox.showerror("Ошибка", "Номер урока — число, время — в виде 8:10 - 08:50.")
            b = bells(); b[str(int(v[0]))] = v[1]; save_bells(b); refresh()
        def delete():
            b = bells()
            for i in t.selection(): b.pop(i, None)
            save_bells(b); refresh()
        def auto():
            v = self.form("Автозаполнение звонков", [("Начало 1-го урока", "8:10", None), ("Длительность урока, мин", "40", None),
                                                     ("Перемена, мин", "10", None), ("Количество уроков", "7", None)])
            if not v: return
            try:
                h, m = map(int, v[0].split(":")); ln, br, n = int(v[1]), int(v[2]), int(v[3]); cur = h * 60 + m; b = {}
                for i in range(1, n + 1):
                    b[str(i)] = f"{cur // 60}:{cur % 60:02d} - {(cur + ln) // 60:02d}:{(cur + ln) % 60:02d}"; cur += ln + br
            except ValueError: return messagebox.showerror("Ошибка", "Проверьте значения: время в виде 8:10, остальное числа.")
            save_bells(b); refresh()
        RButton(bar, text="Добавить / изменить", command=edit).pack(side="left")
        RButton(bar, text="Удалить", command=delete).pack(side="left", padx=6)
        RButton(bar, text="Заполнить автоматически", command=auto).pack(side="left")
        t.bind("<Double-1>", lambda e: edit()); refresh()

    def gen_tab(self, parent):
        tk.Label(parent, justify="left", bg="white", fg="#6f7d97", text=(
            "Программа составит расписание из данных (учителя, кабинеты, учебный план) с учётом лимитов нагрузки,\n"
            "занятости учителей и кабинетов. Результат откроется таблицей: её можно править перетаскиванием,\n"
            "а текущее расписание заменится, только когда вы нажмёте «Применить».")).pack(anchor="w", padx=10, pady=(10, 4))
        bar = tk.Frame(parent, bg="white"); bar.pack(fill="x", padx=10, pady=6)
        mode = tk.StringVar(value="Обычно (30 попыток)")
        ttk.Combobox(bar, textvariable=mode, state="readonly", width=24, values=["Быстро (10 попыток)", "Обычно (30 попыток)", "Тщательно (100 попыток)"]).pack(side="left")
        st = tk.Label(bar, bg="white", fg="#6f7d97"); res = {}
        box = tk.Frame(parent, bg="white"); box.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        txt = tk.Text(box, wrap="word", font=("Segoe UI", 10), relief="flat", bg="#f9fbfe"); sb = ttk.Scrollbar(box, command=txt.yview)
        txt.configure(yscrollcommand=sb.set); txt.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        def run():
            M = G.build_data(q("SELECT name,subjects,classes FROM gen_teachers ORDER BY id"), q("SELECT name,subject FROM gen_rooms ORDER BY id"),
                             q("SELECT subject,g5,g6,g7,g8,g9,g10,g11 FROM gen_plan ORDER BY id"), q("SELECT grade,week FROM gen_limits"))
            bl = [int(k) for k in bells()]; P = min(max(bl), 8) if bl else 7
            n = int(mode.get().split("(")[1].split()[0])
            def prog(i, tot, sc): st.config(text=f"Попытка {i} из {tot}: не размещено {sc[0]}"); self.update()
            try: r = G.generate(M, P, n, prog, 40)
            except ValueError as e: return messagebox.showerror("Ошибка", str(e))
            res.clear(); res.update(r); st.config(text="Готово")
            txt.delete("1.0", "end"); txt.insert("1.0", r["text"])
            res["src"] = MemSource(r["rows"]); sh.config(state="normal"); self.preview(res)
        RButton(bar, text="Составить расписание", primary=True, command=run).pack(side="left", padx=8)
        sh = RButton(bar, text="Показать таблицу", command=lambda: self.preview(res), state="disabled"); sh.pack(side="left")
        st.pack(side="left", padx=10)

    # ---------- таблица расписания ----------
    def page_grid(self):
        bar = self.bar()
        st = tk.Label(bar, bg="white", fg="#6f7d97")
        RButton(bar, text="Скачать Excel", command=lambda: self.export_excel()).pack(side="left")
        RButton(bar, text="Отчёт по СанПиН", command=lambda: self.grid.report()).pack(side="left", padx=6)
        st.pack(side="left", padx=10)
        tk.Label(self.body, bg="white", fg="#6f7d97", justify="left", wraplength=780, text=self.GRID_HINT).pack(anchor="w", padx=14)
        self.grid = Grid(self.body, DBSource(), st)

    GRID_HINT = ("Перетащите урок на другую клетку того же класса. Если клетка занята, уроки поменяются местами. "
                 "Красная рамка: конфликт (учитель или кабинет в двух местах), оранжевая: сложный предмет не на 2–4 уроке.")

    def export_excel(self, rows=None):
        p = filedialog.asksaveasfilename(defaultextension=".xlsx", initialfile="Расписание.xlsx", filetypes=[("Excel", "*.xlsx")])
        if not p: return
        try: export_schedule_xlsx(p, rows)
        except ImportError: return messagebox.showerror("Ошибка", "Установите openpyxl: pip install openpyxl")
        except (ValueError, OSError) as e: return messagebox.showerror("Ошибка", str(e))
        messagebox.showinfo("Готово", "Расписание сохранено в Excel.")

    def apply_schedule(self, rows, window=None):
        if not messagebox.askyesno("Применить", "Текущее расписание будет заменено новым. Замены на отдельные дни сохранятся. Продолжить?"): return
        con = sqlite3.connect(DB); con.execute("DELETE FROM schedule")
        con.executemany("INSERT INTO schedule(day,lesson,class_name,subject,cabinet,teacher) VALUES(?,?,?,?,?,?)", rows)
        con.commit(); con.close(); EXTRA.clear()
        if window: window.destroy()
        messagebox.showinfo("Готово", "Расписание сохранено. Его можно править перетаскиванием в разделе «Таблица расписания»."); self.show("grid")

    def preview(self, res):
        w = tk.Toplevel(self); w.title("Составленное расписание (ещё не сохранено)"); w.geometry("1220x740"); w.configure(bg="white")
        bar = tk.Frame(w, bg="white"); bar.pack(fill="x", padx=14, pady=(12, 0)); st = tk.Label(bar, bg="white", fg="#6f7d97")
        RButton(bar, text="Применить как текущее расписание", primary=True, command=lambda: self.apply_schedule(res["src"].rows(), w)).pack(side="left")
        RButton(bar, text="Скачать Excel", command=lambda: self.export_excel(res["src"].rows())).pack(side="left", padx=6)
        RButton(bar, text="Отчёт по СанПиН", command=lambda: g.report()).pack(side="left")
        st.pack(side="left", padx=10)
        tk.Label(w, bg="white", fg="#6f7d97", justify="left", wraplength=1100, anchor="w",
                 text="Это предпросмотр: расписание в базу ещё не записано. Правьте его перетаскиванием, затем нажмите «Применить». " + self.GRID_HINT).pack(anchor="w", padx=14, pady=4)
        g = Grid(w, res["src"], st)

    def page_home(self):
        f = tk.Frame(self.body, bg=BG); f.pack(fill="both", expand=True)
        tk.Label(f, text="Что будем делать?", bg=BG, fg=INK, font=("Segoe UI", 17, "bold")).pack(anchor="w", padx=20, pady=(18, 6))
        g = tk.Frame(f, bg=BG); g.pack(fill="x", padx=14); g.columnconfigure((0, 1), weight=1, uniform="c")
        for i, (title, glyph, scheme, items) in enumerate(HOME):
            Card(g, title, glyph, scheme, items, self.show).grid(row=i // 2, column=i % 2, sticky="new", padx=6, pady=8)

    def page_changes(self):
        bar = self.bar(); RButton(bar, text="Отменить выбранное изменение", command=self.cancel_sel).pack(side="left")
        self.t = self.tree(("a", "b", "c", "d", "e", "f"), ("Класс", "Дата", "Урок", "Предмет", "Учитель", "Кабинет"), (70, 100, 60, 180, 280, 130))
        rows = all_changes()
        if not rows: self.t.insert("", "end", values=("", "", "", "Изменений расписания нет.", "", ""))
        for cl, vd, les, subj, ot, nt, oc, nc in rows:
            self.t.insert("", "end", iid=f"{cl}|{vd}|{les}", values=(
                cl.upper(), date.fromisoformat(vd).strftime("%d.%m.%Y"), les, subj or "",
                f"{ot} → {nt}" if nt else "", f"{oc} → {nc}" if nc else ""))

    def cancel_sel(self):
        for s in self.t.selection():
            cl, vd, les = s.split("|"); del_change(cl, vd, int(les))
        self.show("changes")

    def upload_page(self, title, kind, hint, fn, done):
        tk.Label(self.body, text=title, bg="white", fg=INK, font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=18, pady=(16, 4))
        tk.Label(self.body, text=hint, bg="white", fg="#6f7d97", justify="left").pack(anchor="w", padx=18)
        f = tk.Frame(self.body, bg="white"); f.pack(anchor="w", padx=18, pady=14)
        def tpl():
            p = filedialog.asksaveasfilename(defaultextension=".xlsx", initialfile=f"Шаблон_{kind}.xlsx")
            if p: shutil.copy(os.path.join(RES, "templates", f"{kind}.xlsx"), p)
        def load():
            p = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx")])
            if not p: return
            if kind == "schedule" and not messagebox.askyesno("Загрузка", "Текущее расписание будет заменено. Продолжить?"): return
            try: messagebox.showinfo("Готово", done(fn(p)))
            except ValueError as e: messagebox.showerror("Ошибка", str(e))
            self.show(self.key)
        RButton(f, text="Скачать шаблон Excel", command=tpl).pack(side="left", padx=(0, 8))
        RButton(f, text="Выбрать файл и загрузить", primary=True, command=load).pack(side="left")

    def page_upload(self):
        self.upload_page("Загрузить расписание", "schedule", "Скачайте шаблон, заполните его и загрузите.\nСтарое расписание будет заменено.",
                         import_schedule, lambda r: f"Расписание загружено.\nУроков: {r[0]}, классов: {r[1]}")

    def page_bells(self):
        self.upload_page("Расписание звонков", "bells", "Скачайте шаблон, заполните время уроков и загрузите.",
                         import_bells, lambda n: f"Расписание звонков добавлено.\nУроков: {n}")
        bar = self.bar()
        RButton(bar, text="Добавить / изменить звонок", command=self.bell_edit).pack(side="left")
        RButton(bar, text="Удалить выбранный", command=self.bell_del).pack(side="left", padx=6)
        self.t = self.tree(("a", "b"), ("Урок", "Время"), (120, 220))
        self.t.bind("<Double-1>", lambda e: self.bell_edit())
        for k, v in sorted(bells().items(), key=lambda x: int(x[0])): self.t.insert("", "end", iid=k, values=(f"{k} урок", v.replace(" ", "")))

if __name__ == "__main__":
    App().mainloop()