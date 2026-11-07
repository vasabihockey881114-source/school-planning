"""Составление расписания из данных: учителя, кабинеты, учебный план, лимиты. Без tkinter — можно тестировать отдельно."""
import re, random, time

DAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница"]
WEEK = {5: 29, 6: 30, 7: 32, 8: 33, 9: 33, 10: 34, 11: 34}   # макс. уроков в неделю (если нет в файле)
DAILY = {5: 6, 6: 6, 7: 7, 8: 7, 9: 7, 10: 7, 11: 7}         # макс. уроков в день (проверьте по актуальному СанПиН)
# Шкала трудности: СанПиН 1.2.3685-21, таблица 6.10 (5–9 классы). Порядок: 5, 6, 7, 8, 9 классы; None — предмета нет в таблице.
SCALE = {"физика": [None, None, 8, 9, 13], "химия": [None, None, None, 10, 12], "история": [5, 8, 6, 8, 10],
         "английский язык": [9, 11, 10, 8, 9], "математика": [10, 13, None, None, None], "геометрия": [None, None, 12, 10, 8],
         "алгебра": [None, None, 10, 9, 7], "биология": [10, 8, 7, 7, 7], "литература": [4, 6, 4, 4, 7],
         "информатика": [4, 10, 4, 7, 7], "русский язык": [8, 12, 11, 7, 6], "география": [None, 7, 6, 6, 5],
         "музыка": [2, 1, 1, 1, None], "обществознание": [6, 9, 9, 5, 5], "труд": [4, 3, 2, 1, 4],
         "обзр": [1, 2, 3, 3, 3], "физкультура": [3, 4, 2, 2, 2], "искусство": [3, 3, 1, None, None]}  # «искусство» = ИЗО
HARD_FROM = 9      # предмет считается «сложным» от стольких баллов (рекомендация: сложные — на 2–4 уроки)
# Веса нарушений (чем больше, тем важнее избежать)
W_NORM, W_POS, W_WEEK, W_GAP, W_SAME, W_EVEN = 200, 1.5, 1.0, 10, 6, 4
SPORT_CAP = 2                                                # сколько классов одновременно в спортзале
ALIAS = {"русский": "русский язык", "ин яз": "английский язык", "английский": "английский язык",
         "иностранный язык": "английский язык", "физ культура": "физкультура", "физическая культура": "физкультура",
         "технология": "труд", "иформатика": "информатика", "обж": "обзр"}
GROUP = {"математика": {"математика", "алгебра", "геометрия"}}
NOT_ROOM = re.compile(r"акт|библ|бибил|зал")

S = lambda v: "" if v is None else str(v).strip()

def num(v):
    try: return int(float(S(v)))
    except ValueError: return None

def canon(s):
    s = " ".join(re.sub(r"[.,]", " ", S(s).lower()).split()); return ALIAS.get(s, s)

def subjects(cell):
    out = set()
    for p in re.split(r"[,;/]", S(cell)):
        c = canon(p)
        if c: out |= GROUP.get(c, {c})
    return out

def class_list(cell): return [x.lower() for x in re.split(r"[\s,;]+", S(cell)) if x]

def difficulty(key, g):
    v = SCALE.get(key, [None] * 5)[g - 5] if 5 <= g <= 9 else None
    if v is not None: return v
    if key == "математика" and g >= 7: return 11               # в плане «математика» в 7–9 классах: среднее алгебры и геометрии
    known = [x for x in SCALE.get(key, []) if x is not None]
    return round(sum(known) / len(known)) if known else 4

def grade(cls):
    m = re.match(r"\d+", cls); return int(m.group()) if m else None

# ---------- чтение Excel в формате примера ----------
def parse_excel(rows):
    hi = next((i for i, r in enumerate(rows[:10]) if any("препод" in S(c).lower() for c in r)), None)
    if hi is None: raise ValueError("Не найдена шапка: в первой строке должен быть столбец «преподаватель»")
    h, data = rows[hi], rows[hi + 1:]
    find = lambda f, st=0: next((i for i in range(st, len(h)) if f(S(h[i]).lower())), None)
    get = lambda r, i: r[i] if i is not None and i < len(r) else None
    ct = find(lambda s: "препод" in s)
    cc = find(lambda s: s.startswith("класс"), ct + 1); cs = find(lambda s: "предмет" in s, ct + 1)
    cr = find(lambda s: s.startswith("каб")); cl = find(lambda s: s.startswith("класс"), (cc or ct) + 1)
    pc = [(i, num(h[i])) for i in range(len(h)) if num(h[i]) is not None and 4 <= num(h[i]) <= 11 and i > (cl or cc or ct) + 1]
    nm = lambda v: str(int(v)) if isinstance(v, float) and v.is_integer() else S(v)
    teachers = [(S(get(r, ct)), S(get(r, cs)), S(get(r, cc))) for r in data if S(get(r, ct))]
    rooms = [(nm(get(r, cr)), S(get(r, cr + 1))) for r in data if cr is not None and nm(get(r, cr))]
    limits = [(str(num(get(r, cl))), str(num(get(r, cl + 1)))) for r in data
              if cl is not None and num(get(r, cl)) is not None and num(get(r, cl + 1)) is not None]
    plan = []
    if pc:
        for r in data:
            sub = S(get(r, pc[0][0] - 1))
            if sub:
                hrs = {g: num(get(r, i)) for i, g in pc}
                plan.append([sub] + [str(hrs[g]) if hrs.get(g) is not None else "" for g in range(5, 12)])
    if not teachers: raise ValueError("В файле не найдено ни одного учителя")
    return dict(teachers=teachers, rooms=rooms, plan=plan, limits=limits)

# ---------- модель ----------
def build_data(teachers, rooms, plan, limits):
    T = [dict(name=S(n), subj=subjects(s), cls=set(class_list(c))) for n, s, c in teachers if S(n)]
    classes = sorted({c for t in T for c in t["cls"]}, key=lambda c: (grade(c) or 99, c))
    P = {}
    for row in plan:
        label = S(row[0]).strip(" ,")
        if label: P[canon(label)] = (label[:1].upper() + label[1:], {5 + i: (num(v) or 0) for i, v in enumerate(row[1:8])})
    lim = dict(WEEK); lim.update({num(g): num(w) for g, w in limits if num(g) and num(w)})
    spec, gen, cap = {}, [], {}
    for n, s in rooms:
        if not S(n): continue
        cap[S(n)] = SPORT_CAP if "спорт" in S(n).lower() else 1
        if S(s): spec.setdefault(canon(s), []).append(S(n))
        elif not NOT_ROOM.search(S(n).lower()): gen.append(S(n))
    return dict(teachers=T, classes=classes, plan=P, limits=lim, spec=spec, gen=gen, cap=cap)

def make_lessons(M, P, warn):
    L, load, noteacher = [], {}, {}
    pool = lambda key: [t["name"] for t in M["teachers"] if not t["cls"] and key in t["subj"]]
    grades = {g for _, h in M["plan"].values() for g, v in h.items() if v}
    for cls in M["classes"]:
        g = grade(cls)
        if g not in grades: warn(f"Для класса {cls.upper()} нет учебного плана (параллель {g}), класс пропущен"); continue
        total = 0
        for key, (label, hrs) in M["plan"].items():
            n = hrs.get(g, 0)
            if n <= 0: continue
            total += n
            c = [t["name"] for t in M["teachers"] if cls in t["cls"] and key in t["subj"]] or pool(key)
            if not c: noteacher.setdefault(label, []).append(cls.upper())
            if len(c) == 1: load[c[0]] = load.get(c[0], 0) + n
            L += [dict(cls=cls, g=g, key=key, label=label, cands=c, n=n) for _ in range(n)]
        if total > M["limits"].get(g, 99): warn(f"{cls.upper()}: по плану {total} ч в неделю, а максимум {M['limits'][g]}")
        if total > DAILY.get(g, 7) * 5: warn(f"{cls.upper()}: {total} ч не помещается в 5 дней")
    for label, cl in noteacher.items():
        warn(f"Нет учителя по предмету «{label}» у классов: {', '.join(cl)} (уроки поставлены без учителя)")
    slots = 5 * P
    for t, v in sorted(load.items(), key=lambda x: -x[1]):
        if v > slots: warn(f"Перегруз: {t} — {v} уроков по плану, а в неделе только {slots} окон")
    for x in L: x["prio"] = (load.get(x["cands"][0], 0) / slots * 10 if len(x["cands"]) == 1 else 0) \
                           + (4 if x["key"] in M["spec"] else 0) + x["n"] / 2
    for x in L: x["sc"] = difficulty(x["key"], x["g"])
    return L

# ---------- размещение ----------
class State:
    def __init__(s, M, P): s.M, s.P, s.cb, s.tb, s.rb, s.nd, s.ns, s.tl, s.home = M, P, {}, set(), {}, {}, {}, {}, {}

    def teacher(s, L, d, p):
        c = [t for t in L["cands"] if (t, d, p) not in s.tb]
        if L["cands"] and not c: return None
        return min(c, key=lambda t: s.tl.get(t, 0)) if c else ""

    def room(s, L, d, p):
        sp = s.M["spec"].get(L["key"])
        if sp: return next((r for r in sp if s.rb.get((d, p, r), 0) < s.M["cap"][r]), None)
        h = s.home.get(L["cls"])
        if h and not s.rb.get((d, p, h)): return h
        return next((r for r in s.M["gen"] if not s.rb.get((d, p, r))), "")

    def cost(s, L, d, p):
        cur = s.nd.get((L["cls"], d), 0); c = p + 3 * cur
        c += 6 * (p - cur - 1) if p > cur + 1 else (-2 if p <= cur else 0)
        if s.ns.get((L["cls"], d, L["key"])): c += 40
        if L["sc"] >= HARD_FROM and (p == 1 or p >= 5): c += 10
        return c

    def put(s, L, d, p, t, r):
        L.update(d=d, p=p, t=t, r=r); s.cb[(L["cls"], d, p)] = L
        if t: s.tb.add((t, d, p)); s.tl[t] = s.tl.get(t, 0) + 1
        if r: s.rb[(d, p, r)] = s.rb.get((d, p, r), 0) + 1
        if r and L["key"] not in s.M["spec"]: s.home.setdefault(L["cls"], r)
        k = (L["cls"], d); s.nd[k] = s.nd.get(k, 0) + 1
        k = (L["cls"], d, L["key"]); s.ns[k] = s.ns.get(k, 0) + 1

    def drop(s, L):
        d, p, t, r = L["d"], L["p"], L["t"], L["r"]; del s.cb[(L["cls"], d, p)]
        if t: s.tb.discard((t, d, p)); s.tl[t] -= 1
        if r: s.rb[(d, p, r)] -= 1
        s.nd[(L["cls"], d)] -= 1; s.ns[(L["cls"], d, L["key"])] -= 1

    def compact(s):
        moved = True
        while moved:
            moved = False
            for L in sorted(s.cb.values(), key=lambda x: x["p"]):
                old = (L["d"], L["p"], L["t"], L["r"])
                for p in range(1, old[1]):
                    if (L["cls"], old[0], p) in s.cb: continue
                    s.drop(L); t = s.teacher(L, old[0], p); r = s.room(L, old[0], p)
                    if t is not None and r is not None: s.put(L, old[0], p, t, r); moved = True; break
                    s.put(L, *old)

    def gaps(s):
        by = {}
        for (c, d, p) in s.cb: by.setdefault((c, d), []).append(p)
        return sum(max(v) - len(v) for v in by.values())

def attempt(M, lessons, P, rng):
    s, un = State(M, P), []
    for L in sorted(lessons, key=lambda x: -(x["prio"] + rng.random() * 3)):
        best, why = None, {"в расписании класса нет свободных мест": 0, "учитель занят": 0, "нет свободного специального кабинета": 0}
        ks = list(why)
        for d in range(5):
            if s.nd.get((L["cls"], d), 0) >= DAILY.get(L["g"], 7) or s.ns.get((L["cls"], d, L["key"]), 0) >= 2:
                why[ks[0]] += P; continue
            for p in range(1, P + 1):
                if (L["cls"], d, p) in s.cb: why[ks[0]] += 1; continue
                t = s.teacher(L, d, p)
                if t is None: why[ks[1]] += 1; continue
                r = s.room(L, d, p)
                if r is None: why[ks[2]] += 1; continue
                c = s.cost(L, d, p) + rng.random() * 2
                if best is None or c < best[0]: best = (c, d, p, t, r)
        if best: s.put(L, *best[1:])
        else: un.append((L, max(why, key=why.get)))
    s.compact(); return s, un

def ccost(s, c, g):
    """Штраф за нарушения СанПиН у одного класса (зависит только от его уроков)."""
    n, sc, pen = [0] * 5, [0] * 5, 0.0
    for d in range(5):
        ps, seen = [], {}
        for p in range(1, s.P + 1):
            L = s.cb.get((c, d, p))
            if not L: continue
            ps.append(p); n[d] += 1; sc[d] += L["sc"]; seen[L["key"]] = seen.get(L["key"], 0) + 1
            if L["sc"] > 6: pen += W_POS * (L["sc"] - 6) * (1 if p == 1 else max(0, p - 4))
        if ps: pen += W_GAP * (max(ps) - len(ps))
        pen += W_SAME * sum(k - 1 for k in seen.values() if k > 1) + W_NORM * max(0, n[d] - DAILY.get(g, 7))
    peak = max(sc[1], sc[2])
    return pen + W_WEEK * (max(0, sc[0] - peak) + max(0, sc[4] - peak)) + W_EVEN * max(0, max(n) - min(n) - 1)

def try_put(s, L, d, p):
    t = s.teacher(L, d, p)
    if t is None: return False
    r = s.room(L, d, p)
    if r is None: return False
    s.put(L, d, p, t, r); return True

def force_place(s, un):
    """Не вошедшие в нормы уроки ставим туда, где нарушение минимально (но не в занятое учителем/кабинетом время)."""
    left = []
    for L, why in un:
        best = None
        for d in range(5):
            for p in range(1, s.P + 1):
                if (L["cls"], d, p) in s.cb: continue
                if try_put(s, L, d, p):
                    c = ccost(s, L["cls"], L["g"]); s.drop(L)
                    if best is None or c < best[0]: best = (c, d, p)
        if best: try_put(s, L, best[1], best[2])
        else: left.append((L, why))
    return left

def anneal(s, rounds, seconds, rng, progress, unplaced):
    """Улучшение: переносим и меняем местами уроки, оставляя изменения, которые уменьшают число нарушений."""
    import math
    by = {}
    for L in s.cb.values(): by.setdefault(L["cls"], []).append(L)
    cls = list(by); cur = {c: ccost(s, c, by[c][0]["g"]) for c in cls}
    steps = rounds * 3000; t0 = time.time()
    for i in range(steps):
        el = time.time() - t0
        if i % 200 == 0 and el > seconds: break
        if i and i % 3000 == 0 and progress: progress(i // 3000, rounds, (unplaced, int(sum(cur.values()))))
        T = 6.0 * (0.05 ** max(i / steps, el / seconds))
        c = rng.choice(cls); L = rng.choice(by[c]); d2, p2 = rng.randrange(5), rng.randrange(1, s.P + 1)
        o1 = (L["d"], L["p"], L["t"], L["r"])
        if (d2, p2) == o1[:2]: continue
        L2 = s.cb.get((c, d2, p2)); s.drop(L)
        o2 = None
        if L2: o2 = (L2["d"], L2["p"], L2["t"], L2["r"]); s.drop(L2)
        ok1 = try_put(s, L, d2, p2); ok2 = ok1 and (L2 is None or try_put(s, L2, o1[0], o1[1]))
        if ok2:
            new = ccost(s, c, L["g"]); delta = new - cur[c]
            if delta <= 0 or rng.random() < math.exp(-delta / T): cur[c] = new; continue
        if ok1 and (L["cls"], L["d"], L["p"]) in s.cb and s.cb[(L["cls"], L["d"], L["p"])] is L: s.drop(L)
        if ok2 and L2 is not None and (L2["cls"], L2["d"], L2["p"]) in s.cb and s.cb[(L2["cls"], L2["d"], L2["p"])] is L2: s.drop(L2)
        s.put(L, *o1)
        if L2: s.put(L2, *o2)

def analyse(s, P):
    """Считает нарушения в готовом расписании. Возвращает {категория: (число, [примеры])}."""
    out = {k: [0, []] for k in ("norm", "hard", "peak", "gap", "same", "even")}
    def add(k, text):
        out[k][0] += 1
        if len(out[k][1]) < 8: out[k][1].append(text)
    for c in sorted({k[0] for k in s.cb}):
        g = next(L["g"] for L in s.cb.values() if L["cls"] == c); n, sc = [0] * 5, [0] * 5
        for d in range(5):
            ls = [(p, s.cb[(c, d, p)]) for p in range(1, P + 1) if (c, d, p) in s.cb]
            n[d] = len(ls); sc[d] = sum(L["sc"] for _, L in ls)
            if n[d] > DAILY.get(g, 7): add("norm", f"{c.upper()}, {DAYS[d]}: {n[d]} уроков при максимуме {DAILY.get(g, 7)}")
            if ls and ls[-1][0] - len(ls): add("gap", f"{c.upper()}, {DAYS[d]}: окно между уроками")
            keys = [L["key"] for _, L in ls]
            for k in sorted({k for k in keys if keys.count(k) > 1}): add("same", f"{c.upper()}, {DAYS[d]}: {k} два раза")
            for p, L in ls:
                if L["sc"] >= HARD_FROM and not 2 <= p <= 4: add("hard", f"{c.upper()}, {DAYS[d]}, {p} урок: {L['label']} ({L['sc']} б.)")
        if max(sc[0], sc[4]) > max(sc[1], sc[2]): add("peak", f"{c.upper()}: баллы трудности Пн {sc[0]}, Вт {sc[1]}, Ср {sc[2]}, Чт {sc[3]}, Пт {sc[4]}")
        if max(n) - min(n) > 1: add("even", f"{c.upper()}: уроков по дням {n}")
    return out

NAMES = {"norm": "[НОРМА, табл. 6.6] Уроков в день больше допустимого", "hard": f"[Рекомендация] Сложный предмет (от {HARD_FROM} баллов) не на 2–4 уроке",
         "peak": "[Рекомендация] Понедельник или пятница тяжелее вторника и среды", "gap": "[Практика] Окна между уроками",
         "same": "[Практика] Один предмет дважды в день", "even": "[Рекомендация] Неравномерно по дням (разница больше 1 урока)"}

def violation_lines(A):
    lines = []
    for k, title in NAMES.items():
        cnt, ex = A[k]
        lines.append(f"  {title}: {cnt}" + ("" if cnt else "  ✓"))
        lines += ["      " + e for e in ex] + (["      …"] if cnt > len(ex) else [])
    return lines

def check_rows(rows, P=7):
    """Проверка готового расписания (строки: день, урок, класс, предмет, кабинет, учитель) по правилам СанПиН."""
    from types import SimpleNamespace
    cb = {}
    for day, les, cls, subj, cab, tea in rows:
        day = next((d for d in DAYS if d.lower() == S(day).lower()), None)
        if day is None or not S(cls): continue
        g, key = grade(S(cls).lower()) or 0, canon(subj)
        cb[(S(cls).lower(), DAYS.index(day), int(les))] = dict(cls=S(cls).lower(), g=g, key=key, label=S(subj), sc=difficulty(key, g))
    return analyse(SimpleNamespace(cb=cb), max([P] + [k[2] for k in cb]))

def cell_conflicts(cells):
    """cells: {(класс, день, урок): {'teacher','cabinet',...}} -> множество клеток с двойной занятостью учителя или кабинета."""
    occ, bad = {}, set()
    for k, r in cells.items():
        for kind in ("teacher", "cabinet"):
            v = S(r.get(kind)).lower()
            if v: occ.setdefault((kind, v, k[1], k[2]), []).append(k)
    for (kind, v, d, p), ks in occ.items():
        if len(ks) > (SPORT_CAP if kind == "cabinet" and "спорт" in v else 1): bad.update(ks)
    return bad

def move_messages(cells, src, dst):
    """Что будет нарушено, если урок из src поставить в dst (а урок из dst, если он есть, в src)."""
    msgs, c = [], src[0]
    moves = [(cells[src], dst)] + ([(cells[dst], src)] if dst in cells else [])
    for r, (_, d, p) in moves:
        t, k = S(r.get("teacher")).lower(), S(r.get("cabinet")).lower()
        for (c2, d2, p2), o in cells.items():
            if c2 == c or (d2, p2) != (d, p): continue
            if t and S(o.get("teacher")).lower() == t: msgs.append(f"Учитель {r['teacher']} в это время ведёт урок у {c2.upper()} ({DAYS[d]}, {p} урок)")
            if k and S(o.get("cabinet")).lower() == k and not (SPORT_CAP > 1 and "спорт" in k):
                msgs.append(f"Кабинет {r['cabinet']} в это время занят классом {c2.upper()} ({DAYS[d]}, {p} урок)")
    return msgs

def generate(M, P, attempts=30, progress=None, limit=25):
    warns = []; lessons = make_lessons(M, P, warns.append)
    if not lessons: raise ValueError("Нет данных для составления: проверьте учителей (с классами) и учебный план")
    best = None
    for i in range(min(attempts, 10)):                       # 1) черновик: жадная расстановка
        s, un = attempt(M, [dict(x) for x in lessons], P, random.Random(i))
        if best is None or (len(un), s.gaps()) < (len(best[1]), best[0].gaps()): best = (s, un)
    s, un = best
    un = force_place(s, un)                                  # 2) разместить всё, даже ценой нарушения
    rng = random.Random(1)
    anneal(s, max(attempts, 1), limit, rng, progress, len(un))  # 3) минимизация нарушений
    A = analyse(s, P); placed = list(s.cb.values())
    rows = [(DAYS[x["d"]], x["p"], x["cls"], x["label"], x["r"], x["t"]) for x in placed]
    norm = sum(1 for x in placed if not x["r"])
    lines = [f"Размещено уроков: {len(placed)} из {len(lessons)}", f"Уроков без кабинета (не хватило свободных): {norm}", "",
             "НАРУШЕНИЯ, КОТОРЫЕ НЕ УДАЛОСЬ ИЗБЕЖАТЬ:"]
    lines += violation_lines(A)
    if un:
        agg = {}
        for L, why in un: agg.setdefault((L["cls"], L["label"], why), 0); agg[(L["cls"], L["label"], why)] += 1
        lines += ["", f"НЕ РАЗМЕЩЕНО ({len(un)}), невозможно без двойной занятости:"] + [f"  {c.upper()} — {l}: {n} ур. ({w})" for (c, l, w), n in sorted(agg.items())]
    if warns: lines += ["", "ПРЕДУПРЕЖДЕНИЯ ПО ДАННЫМ:"] + ["  " + w for w in warns]
    return dict(rows=rows, text="\n".join(lines), placed=len(placed), total=len(lessons), unplaced=len(un), viol={k: v[0] for k, v in A.items()})
