import sqlite3
DB = "school.db"

def connect(): return sqlite3.connect(DB)

def init_db():
    conn=connect(); cur=conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT)")
    cur.execute("""CREATE TABLE IF NOT EXISTS schedule(
        id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, lesson INTEGER,
        class_name TEXT, subject TEXT, cabinet TEXT, teacher TEXT DEFAULT ''
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS schedule_changes(
        id INTEGER PRIMARY KEY AUTOINCREMENT, class_name TEXT, day TEXT,
        lesson INTEGER, teacher TEXT, cabinet TEXT, valid_date TEXT
    )""")
    # compatibility with old schedule table
    cols=[r[1] for r in cur.execute("PRAGMA table_info(schedule)").fetchall()]
    if 'teacher' not in cols: cur.execute("ALTER TABLE schedule ADD COLUMN teacher TEXT DEFAULT ''")
    conn.commit(); conn.close()

def add_user(user_id, username):
    conn=connect(); conn.execute("INSERT OR IGNORE INTO users VALUES (?,?)",(user_id,username)); conn.commit(); conn.close()

def clear_schedule():
    conn=connect(); conn.execute("DELETE FROM schedule"); conn.commit(); conn.close()

def add_schedule(day,lesson,class_name,subject,cabinet,teacher=''):
    conn=connect(); conn.execute("INSERT INTO schedule(day,lesson,class_name,subject,cabinet,teacher) VALUES(?,?,?,?,?,?)",(day,int(lesson),class_name.lower(),subject,cabinet,teacher)); conn.commit(); conn.close()

def get_schedule(class_name,day):
    conn=connect(); rows=conn.execute("SELECT lesson,subject,cabinet,teacher FROM schedule WHERE LOWER(class_name)=LOWER(?) AND LOWER(day)=LOWER(?) ORDER BY lesson",(class_name,day)).fetchall(); conn.close(); return rows

def get_classes():
    conn=connect(); rows=conn.execute("SELECT DISTINCT class_name FROM schedule ORDER BY class_name").fetchall(); conn.close(); return [x[0] for x in rows]

def get_free_teachers(day,lesson,exclude_class=None):
    conn=connect()
    all_t=[x[0] for x in conn.execute("SELECT DISTINCT teacher FROM schedule WHERE teacher IS NOT NULL AND TRIM(teacher)!='' ORDER BY teacher").fetchall()]
    q="SELECT DISTINCT teacher FROM schedule WHERE LOWER(day)=LOWER(?) AND lesson=? AND teacher IS NOT NULL AND TRIM(teacher)!=''"
    args=[day,int(lesson)]
    if exclude_class: q += " AND LOWER(class_name)!=LOWER(?)"; args.append(exclude_class)
    busy={str(x[0]).strip().lower() for x in conn.execute(q,args).fetchall()}; conn.close()
    return [t for t in all_t if str(t).strip().lower() not in busy]

def get_free_cabinets(day,lesson,exclude_class=None):
    conn=connect()
    all_c=[x[0] for x in conn.execute("SELECT DISTINCT cabinet FROM schedule WHERE cabinet IS NOT NULL AND TRIM(cabinet)!='' ORDER BY cabinet").fetchall()]
    q="SELECT DISTINCT cabinet FROM schedule WHERE LOWER(day)=LOWER(?) AND lesson=? AND cabinet IS NOT NULL AND TRIM(cabinet)!=''"; args=[day,int(lesson)]
    if exclude_class: q += " AND LOWER(class_name)!=LOWER(?)"; args.append(exclude_class)
    busy={str(x[0]).strip().lower() for x in conn.execute(q,args).fetchall()}; conn.close()
    return [c for c in all_c if str(c).strip().lower() not in busy]

def set_schedule_change(class_name,day,lesson,teacher=None,cabinet=None,valid_date=None):
    conn=connect(); conn.execute("DELETE FROM schedule_changes WHERE LOWER(class_name)=LOWER(?) AND LOWER(day)=LOWER(?) AND lesson=? AND valid_date=?",(class_name,day,int(lesson),valid_date)); conn.execute("INSERT INTO schedule_changes(class_name,day,lesson,teacher,cabinet,valid_date) VALUES(?,?,?,?,?,?)",(class_name,day,int(lesson),teacher,cabinet,valid_date)); conn.commit(); conn.close()

def get_schedule_changes(class_name,day,valid_date):
    conn=connect(); rows=conn.execute("SELECT lesson,teacher,cabinet FROM schedule_changes WHERE LOWER(class_name)=LOWER(?) AND LOWER(day)=LOWER(?) AND valid_date=?",(class_name,day,valid_date)).fetchall(); conn.close(); return rows

def clear_old_changes(today_date):
    conn=connect(); conn.execute("DELETE FROM schedule_changes WHERE valid_date < ?",(today_date,)); conn.commit(); conn.close()