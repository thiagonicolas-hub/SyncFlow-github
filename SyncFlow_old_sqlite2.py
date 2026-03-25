from flask import Flask, render_template, redirect, request, session, url_for, flash, jsonify, render_template_string
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from datetime import date
import webbrowser
from threading import Timer
import csv
from io import StringIO
from flask import Response
from calendar import monthrange
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
import io
from flask import send_file
from werkzeug.serving import make_server
import psutil
import os
import sys
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import get_flashed_messages
# Compatibilidade: werkzeug 2.x tinha url_parse; werkzeug 3.x removeu.
# --- SQLITE_COMPAT_FUNCS ---
def _sf_parse_date(value):
    if value is None:
        return None
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value if isinstance(value, datetime.datetime) else datetime.datetime.combine(value, datetime.time.min)
    s = str(value).strip()
    if not s:
        return None
    # tenta formatos comuns
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.datetime.strptime(s[:19], fmt)
        except Exception:
            pass
    # tenta fromisoformat (Python 3.11+ lida bem com ISO)
    try:
        return datetime.datetime.fromisoformat(s)
    except Exception:
        return None

def _sf_day(value):
    d = _sf_parse_date(value)
    return int(d.day) if d else None

def _sf_month(value):
    d = _sf_parse_date(value)
    return int(d.month) if d else None

def _sf_year(value):
    d = _sf_parse_date(value)
    return int(d.year) if d else None

def _sf_curdate():
    return datetime.date.today().isoformat()

def _sf_now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _sf_datediff(d1, d2):
    a = _sf_parse_date(d1)
    b = _sf_parse_date(d2)
    if not a or not b:
        return None
    return int((a.date() - b.date()).days)
try:
    from werkzeug.urls import url_parse  # type: ignore
except Exception:
    from urllib.parse import urlparse as url_parse

# ==========================
# CONFIGURAÇÃO DO APP (Flask)
# ==========================
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "syncflow-dev-key-change-me")  # em produção, defina via env
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # Em HTTPS (produção), ligue:
    SESSION_COOKIE_SECURE=(os.getenv("APP_ENV","dev") in ("prod","production")),
)

# ==========================
# BANCO LOCAL (SQLite)
# ==========================
import sqlite3
from pathlib import Path

APP_NAME = "SyncFlow"

def _is_frozen():
    return getattr(sys, "frozen", False)

def get_db_path() -> Path:
    """
    Caminho do banco SQLite.

    - Em dev: ./data/syncflow.db
    - Empacotado (EXE): %APPDATA%/SyncFlow/syncflow.db
    """
    env = os.getenv("SQLITE_PATH")
    if env:
        p = Path(env)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    if _is_frozen():
        base = Path(os.getenv("APPDATA", str(Path.home())))
        data_dir = base / APP_NAME
    else:
        data_dir = Path(__file__).resolve().parent / "data"

    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "syncflow.db"

def _connect_sqlite():
    conn = sqlite3.connect(str(get_db_path()), check_same_thread=False)

    # registra funções compatíveis com MySQL (evita quebrar queries antigas)
    try:
        conn.create_function("DAY", 1, _sf_day)
        conn.create_function("MONTH", 1, _sf_month)
        conn.create_function("YEAR", 1, _sf_year)
        conn.create_function("CURDATE", 0, _sf_curdate)
        conn.create_function("NOW", 0, _sf_now)
        conn.create_function("DATEDIFF", 2, _sf_datediff)
    except Exception:
        pass



    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    """
    Cria as tabelas essenciais se não existirem.
    Banco começa vazio (você cadastra o admin via tela do sistema).
    """
    conn = _connect_sqlite()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS parceiros (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        cnpj TEXT,
        email TEXT,
        telefone TEXT,
        status TEXT DEFAULT 'Ativo'
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        senha_hash TEXT NOT NULL,
        tipo TEXT NOT NULL,
        status TEXT DEFAULT 'Ativo',
        parceiro_id INTEGER,
        FOREIGN KEY(parceiro_id) REFERENCES parceiros(id)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS eventos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        parceiro_id INTEGER NOT NULL,
        criado_em TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(parceiro_id) REFERENCES parceiros(id)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS agendas_evento (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        evento_id INTEGER NOT NULL,
        nome_agenda TEXT NOT NULL,
        data_inicio TEXT,
        data_termino TEXT,
        grupo TEXT,
        responsavel TEXT,
        descricao TEXT,
        parceiro_id INTEGER NOT NULL,
        FOREIGN KEY(evento_id) REFERENCES eventos(id),
        FOREIGN KEY(parceiro_id) REFERENCES parceiros(id)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS agendas_grupos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agenda_id INTEGER NOT NULL,
        nome TEXT NOT NULL,
        parceiro_id INTEGER NOT NULL,
        FOREIGN KEY(agenda_id) REFERENCES agendas_evento(id),
        FOREIGN KEY(parceiro_id) REFERENCES parceiros(id)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS participantes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        data_nascimento TEXT,
        idade INTEGER,
        credencial TEXT,
        pcg TEXT,
        grupo TEXT,
        cep TEXT,
        logradouro TEXT,
        numero TEXT,
        bairro TEXT,
        cidade TEXT,
        uf TEXT,
        observacoes TEXT,
        status TEXT DEFAULT 'Ativo',
        parceiro_id INTEGER NOT NULL,
        FOREIGN KEY(parceiro_id) REFERENCES parceiros(id)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS agendas_grupos_participantes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        grupo_id INTEGER NOT NULL,
        participante_id INTEGER NOT NULL,
        parceiro_id INTEGER NOT NULL,
        FOREIGN KEY(grupo_id) REFERENCES agendas_grupos(id),
        FOREIGN KEY(participante_id) REFERENCES participantes(id),
        FOREIGN KEY(parceiro_id) REFERENCES parceiros(id)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS frequencia_diaria (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        grupo_id INTEGER NOT NULL,
        participante_id INTEGER NOT NULL,
        data TEXT NOT NULL,
        presente INTEGER NOT NULL DEFAULT 0,
        parceiro_id INTEGER NOT NULL,
        FOREIGN KEY(grupo_id) REFERENCES agendas_grupos(id),
        FOREIGN KEY(participante_id) REFERENCES participantes(id),
        FOREIGN KEY(parceiro_id) REFERENCES parceiros(id)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS frequencia_mensal (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        grupo_id INTEGER NOT NULL,
        participante_id INTEGER NOT NULL,
        mes TEXT NOT NULL,
        presente INTEGER NOT NULL DEFAULT 0,
        parceiro_id INTEGER NOT NULL,
        FOREIGN KEY(grupo_id) REFERENCES agendas_grupos(id),
        FOREIGN KEY(participante_id) REFERENCES participantes(id),
        FOREIGN KEY(parceiro_id) REFERENCES parceiros(id)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS notificacoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parceiro_id INTEGER NOT NULL,
        tipo TEXT,
        mensagem TEXT,
        link TEXT,
        lida INTEGER NOT NULL DEFAULT 0,
        criada_em TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(parceiro_id) REFERENCES parceiros(id)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS auditoria (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parceiro_id INTEGER,
        usuario_id INTEGER,
        usuario_nome TEXT,
        acao TEXT,
        detalhes TEXT,
        ip TEXT,
        user_agent TEXT,
        criado_em TEXT DEFAULT (datetime('now'))
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS reset_senha (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        token TEXT NOT NULL,
        expira_em TEXT NOT NULL
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS logs_suporte (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parceiro_id INTEGER,
        usuario_id INTEGER,
        mensagem TEXT,
        criado_em TEXT DEFAULT (datetime('now'))
    );
    """)

    conn.commit()
    conn.close()

class _SQLiteDictCursor:
    def __init__(self, cur):
        self._cur = cur
        self._cols = None

    def execute(self, sql, params=()):
        self._cur.execute(sql, params)
        self._cols = [d[0] for d in (self._cur.description or [])]
        return self

    def executemany(self, sql, seq_params):
        self._cur.executemany(sql, seq_params)
        self._cols = [d[0] for d in (self._cur.description or [])]
        return self

    def fetchone(self):
        row = self._cur.fetchone()
        if row is None:
            return None
        if self._cols:
            return {self._cols[i]: row[i] for i in range(len(self._cols))}
        return row

    def fetchall(self):
        rows = self._cur.fetchall()
        if not self._cols:
            return rows
        return [{self._cols[i]: r[i] for i in range(len(self._cols))} for r in rows]

    def __iter__(self):
        for r in self.fetchall():
            yield r

    def __getattr__(self, name):
        return getattr(self._cur, name)

class DB:
    """
    Wrapper de conexão SQLite para manter compatibilidade com o sistema
    (que antes usava mysql.connector cursor(dictionary=True)).
    """

    def __init__(self):
        self.conn = _connect_sqlite()
        self.cur = _SQLiteDictCursor(self.conn.cursor())

    def _translate_sql(self, sql: str) -> str:
        # NOW() - INTERVAL n DAY -> datetime('now','-n day')
        sql = re.sub(
            r"NOW\(\)\s*-\s*INTERVAL\s*(\d+)\s*DAY",
            r"datetime('now','-\1 day')",
            sql,
            flags=re.IGNORECASE
        )

        # CURDATE() - INTERVAL n DAY -> date('now','-n day')
        sql = re.sub(
            r"CURDATE\(\)\s*-\s*INTERVAL\s*(\d+)\s*DAY",
            r"date('now','-\1 day')",
            sql,
            flags=re.IGNORECASE
        )

        # NOW() -> datetime('now')
        sql = re.sub(r"\bNOW\(\)", "datetime('now')", sql, flags=re.IGNORECASE)
        # CURDATE() -> date('now')
        sql = re.sub(r"\bCURDATE\(\)", "date('now')", sql, flags=re.IGNORECASE)

        # datetime('now') - INTERVAL n DAY (fallback) -> datetime('now','-n day')
        sql = re.sub(
            r"datetime\('now'\)\s*-\s*INTERVAL\s*(\d+)\s*DAY",
            r"datetime('now','-\1 day')",
            sql,
            flags=re.IGNORECASE
        )

        # DATE_FORMAT(campo, '%%Y-%%m') -> strftime('%Y-%m', campo)
        sql = re.sub(
            r"DATE_FORMAT\(\s*([^,]+?)\s*,\s*'([^']+)'\s*\)",
            lambda m: f"strftime('{m.group(2).replace('%%','%')}', {m.group(1).strip()})",
            sql,
            flags=re.IGNORECASE
        )

        # placeholders %s -> ?
        if "%s" in sql:
            sql = sql.replace("%s", "?")

        return sql

    def execute(self, sql, params=()):
        sql = self._translate_sql(sql)
        self.cur.execute(sql, params)
        return self.cur

    def executemany(self, sql, seq_params):
        sql = self._translate_sql(sql)
        self.cur.executemany(sql, seq_params)
        return self.cur

    def commit(self):
        self.conn.commit()

    def close(self):
        try:
            if self.cur:
                self.cur.close()
        finally:
            if self.conn:
                self.conn.close()

def get_db():
    return DB()



def contar_admins():
    conn = get_db()
    try:
        qtd = conn.execute("""
            SELECT COUNT(*) AS total
            FROM usuarios
            WHERE tipo = 'Administrador'
              AND status = 'Ativo'
        """).fetchone()["total"]
        return qtd
    finally:
        conn.close()
    
@app.context_processor
def inject_eventos_menu():
    # não acessa DB sem sessão válida
    if not session.get("usuario_id"):
        return {"menu_eventos": []}

    usuario_tipo = session.get("usuario_tipo")
    parceiro_id  = session.get("parceiro_id")

    if not usuario_tipo:
        return {"menu_eventos": []}

    conn = get_db()
    try:
        if usuario_tipo == "Administrador":
            eventos = conn.execute("""
                SELECT id, nome
                FROM eventos
                ORDER BY nome ASC
            """).fetchall()
        else:
            eventos = conn.execute("""
                SELECT id, nome
                FROM eventos
                WHERE parceiro_id = ?
                ORDER BY nome ASC
            """, (parceiro_id,)).fetchall()

        return {"menu_eventos": eventos}
    finally:
        conn.close()

# (a segunda definição original de inject_eventos_menu foi removida
#  porque sobrescrevia a primeira; mantemos apenas esta.)

# -----------------------------
# -----------------------------
# Primeiro acesso (criar admin)
# -----------------------------
@app.route("/setup", methods=["GET", "POST"])
def setup():
    # se já existe admin, não precisa mais
    try:
        if contar_admins() > 0:
            return redirect(url_for("login"))
    except Exception:
        # se algo deu errado, ainda mostra a tela
        pass

    if request.method == "POST":
        parceiro_nome = (request.form.get("parceiro_nome") or "").strip()
        parceiro_cnpj = (request.form.get("parceiro_cnpj") or "").strip() or None
        parceiro_email = (request.form.get("parceiro_email") or "").strip() or None
        parceiro_tel = (request.form.get("parceiro_telefone") or "").strip() or None

        admin_nome = (request.form.get("admin_nome") or "").strip()
        admin_email = (request.form.get("admin_email") or "").strip().lower()
        admin_senha = (request.form.get("admin_senha") or "").strip()

        if not parceiro_nome or not admin_nome or not admin_email or not admin_senha:
            flash("Preencha todos os campos obrigatórios.", "login")
        else:
            conn = get_db()
            try:
                # cria parceiro
                cur = conn.execute("""
                    INSERT INTO parceiros (nome, cnpj, email, telefone, status)
                    VALUES (%s, %s, %s, %s, %s)
                """, (parceiro_nome, parceiro_cnpj, parceiro_email, parceiro_tel, "Ativo"))

                parceiro_id = cur.lastrowid

                # cria admin
                senha_hash = generate_password_hash(admin_senha)
                conn.execute("""
                    INSERT INTO usuarios (nome, email, senha_hash, tipo, status, parceiro_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (admin_nome, admin_email, senha_hash, "Administrador", "Ativo", parceiro_id))

                conn.commit()
                flash("Administrador criado com sucesso! Faça login.", "login")
                return redirect(url_for("login"))
            except Exception as e:
                conn.commit()
                flash(f"Erro ao criar administrador: {e}", "login")
            finally:
                conn.close()

    # HTML simples (não depende de template)
    return render_template_string("""
    <!doctype html>
    <html lang="pt-br">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Primeiro Acesso | SyncFlow</title>
      <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body class="bg-light">
      <div class="container py-5" style="max-width: 720px;">
        <div class="card shadow-sm">
          <div class="card-body p-4">
            <h4 class="mb-3">Primeiro acesso</h4>
            <p class="text-muted mb-4">Crie o parceiro e o primeiro administrador do sistema.</p>

            {% with messages = get_flashed_messages(category_filter=['login']) %}
              {% if messages %}
                <div class="alert alert-warning">{{ messages[0] }}</div>
              {% endif %}
            {% endwith %}

            <form method="post">
              <h6 class="mt-2">Parceiro</h6>
              <div class="row g-2">
                <div class="col-md-6">
                  <label class="form-label">Nome *</label>
                  <input class="form-control" name="parceiro_nome" required>
                </div>
                <div class="col-md-6">
                  <label class="form-label">CNPJ</label>
                  <input class="form-control" name="parceiro_cnpj">
                </div>
                <div class="col-md-6">
                  <label class="form-label">E-mail</label>
                  <input class="form-control" name="parceiro_email" type="email">
                </div>
                <div class="col-md-6">
                  <label class="form-label">Telefone</label>
                  <input class="form-control" name="parceiro_telefone">
                </div>
              </div>

              <hr class="my-4">

              <h6>Administrador</h6>
              <div class="row g-2">
                <div class="col-md-6">
                  <label class="form-label">Nome *</label>
                  <input class="form-control" name="admin_nome" required>
                </div>
                <div class="col-md-6">
                  <label class="form-label">E-mail *</label>
                  <input class="form-control" name="admin_email" type="email" required>
                </div>
                <div class="col-md-6">
                  <label class="form-label">Senha *</label>
                  <input class="form-control" name="admin_senha" type="password" required>
                </div>
              </div>

              <div class="d-grid mt-4">
                <button class="btn btn-primary btn-lg">Criar administrador</button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </body>
    </html>
    """)

# Login
# -----------------------------
@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    get_flashed_messages()  # consome qualquer sobra

    # Se é o primeiro acesso e não existe admin, vai para setup
    if contar_admins() == 0:
        return redirect(url_for("setup"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "").strip()

        conn = get_db()
        try:
            # manutenção de notificações
            gerar_notificacoes_aniversario(conn)
            limpar_notificacoes_antigas(conn)

            user = conn.execute(
                "SELECT * FROM usuarios WHERE LOWER(email) = %s",
                (email,)
            ).fetchone()

            if not user:
                flash("E-mail ou senha incorretos.", "login")
                return render_template("login.html")

            if user["status"] == "Inativo":
                flash("Este usuário está inativo.", "login")
                return render_template("login.html")

            if not check_password_hash(user["senha_hash"], senha):
                flash("E-mail ou senha incorretos.", "login")
                return render_template("login.html")

            # --- 🔥 SESSÕES DO USUÁRIO ---
            session["usuario_id"]   = user["id"]
            session["usuario_nome"] = user["nome"]
            session["usuario_tipo"] = user["tipo"]
            session["parceiro_id"]  = user["parceiro_id"]

            # --- 🔥 BUSCAR NOME DO PARCEIRO ---
            if user["parceiro_id"]:
                parceiro = conn.execute(
                    "SELECT nome FROM parceiros WHERE id = %s",
                    (user["parceiro_id"],)
                ).fetchone()

                session["parceiro_nome"] = parceiro["nome"] if parceiro else "Parceiro"
            else:
                session["parceiro_nome"] = "Administrador"

            if user["tipo"] == "Administrador":
                return redirect(url_for("admin_home"))
            else:
                return redirect(url_for("home"))

        finally:
            # 🔒 GARANTE que a conexão sempre será devolvida ao pool
            conn.close()

    return render_template("login.html")


@app.route("/logout", methods=["GET"])
def logout():
    session.clear()
    flash("Sessão encerrada com sucesso.", "info")
    return redirect(url_for("login"))

@app.route("/recuperar-senha", methods=["GET", "POST"])
def recuperar_senha():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()

        conn = get_db()
        try:
            usuario = conn.execute(
                "SELECT id, email FROM usuarios WHERE LOWER(email)=%s",
                (email,)
            ).fetchone()

            if not usuario:
                flash("Se este e-mail existir, enviaremos instruções.", "login_warning")
                return render_template("recuperar_senha.html")

            import uuid, datetime

            token = str(uuid.uuid4())
            expira = (
                datetime.datetime.now() + datetime.timedelta(hours=1)
            ).strftime("%Y-%m-%d %H:%M:%S")

            conn.execute("""
                INSERT INTO reset_senha (usuario_id, token, expira_em)
                VALUES (%s, %s, %s)
            """, (usuario["id"], token, expira))

            conn.commit()

        finally:
            # 🔒 garante devolução da conexão ao pool
            conn.close()

        link = url_for("resetar_senha", token=token, _external=True)

        mensagem = f"""
        <p>Olá!</p>
        <p>Você solicitou a recuperação da sua senha no SyncFlow.</p>
        <p>Clique no link abaixo para redefinir sua senha:</p>

        <p><a href="{link}" target="_blank">{link}</a></p>

        <p>O link expira em <strong>1 hora</strong>.</p>

        <p>Se você não solicitou isso, ignore este e-mail.</p>
        """

        enviar_email(usuario["email"], "Recuperação de Senha - SyncFlow", mensagem)

        flash("Enviamos um link de recuperação para seu e-mail!", "login_success")
        return render_template("recuperar_senha.html")

    return render_template("recuperar_senha.html")

@app.route("/resetar-senha/<token>", methods=["GET", "POST"])
def resetar_senha(token):
    conn = get_db()
    try:
        dados = conn.execute("""
            SELECT r.*, u.email 
            FROM reset_senha r
            JOIN usuarios u ON u.id = r.usuario_id
            WHERE r.token=%s
        """, (token,)).fetchone()

        if not dados:
            flash("Token inválido.", "login_error")
            return redirect(url_for("login"))

        # Verificar expiração
        import datetime
        expira_em = dados["expira_em"]

        if datetime.datetime.now() > expira_em:
            flash("Token expirado. Solicite uma nova recuperação.", "login_error")
            return redirect(url_for("login"))

        # POST → Atualizar senha
        if request.method == "POST":
            nova_senha = request.form.get("senha")
            if not nova_senha:
                flash("Digite a nova senha.", "login_warning")
                return render_template("resetar_senha.html", token=token)

            senha_hash = generate_password_hash(nova_senha)

            conn.execute(
                "UPDATE usuarios SET senha_hash=%s WHERE id=%s",
                (senha_hash, dados["usuario_id"])
            )

            conn.execute(
                "DELETE FROM reset_senha WHERE token=%s",
                (token,)
            )

            conn.commit()

            flash("Senha alterada com sucesso!", "success")
            return redirect(url_for("login"))

        return render_template("resetar_senha.html", token=token)

    finally:
        # 🔒 garantia absoluta de devolução da conexão ao pool
        conn.close()

def enviar_email(destino, assunto, mensagem_html):
    smtp_host  = os.getenv("SMTP_HOST", "smtp.hostinger.com")
    smtp_port  = int(os.getenv("SMTP_PORT", "587"))

    smtp_email = os.getenv("SMTP_USER")      # ex: noreply@synchronize.com.br
    smtp_senha = os.getenv("SMTP_PASS")      # senha do e-mail

    if not smtp_email or not smtp_senha:
        # em produção você pode logar isso em vez de print
        raise RuntimeError("SMTP_USER/SMTP_PASS não configurados no ambiente.")

    msg = MIMEMultipart()
    msg["From"] = f"SyncFlow by Synchronize <{smtp_email}>"
    msg["To"] = destino
    msg["Subject"] = assunto

    msg.attach(MIMEText(mensagem_html, "html"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_email, smtp_senha)
        server.sendmail(smtp_email, destino, msg.as_string())

# -----------------------------
# HOME
# -----------------------------
@app.route("/admin/home")
def admin_home():
    if "usuario_tipo" not in session or session["usuario_tipo"] != "Administrador":
        return redirect(url_for("login"))

    conn = get_db()
    try:
        total_parceiros = conn.execute(
            "SELECT COUNT(*) AS c FROM parceiros"
        ).fetchone()["c"]

        total_usuarios = conn.execute(
            "SELECT COUNT(*) AS c FROM usuarios WHERE status='Ativo'"
        ).fetchone()["c"]

        total_eventos = conn.execute(
            "SELECT COUNT(*) AS c FROM eventos"
        ).fetchone()["c"]

        total_participantes = conn.execute(
            "SELECT COUNT(*) AS c FROM participantes"
        ).fetchone()["c"]

        lista_parceiros = conn.execute("""
            SELECT p.*,
                   (SELECT COUNT(*) FROM usuarios u WHERE u.parceiro_id = p.id) AS total_usuarios,
                   '-' AS ultimo_acesso
            FROM parceiros p
            ORDER BY p.nome ASC
        """).fetchall()

        logs = conn.execute("""
            SELECT 
                a.id,
                COALESCE(u.nome, a.usuario_nome) AS usuario,
                p.nome AS parceiro,
                a.acao,
                a.criado_em AS data
            FROM auditoria a
            LEFT JOIN usuarios u ON u.id = a.usuario_id
            LEFT JOIN parceiros p ON p.id = a.parceiro_id
            ORDER BY a.id DESC
            LIMIT 20
        """).fetchall()

        return render_template(
            "admin_home.html",
            total_parceiros=total_parceiros,
            total_usuarios=total_usuarios,
            total_eventos=total_eventos,
            total_participantes=total_participantes,
            lista_parceiros=lista_parceiros,
            logs=logs
        )

    finally:
        # 🔒 garante devolução da conexão ao pool
        conn.close()

@app.route("/home")
def home():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    parceiro_id = session["parceiro_id"]
    conn = get_db()

    try:
        # KPIs principais por parceiro
        total_participantes = conn.execute(
            "SELECT COUNT(*) AS c FROM participantes WHERE parceiro_id = %s",
            (parceiro_id,)
        ).fetchone()["c"]

        total_participantes_ativos = conn.execute(
            "SELECT COUNT(*) AS c FROM participantes WHERE parceiro_id = %s AND status = 'Ativo'",
            (parceiro_id,)
        ).fetchone()["c"]

        total_participantes_inativos = conn.execute(
            "SELECT COUNT(*) AS c FROM participantes WHERE parceiro_id = %s AND status = 'Inativo'",
            (parceiro_id,)
        ).fetchone()["c"]

        total_eventos = conn.execute(
            "SELECT COUNT(*) AS c FROM eventos WHERE parceiro_id = %s",
            (parceiro_id,)
        ).fetchone()["c"]

        total_agendas = conn.execute(
            "SELECT COUNT(*) AS c FROM agendas_evento WHERE parceiro_id = %s",
            (parceiro_id,)
        ).fetchone()["c"]

        total_grupos = conn.execute(
            "SELECT COUNT(*) AS c FROM agendas_grupos WHERE parceiro_id = %s",
            (parceiro_id,)
        ).fetchone()["c"]

        # Últimas 3 agendas criadas pelo parceiro
        ultimas_agendas = conn.execute("""
            SELECT 
                a.id,
                a.nome_agenda,
                a.data_inicio,
                e.nome AS evento_nome
            FROM agendas_evento a
            LEFT JOIN eventos e ON e.id = a.evento_id
            WHERE a.parceiro_id = %s
            ORDER BY a.id DESC
            LIMIT 3
        """, (parceiro_id,)).fetchall()

        # Mensagem do dia
        mensagens = [
            "Sincronizando pessoas, eventos e resultados.",
            "Tudo conectado. Tudo sincronizado.",
            "A gestão que acompanha seu ritmo."
        ]
        idx = date.today().toordinal() % len(mensagens)
        mensagem_dia = mensagens[idx]

        # Sparkline dos últimos 6 meses (mock)
        import random
        spark_labels = ["Mes1", "Mes2", "Mes3", "Mes4", "Mes5", "Mes6"]
        spark_part = [random.randint(10, 50) for _ in range(6)]
        spark_grupo = [random.randint(1, 20) for _ in range(6)]
        spark_evento = [random.randint(1, 10) for _ in range(6)]
        spark_agenda = [random.randint(1, 15) for _ in range(6)]

        return render_template(
            "home.html",
            total_participantes=total_participantes,
            total_participantes_ativos=total_participantes_ativos,
            total_participantes_inativos=total_participantes_inativos,
            total_eventos=total_eventos,
            total_agendas=total_agendas,
            total_grupos=total_grupos,
            ultimas_agendas=ultimas_agendas,
            mensagem_dia=mensagem_dia,
            spark_labels=spark_labels,
            spark_part=spark_part,
            spark_grupo=spark_grupo,
            spark_evento=spark_evento,
            spark_agenda=spark_agenda
        )

    finally:
        # 🔒 garante devolução da conexão ao pool
        conn.close()
 
def has_permission(user_tipo, permission):
    regras = {
        "Administrador": {"all"},
        "Suporte": {"all"},
        "Master": {"view", "edit", "delete", "no_user_menu"},
        "Senior": {"view", "edit"},
        "Pleno": {"view"}
    }

    perms = regras.get(user_tipo, set())

    # acesso total
    if "all" in perms:
        return True

    return permission in perms

@app.route("/usuarios")
def usuarios():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    usuario_tipo        = session.get("usuario_tipo")
    parceiro_id_session = session.get("parceiro_id")

    # Filtros vindos da tela
    busca           = request.args.get("busca", "").strip()
    parceiro_filtro = request.args.get("parceiro", "").strip()
    status_filtro   = request.args.get("status", "").strip()
    tipo_filtro     = request.args.get("tipo", "").strip()

    # Ordenação / paginação
    pagina     = int(request.args.get("pagina", 1))
    por_pagina = 10
    sort       = request.args.get("sort", "nome")
    direction  = request.args.get("dir", "asc")

    conn = get_db()
    try:
        # ---------------------------
        # WHERE dinâmico
        # ---------------------------
        where = []
        params = []

        # Multiempresa: só Admin vê tudo
        if usuario_tipo != "Administrador":
            where.append("u.parceiro_id = %s")
            params.append(parceiro_id_session)
        else:
            if parceiro_filtro:
                where.append("u.parceiro_id = %s")
                params.append(parceiro_filtro)

        # Busca por nome ou e-mail
        if busca:
            where.append("(u.nome LIKE %s OR u.email LIKE %s)")
            like = f"%{busca}%"
            params.extend([like, like])

        # Filtro por Status
        if status_filtro:
            where.append("u.status = %s")
            params.append(status_filtro)

        # Filtro por Tipo
        if tipo_filtro:
            where.append("u.tipo = %s")
            params.append(tipo_filtro)

        where_sql = "WHERE " + " AND ".join(where) if where else ""

        # ---------------------------
        # Ordenação segura
        # ---------------------------
        colunas_validas = {
            "nome":   "u.nome",
            "email":  "u.email",
            "tipo":   "u.tipo",
            "status": "u.status",
        }
        coluna_ordenacao = colunas_validas.get(sort, "u.nome")
        ordem = "ASC" if direction == "asc" else "DESC"

        # Base (FROM + JOIN)
        sql_base = f"""
            FROM usuarios u
            LEFT JOIN parceiros p ON p.id = u.parceiro_id
            {where_sql}
        """

        # ---------------------------
        # TOTAL para paginação
        # ---------------------------
        total = conn.execute(
            f"SELECT COUNT(*) AS c {sql_base}",
            params
        ).fetchone()["c"]

        offset = (pagina - 1) * por_pagina

        # ---------------------------
        # Consulta final
        # ---------------------------
        usuarios = conn.execute(
            f"""
            SELECT
                u.id,
                u.nome,
                u.email,
                u.tipo,
                u.status,
                u.parceiro_id,
                p.nome AS parceiro_nome
            {sql_base}
            ORDER BY {coluna_ordenacao} {ordem}
            LIMIT %s OFFSET %s
            """,
            params + [por_pagina, offset]
        ).fetchall()

        # Combobox de parceiros só para Admin
        parceiros = []
        if usuario_tipo == "Administrador":
            parceiros = conn.execute(
                "SELECT id, nome FROM parceiros ORDER BY nome"
            ).fetchall()

    finally:
        # 🔒 GARANTE que a conexão sempre será devolvida ao pool
        conn.close()

    total_paginas = max(1, (total + por_pagina - 1) // por_pagina)

    return render_template(
        "usuarios.html",
        usuarios=usuarios,
        parceiros=parceiros,
        parceiro_filtro=parceiro_filtro,
        status_filtro=status_filtro,
        tipo_filtro=tipo_filtro,
        busca=busca,
        pagina=pagina,
        total_paginas=total_paginas,
        sort=sort,
        direction=direction
    )

@app.route("/usuarios/novo", methods=["POST"])
def usuarios_novo():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    usuario_tipo   = session.get("usuario_tipo")
    parceiro_sessao = session.get("parceiro_id")

    nome   = request.form["nome"].strip()
    email  = request.form["email"].strip()
    senha  = request.form["senha"].strip()
    tipo   = request.form.get("tipo", "Pleno")
    status = request.form.get("status", "Ativo")

    # -------------------------------
    # DEFINIR PARCEIRO DO NOVO USUÁRIO
    # -------------------------------
    parceiro_id = None

    if usuario_tipo == "Administrador":
        parceiro_id_form = request.form.get("parceiro_id", "").strip()

        if tipo == "Suporte":
            if not parceiro_id_form:
                flash("Selecione o parceiro que o usuário de suporte irá atender.", "usuario_error")
                return redirect(url_for("usuarios"))

            parceiro_id = parceiro_id_form
        else:
            parceiro_id = parceiro_id_form or parceiro_sessao
    else:
        parceiro_id = parceiro_sessao

    if parceiro_id:
        try:
            parceiro_id = int(parceiro_id)
        except ValueError:
            parceiro_id = None

    conn = get_db()
    try:
        # -------------------------------
        # VALIDAR DUPLICIDADE DE E-MAIL
        # -------------------------------
        existe = conn.execute(
            "SELECT id FROM usuarios WHERE email = %s",
            (email,)
        ).fetchone()

        if existe:
            flash("Já existe um usuário com este e-mail.", "usuario_error")
            return redirect(url_for("usuarios"))

        # -------------------------------
        # INSERIR USUÁRIO
        # -------------------------------
        senha_hash = generate_password_hash(senha)

        conn.execute("""
            INSERT INTO usuarios (nome, email, senha_hash, tipo, status, parceiro_id)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (nome, email, senha_hash, tipo, status, parceiro_id))

        conn.commit()

        flash("Usuário criado com sucesso!", "success")
        return redirect(url_for("usuarios"))

    finally:
        # 🔒 garante devolução da conexão ao pool
        conn.close()

@app.route("/usuarios/editar/<int:id>", methods=["POST"])
def usuarios_editar(id):
    if not has_permission(session["usuario_tipo"], "edit"):
        flash("Você não tem permissão para editar.", "usuario_error")
        return redirect(url_for("home"))

    usuario_tipo = session["usuario_tipo"]
    parceiro_id_session = session.get("parceiro_id")

    nome   = request.form["nome"].strip()
    email  = request.form["email"].strip().lower()
    tipo   = request.form.get("tipo", "Pleno")
    status = request.form.get("status", "Ativo")
    senha  = request.form.get("senha", "").strip()
    parceiro_id_form = request.form.get("parceiro_id", "").strip()

    conn = get_db()
    try:
        # ========================================================
        # 1️⃣ BUSCAR USUÁRIO
        # ========================================================
        if usuario_tipo == "Administrador":
            antigo = conn.execute(
                "SELECT * FROM usuarios WHERE id=%s",
                (id,)
            ).fetchone()
        else:
            antigo = conn.execute(
                "SELECT * FROM usuarios WHERE id=%s AND parceiro_id=%s",
                (id, parceiro_id_session)
            ).fetchone()

            if not antigo:
                flash("Você não pode editar usuários de outro parceiro.", "usuario_error")
                return redirect(url_for("usuarios"))

        if not antigo:
            flash("Usuário não encontrado.", "usuario_error")
            return redirect(url_for("usuarios"))

        # ========================================================
        # 2️⃣ PROTEÇÃO – ÚLTIMO ADMINISTRADOR GLOBAL
        # ========================================================
        def contar_admins():
            return conn.execute(
                "SELECT COUNT(*) AS c FROM usuarios WHERE tipo='Administrador'"
            ).fetchone()["c"]

        if antigo["tipo"] == "Administrador":
            if tipo != "Administrador" and contar_admins() <= 1:
                flash("Não é possível remover o último administrador!", "usuario_error")
                return redirect(url_for("usuarios"))

            if status == "Inativo" and contar_admins() <= 1:
                flash("Não é possível inativar o último administrador!", "usuario_error")
                return redirect(url_for("usuarios"))

        # ========================================================
        # 3️⃣ VERIFICAR E-MAIL DUPLICADO
        # ========================================================
        if usuario_tipo == "Administrador":
            existe = conn.execute("""
                SELECT id FROM usuarios 
                WHERE email=%s AND id<>%s
            """, (email, id)).fetchone()
        else:
            existe = conn.execute("""
                SELECT id FROM usuarios 
                WHERE email=%s AND parceiro_id=%s AND id<>%s
            """, (email, parceiro_id_session, id)).fetchone()

        if existe:
            flash("Já existe outro usuário usando este e-mail.", "usuario_error")
            return redirect(url_for("usuarios"))

        # ========================================================
        # 4️⃣ DEFINIR PARCEIRO DESTINO
        # ========================================================
        if usuario_tipo == "Administrador":
            parceiro_destino = antigo["parceiro_id"]

            if tipo == "Suporte":
                if not parceiro_id_form:
                    flash("Selecione o parceiro que o usuário de suporte irá atender.", "usuario_error")
                    return redirect(url_for("usuarios"))
                try:
                    parceiro_destino = int(parceiro_id_form)
                except ValueError:
                    flash("Parceiro inválido selecionado para usuário de suporte.", "usuario_error")
                    return redirect(url_for("usuarios"))
            else:
                if parceiro_id_form:
                    try:
                        parceiro_destino = int(parceiro_id_form)
                    except ValueError:
                        parceiro_destino = antigo["parceiro_id"]
        else:
            parceiro_destino = parceiro_id_session

        # ========================================================
        # 5️⃣ UPDATE FINAL
        # ========================================================
        if senha:
            senha_hash = generate_password_hash(senha)
            sql = """
                UPDATE usuarios
                SET nome=%s, email=%s, senha_hash=%s, tipo=%s, status=%s, parceiro_id=%s
                WHERE id=%s
            """
            params = (nome, email, senha_hash, tipo, status, parceiro_destino, id)
        else:
            sql = """
                UPDATE usuarios
                SET nome=%s, email=%s, tipo=%s, status=%s, parceiro_id=%s
                WHERE id=%s
            """
            params = (nome, email, tipo, status, parceiro_destino, id)

        conn.execute(sql, params)
        conn.commit()

        flash("Usuário atualizado com sucesso!", "success")
        return redirect(url_for("usuarios"))

    finally:
        # 🔒 GARANTE que a conexão sempre será devolvida ao pool
        conn.close()

@app.route("/usuarios/inativar/<int:id>")
def usuarios_inativar(id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    usuario_tipo = session["usuario_tipo"]
    parceiro_id_logado = session["parceiro_id"]

    # 🔐 Permissões
    if usuario_tipo not in ["Administrador", "Master"]:
        flash("Você não tem permissão para inativar usuários.", "usuario_error")
        return redirect(url_for("usuarios"))

    conn = get_db()
    try:
        # ================================
        # BUSCA USUÁRIO DE FORMA SEGURA
        # ================================
        if usuario_tipo == "Administrador":
            user = conn.execute(
                "SELECT * FROM usuarios WHERE id=%s",
                (id,)
            ).fetchone()
        else:
            user = conn.execute(
                "SELECT * FROM usuarios WHERE id=%s AND parceiro_id=%s",
                (id, parceiro_id_logado)
            ).fetchone()

        if not user:
            flash("Usuário não encontrado ou pertence a outro parceiro.", "usuario_error")
            return redirect(url_for("usuarios"))

        # ================================
        # PROTEÇÃO: ÚLTIMO ADMINISTRADOR
        # ================================
        def contar_admins():
            return conn.execute(
                "SELECT COUNT(*) AS c FROM usuarios WHERE tipo='Administrador'"
            ).fetchone()["c"]

        if user["tipo"] == "Administrador":
            if contar_admins() <= 1:
                flash("Não é possível inativar o último administrador!", "usuario_error")
                return redirect(url_for("usuarios"))

        # ================================
        # INATIVAÇÃO
        # ================================
        conn.execute(
            "UPDATE usuarios SET status='Inativo' WHERE id=%s",
            (id,)
        )
        conn.commit()

        flash("Usuário inativado com sucesso.", "info")
        return redirect(url_for("usuarios"))

    finally:
        # 🔒 GARANTE devolução da conexão ao pool
        conn.close()

@app.route("/usuarios/ativar/<int:id>")
def usuarios_ativar(id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    usuario_tipo = session["usuario_tipo"]
    parceiro_id_logado = session["parceiro_id"]

    # 🔐 Permissões
    if usuario_tipo not in ["Administrador", "Master"]:
        flash("Você não tem permissão para ativar usuários.", "usuario_error")
        return redirect(url_for("usuarios"))

    conn = get_db()
    try:
        # ================================
        # BUSCA USUÁRIO
        # ================================
        if usuario_tipo == "Administrador":
            user = conn.execute(
                "SELECT * FROM usuarios WHERE id=%s",
                (id,)
            ).fetchone()
        else:
            user = conn.execute(
                "SELECT * FROM usuarios WHERE id=%s AND parceiro_id=%s",
                (id, parceiro_id_logado)
            ).fetchone()

        if not user:
            flash("Usuário não encontrado ou pertence a outro parceiro.", "usuario_error")
            return redirect(url_for("usuarios"))

        # ================================
        # ATIVAR USUÁRIO
        # ================================
        conn.execute(
            "UPDATE usuarios SET status='Ativo' WHERE id=%s",
            (id,)
        )
        conn.commit()

        flash("Usuário ativado com sucesso.", "success")
        return redirect(url_for("usuarios"))

    finally:
        # 🔒 garante devolução da conexão ao pool
        conn.close()

@app.route("/usuarios/excluir/<int:id>")
def usuarios_excluir(id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    usuario_tipo   = session["usuario_tipo"]
    usuario_logado = session["usuario_id"]

    # 🔐 Permissão: SOMENTE ADMINISTRADOR GLOBAL
    if usuario_tipo != "Administrador":
        flash("Você não tem permissão para excluir usuários.", "usuario_error")
        return redirect(url_for("usuarios"))

    conn = get_db()
    try:
        # ================================
        # BUSCA USUÁRIO A SER EXCLUÍDO
        # ================================
        user = conn.execute(
            "SELECT * FROM usuarios WHERE id=%s",
            (id,)
        ).fetchone()

        if not user:
            flash("Usuário não encontrado.", "usuario_error")
            return redirect(url_for("usuarios"))

        # ================================
        # IMPEDIR AUTO-EXCLUSÃO
        # ================================
        if user["id"] == usuario_logado:
            flash("Você não pode excluir sua própria conta.", "usuario_error")
            return redirect(url_for("usuarios"))

        # ================================
        # IMPEDIR EXCLUSÃO DO ÚLTIMO ADMIN
        # ================================
        def contar_admins():
            return conn.execute(
                "SELECT COUNT(*) AS c FROM usuarios WHERE tipo='Administrador'"
            ).fetchone()["c"]

        if user["tipo"] == "Administrador" and contar_admins() <= 1:
            flash("Não é possível excluir o último administrador!", "usuario_error")
            return redirect(url_for("usuarios"))

        # ================================
        # EXCLUSÃO
        # ================================
        conn.execute(
            "DELETE FROM usuarios WHERE id=%s",
            (id,)
        )
        conn.commit()

        flash("Usuário excluído com sucesso.", "success")
        return redirect(url_for("usuarios"))

    finally:
        # 🔒 GARANTE devolução da conexão ao pool
        conn.close()

# -----------------------------
# Agendamento por Evento
# -----------------------------
@app.route("/eventos/<int:evento_id>/agendamento", methods=["GET", "POST"])
def eventos_agendamento(evento_id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    parceiro_id = session["parceiro_id"]
    usuario_tipo = session["usuario_tipo"]

    conn = get_db()
    try:
        # 🔒 Buscar evento garantindo que pertence ao parceiro correto
        evento = conn.execute(
            "SELECT * FROM eventos WHERE id = %s AND parceiro_id = %s",
            (evento_id, parceiro_id)
        ).fetchone()

        if not evento:
            flash("Evento não encontrado ou não pertence ao seu parceiro.", "evento_error")
            return redirect(url_for("home"))

        # ===============================
        # CADASTRO (POST)
        # ===============================
        if request.method == "POST":
            nome_agenda = request.form.get("nome_agenda", "").strip()
            data_inicio = request.form.get("data_inicio", "").strip()
            responsavel = request.form.get("responsavel", "").strip()
            descricao = request.form.get("descricao", "").strip()

            grupo = None

            conn.execute("""
                INSERT INTO agendas_evento 
                    (evento_id, nome_agenda, data_inicio, data_termino, grupo, responsavel, descricao, parceiro_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                evento_id,
                nome_agenda,
                data_inicio or None,
                None,
                grupo,
                responsavel or None,
                descricao or None,
                parceiro_id
            ))

            conn.commit()
            flash("Agendamento criado com sucesso!", "success")
            return redirect(url_for("eventos_agendamento", evento_id=evento_id))

        # ===============================
        # LISTAGEM / FILTROS (GET)
        # ===============================
        busca = request.args.get("busca", "").strip()
        pagina = int(request.args.get("pagina", 1))
        por_pagina = 10

        data_inicio_de = request.args.get("data_inicio_de", "").strip()
        data_inicio_ate = request.args.get("data_inicio_ate", "").strip()
        grupo_filtro = request.args.get("grupo", "").strip()

        sort = request.args.get("sort", "nome")
        direction = request.args.get("dir", "asc")

        colunas_validas = {
            "nome": "nome_agenda",
            "inicio": "data_inicio",
            "termino": "data_termino",
            "grupo": "grupo",
            "responsavel": "responsavel"
        }
        coluna_ordenacao = colunas_validas.get(sort, "nome_agenda")
        ordem = "ASC" if direction == "asc" else "DESC"

        where_clauses = ["evento_id = %s", "parceiro_id = %s"]
        params = [evento_id, parceiro_id]

        if busca:
            where_clauses.append("(nome_agenda LIKE %s OR grupo LIKE %s OR responsavel LIKE %s)")
            like = f"%{busca}%"
            params.extend([like, like, like])

        if data_inicio_de:
            where_clauses.append("DATE(data_inicio) >= DATE(%s)")
            params.append(data_inicio_de)

        if data_inicio_ate:
            where_clauses.append("DATE(data_inicio) <= DATE(%s)")
            params.append(data_inicio_ate)

        if grupo_filtro:
            where_clauses.append("grupo LIKE %s")
            params.append(f"%{grupo_filtro}%")

        where_sql = "WHERE " + " AND ".join(where_clauses)

        sql_base = f"""
            SELECT * FROM agendas_evento
            {where_sql}
            ORDER BY {coluna_ordenacao} {ordem}
        """

        todos = conn.execute(sql_base, params).fetchall()

        total = len(todos)
        inicio = (pagina - 1) * por_pagina
        fim = inicio + por_pagina
        dados = todos[inicio:fim]

        # ===============================
        # STATUS DA AGENDA
        # ===============================
        from datetime import date as _date

        agendas = []
        for a in dados:
            di = a["data_inicio"]
            dt = a["data_termino"]

            if isinstance(di, str) and di:
                data_inicio_real = datetime.strptime(di, "%Y-%m-%d").date()
            else:
                data_inicio_real = di

            if isinstance(dt, str) and dt:
                data_termino_real = datetime.strptime(dt, "%Y-%m-%d").date()
            else:
                data_termino_real = dt

            if data_termino_real:
                status = "Finalizado"
            else:
                if data_inicio_real and data_inicio_real > _date.today():
                    status = "Em aberto"
                elif data_inicio_real and data_inicio_real == _date.today():
                    status = "Em andamento"
                else:
                    status = "Atrasado"

            agendas.append({**dict(a), "status": status})

        total_paginas = max(1, (total + por_pagina - 1) // por_pagina)

        return render_template(
            "eventos_agendamento.html",
            evento=evento,
            agendas=agendas,
            busca=busca,
            pagina=pagina,
            total_paginas=total_paginas,
            data_inicio_de=data_inicio_de,
            data_inicio_ate=data_inicio_ate,
            grupo_filtro=grupo_filtro,
            sort=sort,
            direction=direction
        )

    finally:
        # 🔒 garantia absoluta de devolução da conexão ao pool
        conn.close()

@app.route("/eventos/<int:evento_id>/agendas/<int:agenda_id>/finalizar")
def finalizar_agenda(evento_id, agenda_id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    parceiro_id  = session["parceiro_id"]
    usuario_tipo = session.get("usuario_tipo", "usuario")

    conn = get_db()
    try:
        # 🔒 Validar se o evento pertence ao parceiro (exceto admin)
        if usuario_tipo != "Administrador":
            evento = conn.execute(
                "SELECT id FROM eventos WHERE id=%s AND parceiro_id=%s",
                (evento_id, parceiro_id)
            ).fetchone()

            if not evento:
                flash("Evento não encontrado ou não pertence ao seu parceiro.", "evento_error")
                return redirect(url_for("home"))

        # 🔒 Buscar agenda
        if usuario_tipo == "Administrador":
            agenda = conn.execute(
                "SELECT * FROM agendas_evento WHERE id=%s",
                (agenda_id,)
            ).fetchone()
        else:
            agenda = conn.execute(
                "SELECT * FROM agendas_evento WHERE id=%s AND parceiro_id=%s",
                (agenda_id, parceiro_id)
            ).fetchone()

        if not agenda:
            flash("Agenda não encontrada ou pertence a outro parceiro.", "danger")
            return redirect(url_for("eventos_agendamento", evento_id=evento_id))

        # 🔒 Bloquear alteração se já finalizada (exceto admin)
        if agenda["data_termino"] and usuario_tipo != "Administrador":
            flash("Você não tem permissão para alterar uma agenda finalizada.", "danger")
            return redirect(url_for("eventos_agendamento", evento_id=evento_id))

        # 🔥 Finalizar agenda (MySQL)
        conn.execute(
            "UPDATE agendas_evento SET data_termino = NOW() WHERE id=%s",
            (agenda_id,)
        )
        conn.commit()

        flash("Agenda finalizada com sucesso!", "success")
        return redirect(url_for("eventos_agendamento", evento_id=evento_id))

    finally:
        # 🔒 garantia absoluta de devolução da conexão ao pool
        conn.close()

# =======================================
# GRUPOS DA AGENDA
# =======================================
@app.route("/agenda/<int:agenda_id>/grupos", methods=["GET", "POST"])
def agenda_grupos(agenda_id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    parceiro_id  = session["parceiro_id"]
    usuario_tipo = session["usuario_tipo"]

    # 🔐 Permissões
    if usuario_tipo not in ["Suporte", "Master"]:
        flash("Você não tem permissão para acessar grupos desta agenda.", "danger")
        return redirect(url_for("home"))

    conn = get_db()
    try:
        # =========================================================
        # Buscar agenda
        # =========================================================
        if usuario_tipo == "Master":
            agenda = conn.execute("""
                SELECT a.*, e.nome AS evento_nome
                FROM agendas_evento a
                JOIN eventos e ON e.id = a.evento_id
                WHERE a.id = %s
            """, (agenda_id,)).fetchone()
        else:
            agenda = conn.execute("""
                SELECT a.*, e.nome AS evento_nome
                FROM agendas_evento a
                JOIN eventos e ON e.id = a.evento_id
                WHERE a.id = %s AND a.parceiro_id = %s
            """, (agenda_id, parceiro_id)).fetchone()

        if not agenda:
            flash("Agenda não encontrada ou pertence a outro parceiro.", "danger")
            return redirect(url_for("home"))

        # =========================================================
        # CADASTRO (POST)
        # =========================================================
        if request.method == "POST":
            nome = request.form.get("nome", "").strip()

            if not nome:
                flash("O nome do grupo é obrigatório.", "danger")
                return redirect(url_for("agenda_grupos", agenda_id=agenda_id))

            # parceiro do grupo
            parceiro_grupo = agenda["parceiro_id"] if usuario_tipo == "Master" else parceiro_id

            conn.execute("""
                INSERT INTO agendas_grupos (agenda_id, nome, parceiro_id)
                VALUES (%s, %s, %s)
            """, (agenda_id, nome, parceiro_grupo))

            conn.commit()
            flash("Grupo criado com sucesso!", "success")
            return redirect(url_for("agenda_grupos", agenda_id=agenda_id))

        # =========================================================
        # LISTAGEM
        # =========================================================
        busca = request.args.get("busca", "").strip()
        sort = request.args.get("sort", "nome")
        direction = request.args.get("dir", "asc")

        ordem = "ASC" if direction == "asc" else "DESC"

        where_clauses = ["agenda_id = %s"]
        params = [agenda_id]

        if usuario_tipo != "Master":
            where_clauses.append("parceiro_id = %s")
            params.append(parceiro_id)

        if busca:
            where_clauses.append("nome LIKE %s")
            params.append(f"%{busca}%")

        where_sql = "WHERE " + " AND ".join(where_clauses)

        grupos = conn.execute(f"""
            SELECT *
            FROM agendas_grupos
            {where_sql}
            ORDER BY nome {ordem}
        """, params).fetchall()

        return render_template(
            "agenda_grupo.html",
            agenda=agenda,
            grupos=grupos,
            busca=busca,
            sort=sort,
            direction=direction
        )

    finally:
        # 🔒 garante devolução da conexão ao pool
        conn.close()

# EDITAR
@app.route("/agenda/<int:agenda_id>/grupos/editar/<int:id>", methods=["POST"])
def agenda_grupos_editar(agenda_id, id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    usuario_tipo = session["usuario_tipo"]
    parceiro_id  = session["parceiro_id"]

    # 🔐 Permissões
    if usuario_tipo not in ["Suporte", "Master"]:
        flash("Você não tem permissão para editar grupos.", "danger")
        return redirect(url_for("home"))

    conn = get_db()
    try:
        # ===========================
        # VALIDAR AGENDA
        # ===========================
        if usuario_tipo == "Master":
            agenda = conn.execute(
                "SELECT id FROM agendas_evento WHERE id=%s",
                (agenda_id,)
            ).fetchone()
        else:
            agenda = conn.execute(
                "SELECT id FROM agendas_evento WHERE id=%s AND parceiro_id=%s",
                (agenda_id, parceiro_id)
            ).fetchone()

        if not agenda:
            flash("Agenda não encontrada ou pertence a outro parceiro.", "danger")
            return redirect(url_for("home"))

        # ===========================
        # VALIDAR GRUPO
        # ===========================
        if usuario_tipo == "Master":
            grupo = conn.execute(
                "SELECT id FROM agendas_grupos WHERE id=%s AND agenda_id=%s",
                (id, agenda_id)
            ).fetchone()
        else:
            grupo = conn.execute(
                "SELECT id FROM agendas_grupos WHERE id=%s AND agenda_id=%s AND parceiro_id=%s",
                (id, agenda_id, parceiro_id)
            ).fetchone()

        if not grupo:
            flash("Grupo não encontrado ou pertence a outro parceiro.", "danger")
            return redirect(url_for("agenda_grupos", agenda_id=agenda_id))

        # ===========================
        # VALIDAR NOME
        # ===========================
        nome = request.form.get("nome", "").strip()
        if not nome:
            flash("O nome do grupo é obrigatório.", "danger")
            return redirect(url_for("agenda_grupos", agenda_id=agenda_id))

        # ===========================
        # ATUALIZAR GRUPO
        # ===========================
        conn.execute("""
            UPDATE agendas_grupos
            SET nome=%s
            WHERE id=%s AND agenda_id=%s
        """, (nome, id, agenda_id))

        conn.commit()

        flash("Grupo atualizado com sucesso!", "success")
        return redirect(url_for("agenda_grupos", agenda_id=agenda_id))

    finally:
        # 🔒 garante devolução da conexão ao pool
        conn.close()

# EXCLUIR
@app.route("/agenda/<int:agenda_id>/grupos/excluir/<int:id>")
def agenda_grupos_excluir(agenda_id, id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    usuario_tipo = session["usuario_tipo"]
    parceiro_id  = session["parceiro_id"]

    # 🔐 Permissões
    if usuario_tipo not in ["Suporte", "Master"]:
        flash("Você não tem permissão para excluir grupos.", "danger")
        return redirect(url_for("home"))

    conn = get_db()
    try:
        # ==========================================
        # VALIDAR AGENDA
        # ==========================================
        if usuario_tipo == "Master":
            agenda = conn.execute(
                "SELECT id FROM agendas_evento WHERE id=%s",
                (agenda_id,)
            ).fetchone()
        else:
            agenda = conn.execute(
                "SELECT id FROM agendas_evento WHERE id=%s AND parceiro_id=%s",
                (agenda_id, parceiro_id)
            ).fetchone()

        if not agenda:
            flash("Agenda não encontrada ou pertence a outro parceiro.", "danger")
            return redirect(url_for("home"))

        # ==========================================
        # VALIDAR GRUPO
        # ==========================================
        if usuario_tipo == "Master":
            grupo = conn.execute(
                "SELECT id FROM agendas_grupos WHERE id=%s AND agenda_id=%s",
                (id, agenda_id)
            ).fetchone()
        else:
            grupo = conn.execute(
                "SELECT id FROM agendas_grupos WHERE id=%s AND agenda_id=%s AND parceiro_id=%s",
                (id, agenda_id, parceiro_id)
            ).fetchone()

        if not grupo:
            flash("Grupo não encontrado ou pertence a outro parceiro.", "danger")
            return redirect(url_for("agenda_grupos", agenda_id=agenda_id))

        # ==========================================
        # EXCLUSÃO EM TRANSAÇÃO
        # ==========================================
        conn.execute("DELETE FROM frequencia_diaria WHERE grupo_id=%s", (id,))
        conn.execute("DELETE FROM frequencia_mensal WHERE grupo_id=%s", (id,))
        conn.execute("DELETE FROM agendas_grupos_participantes WHERE grupo_id=%s", (id,))
        conn.execute("DELETE FROM agendas_grupos WHERE id=%s", (id,))

        conn.commit()

        flash("Grupo excluído com sucesso!", "warning")
        return redirect(url_for("agenda_grupos", agenda_id=agenda_id))

    except Exception as e:
        conn.rollback()
        flash("Erro ao excluir o grupo. Nenhuma alteração foi aplicada.", "danger")
        return redirect(url_for("agenda_grupos", agenda_id=agenda_id))

    finally:
        # 🔒 garante devolução da conexão ao pool
        conn.close()

@app.route("/agenda/<int:agenda_id>/grupo/<int:grupo_id>/frequencia-diaria")
def frequencia_diaria_grupo(agenda_id, grupo_id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    parceiro_id  = session["parceiro_id"]
    usuario_tipo = session["usuario_tipo"]

    conn = get_db()
    try:
        # 🔍 Validar agenda
        agenda = conn.execute(
            "SELECT * FROM agendas_evento WHERE id=%s AND parceiro_id=%s",
            (agenda_id, parceiro_id)
        ).fetchone()

        # Admin global pode acessar qualquer agenda
        if usuario_tipo == "Administrador" and not agenda:
            agenda = conn.execute(
                "SELECT * FROM agendas_evento WHERE id=%s",
                (agenda_id,)
            ).fetchone()

        if not agenda:
            flash("Agenda não encontrada ou pertence a outro parceiro.", "danger")
            return redirect(url_for("home"))

        # 🔍 Validar grupo
        if usuario_tipo == "Administrador":
            grupo = conn.execute(
                "SELECT * FROM agendas_grupos WHERE id=%s",
                (grupo_id,)
            ).fetchone()
        else:
            grupo = conn.execute(
                "SELECT * FROM agendas_grupos WHERE id=%s AND parceiro_id=%s",
                (grupo_id, parceiro_id)
            ).fetchone()

        if not grupo or grupo["agenda_id"] != agenda_id:
            flash("Grupo não encontrado ou pertence a outro parceiro.", "danger")
            return redirect(url_for("agenda_grupos", agenda_id=agenda_id))

        return redirect(url_for("frequencia_diaria", grupo_id=grupo_id))

    finally:
        # 🔒 garante devolução da conexão ao pool
        conn.close()

@app.route("/agenda/<int:agenda_id>/grupo/<int:grupo_id>/frequencia-mensal")
def frequencia_mensal_grupo(agenda_id, grupo_id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    parceiro_id  = session["parceiro_id"]
    usuario_tipo = session["usuario_tipo"]

    conn = get_db()
    try:
        # 🔍 Validar agenda
        agenda = conn.execute(
            "SELECT * FROM agendas_evento WHERE id=%s AND parceiro_id=%s",
            (agenda_id, parceiro_id)
        ).fetchone()

        # Admin global → pode acessar qualquer agenda
        if usuario_tipo == "Administrador" and not agenda:
            agenda = conn.execute(
                "SELECT * FROM agendas_evento WHERE id=%s",
                (agenda_id,)
            ).fetchone()

        if not agenda:
            flash("Agenda não encontrada ou pertence a outro parceiro.", "danger")
            return redirect(url_for("home"))

        # 🔍 Validar grupo
        if usuario_tipo == "Administrador":
            grupo = conn.execute(
                "SELECT * FROM agendas_grupos WHERE id=%s",
                (grupo_id,)
            ).fetchone()
        else:
            grupo = conn.execute(
                "SELECT * FROM agendas_grupos WHERE id=%s AND parceiro_id=%s",
                (grupo_id, parceiro_id)
            ).fetchone()

        if not grupo or grupo["agenda_id"] != agenda_id:
            flash("Grupo não encontrado ou pertence a outro parceiro.", "danger")
            return redirect(url_for("agenda_grupos", agenda_id=agenda_id))

        return redirect(
            url_for(
                "grupo_frequencia_mensal",
                agenda_id=agenda_id,
                grupo_id=grupo_id
            )
        )

    finally:
        # 🔒 garante devolução da conexão ao pool
        conn.close()

@app.route("/agenda/<int:agenda_id>/grupo/<int:grupo_id>/detalhes")
def grupo_detalhes(agenda_id, grupo_id):
    if "usuario_id" not in session:
        return jsonify({"erro": "Não autenticado"}), 401

    parceiro_id  = session["parceiro_id"]
    usuario_tipo = session["usuario_tipo"]

    conn = get_db()
    try:
        # ==========================================
        # VALIDAR AGENDA
        # ==========================================
        agenda = conn.execute(
            "SELECT * FROM agendas_evento WHERE id=%s AND parceiro_id=%s",
            (agenda_id, parceiro_id)
        ).fetchone()

        # Admin global pode ver qualquer agenda
        if usuario_tipo == "Administrador" and not agenda:
            agenda = conn.execute(
                "SELECT * FROM agendas_evento WHERE id=%s",
                (agenda_id,)
            ).fetchone()

        if not agenda:
            return jsonify({
                "erro": "Agenda não encontrada ou pertence a outro parceiro"
            }), 404

        # ==========================================
        # VALIDAR GRUPO
        # ==========================================
        if usuario_tipo == "Administrador":
            grupo = conn.execute(
                "SELECT * FROM agendas_grupos WHERE id=%s",
                (grupo_id,)
            ).fetchone()
        else:
            grupo = conn.execute(
                "SELECT * FROM agendas_grupos WHERE id=%s AND parceiro_id=%s",
                (grupo_id, parceiro_id)
            ).fetchone()

        if not grupo:
            return jsonify({
                "erro": "Grupo não encontrado ou pertence a outro parceiro"
            }), 404

        # 🔒 Verificar vínculo agenda → grupo
        if grupo["agenda_id"] != agenda_id:
            return jsonify({
                "erro": "Grupo não pertence à agenda informada"
            }), 403

        # ==========================================
        # TOTAL DE PARTICIPANTES
        # ==========================================
        total = conn.execute("""
            SELECT COUNT(*) AS total
            FROM agendas_grupos_participantes
            WHERE grupo_id = %s
        """, (grupo_id,)).fetchone()["total"]

        return jsonify({
            "nome": grupo["nome"],
            "total": total
        })

    finally:
        # 🔒 garante devolução da conexão ao pool
        conn.close()

@app.route("/eventos/<int:evento_id>/agendamento/editar/<int:id>", methods=["POST"])
def eventos_agendamento_editar(evento_id, id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    usuario_tipo = session["usuario_tipo"]
    parceiro_id  = session["parceiro_id"]

    # 🔐 Permissão
    if not has_permission(usuario_tipo, "edit"):
        flash("Você não tem permissão para editar agendamentos.", "danger")
        return redirect(url_for("home"))

    conn = get_db()
    try:
        # =========================================
        # VALIDAR EVENTO
        # =========================================
        evento = conn.execute(
            "SELECT * FROM eventos WHERE id=%s AND parceiro_id=%s",
            (evento_id, parceiro_id)
        ).fetchone()

        if usuario_tipo == "Administrador" and not evento:
            evento = conn.execute(
                "SELECT * FROM eventos WHERE id=%s",
                (evento_id,)
            ).fetchone()

        if not evento:
            flash("Evento não encontrado ou pertence a outro parceiro.", "danger")
            return redirect(url_for("home"))

        # =========================================
        # VALIDAR AGENDA
        # =========================================
        if usuario_tipo == "Administrador":
            agenda = conn.execute(
                "SELECT * FROM agendas_evento WHERE id=%s",
                (id,)
            ).fetchone()
        else:
            agenda = conn.execute(
                "SELECT * FROM agendas_evento WHERE id=%s AND parceiro_id=%s",
                (id, parceiro_id)
            ).fetchone()

        if not agenda:
            flash("Agendamento não encontrado ou pertence a outro parceiro.", "danger")
            return redirect(url_for("eventos_agendamento", evento_id=evento_id))

        if agenda["evento_id"] != evento_id:
            flash("Este agendamento não pertence ao evento informado.", "danger")
            return redirect(url_for("eventos_agendamento", evento_id=evento_id))

        # =========================================
        # FORMULÁRIO
        # =========================================
        nome_agenda  = request.form.get("nome_agenda", "").strip()
        data_inicio  = request.form.get("data_inicio", "").strip()
        data_termino = request.form.get("data_termino", "").strip()
        responsavel  = request.form.get("responsavel", "").strip()
        descricao    = request.form.get("descricao", "").strip()

        # =========================================
        # UPDATE
        # =========================================
        conn.execute("""
            UPDATE agendas_evento
            SET nome_agenda=%s,
                data_inicio=%s,
                data_termino=%s,
                responsavel=%s,
                descricao=%s
            WHERE id=%s AND evento_id=%s
        """, (
            nome_agenda,
            data_inicio or None,
            data_termino or None,
            responsavel or None,
            descricao or None,
            id,
            evento_id
        ))

        conn.commit()

        flash("Agendamento atualizado com sucesso!", "success")
        return redirect(url_for("eventos_agendamento", evento_id=evento_id))

    finally:
        # 🔒 garante devolução da conexão ao pool
        conn.close()

@app.route("/eventos/<int:evento_id>/agendamento/<int:agenda_id>/detalhes")
def agenda_detalhes(evento_id, agenda_id):
    if "usuario_id" not in session:
        return jsonify({"error": "Não autenticado"}), 401

    parceiro_id  = session["parceiro_id"]
    usuario_tipo = session["usuario_tipo"]

    conn = get_db()
    try:
        # ======================================================
        # 1) VALIDAR EVENTO
        # ======================================================
        evento = conn.execute(
            "SELECT id FROM eventos WHERE id=%s AND parceiro_id=%s",
            (evento_id, parceiro_id)
        ).fetchone()

        if usuario_tipo == "Administrador" and not evento:
            evento = conn.execute(
                "SELECT id FROM eventos WHERE id=%s",
                (evento_id,)
            ).fetchone()

        if not evento:
            return jsonify({
                "error": "Evento não encontrado ou pertence a outro parceiro"
            }), 404

        # ======================================================
        # 2) VALIDAR AGENDA
        # ======================================================
        if usuario_tipo == "Administrador":
            agenda = conn.execute("""
                SELECT 
                    a.id,
                    a.nome_agenda,
                    a.data_inicio,
                    a.data_termino,
                    a.responsavel,
                    a.descricao,
                    e.nome AS evento_nome,
                    a.evento_id
                FROM agendas_evento a
                JOIN eventos e ON e.id = a.evento_id
                WHERE a.id=%s
            """, (agenda_id,)).fetchone()
        else:
            agenda = conn.execute("""
                SELECT 
                    a.id,
                    a.nome_agenda,
                    a.data_inicio,
                    a.data_termino,
                    a.responsavel,
                    a.descricao,
                    e.nome AS evento_nome,
                    a.evento_id
                FROM agendas_evento a
                JOIN eventos e ON e.id = a.evento_id
                WHERE a.id=%s AND a.parceiro_id=%s
            """, (agenda_id, parceiro_id)).fetchone()

        if not agenda:
            return jsonify({
                "error": "Agenda não encontrada ou pertence a outro parceiro"
            }), 404

        if agenda["evento_id"] != evento_id:
            return jsonify({
                "error": "Esta agenda não pertence ao evento informado"
            }), 403

        # ======================================================
        # 3) BUSCAR GRUPOS
        # ======================================================
        if usuario_tipo == "Administrador":
            grupos = conn.execute("""
                SELECT 
                    g.id,
                    g.nome,
                    COUNT(DISTINCT agp.participante_id) AS total_participantes
                FROM agendas_grupos g
                LEFT JOIN agendas_grupos_participantes agp
                       ON agp.grupo_id = g.id
                WHERE g.agenda_id=%s
                GROUP BY g.id, g.nome
                ORDER BY g.nome
            """, (agenda_id,)).fetchall()
        else:
            grupos = conn.execute("""
                SELECT 
                    g.id,
                    g.nome,
                    COUNT(DISTINCT agp.participante_id) AS total_participantes
                FROM agendas_grupos g
                LEFT JOIN agendas_grupos_participantes agp
                       ON agp.grupo_id = g.id
                WHERE g.agenda_id=%s AND g.parceiro_id=%s
                GROUP BY g.id, g.nome
                ORDER BY g.nome
            """, (agenda_id, parceiro_id)).fetchall()

        # ======================================================
        # 4) FORMATAR JSON
        # ======================================================
        dados_agenda = {
            "nome_agenda": agenda["nome_agenda"],
            "evento_nome": agenda["evento_nome"],
            "responsavel": agenda["responsavel"],
            "descricao": agenda["descricao"],
            "data_inicio": str(agenda["data_inicio"]) if agenda["data_inicio"] else "",
            "data_termino": str(agenda["data_termino"]) if agenda["data_termino"] else ""
        }

        lista_grupos = [
            {
                "nome": g["nome"],
                "total_participantes": g["total_participantes"]
            }
            for g in grupos
        ]

        return jsonify({
            "agenda": dados_agenda,
            "grupos": lista_grupos
        })

    finally:
        # 🔒 garante devolução da conexão ao pool
        conn.close()

@app.route("/eventos/<int:evento_id>/agendamento/excluir/<int:id>")
def eventos_agendamento_excluir(evento_id, id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    usuario_tipo = session["usuario_tipo"]
    parceiro_id  = session["parceiro_id"]

    # 🔐 Permissão
    if not has_permission(usuario_tipo, "delete"):
        flash("Você não tem permissão para excluir agendas.", "evento_error")
        return redirect(url_for("home"))

    conn = get_db()
    try:
        # ============================================================
        # 1) Validar evento
        # ============================================================
        evento = conn.execute(
            "SELECT id FROM eventos WHERE id=%s AND parceiro_id=%s",
            (evento_id, parceiro_id)
        ).fetchone()

        if usuario_tipo == "Administrador" and not evento:
            evento = conn.execute(
                "SELECT id FROM eventos WHERE id=%s",
                (evento_id,)
            ).fetchone()

        if not evento:
            flash("Evento não encontrado ou pertence a outro parceiro.", "evento_error")
            return redirect(url_for("home"))

        # ============================================================
        # 2) Validar agenda
        # ============================================================
        if usuario_tipo == "Administrador":
            agenda = conn.execute(
                "SELECT * FROM agendas_evento WHERE id=%s",
                (id,)
            ).fetchone()
        else:
            agenda = conn.execute(
                "SELECT * FROM agendas_evento WHERE id=%s AND parceiro_id=%s",
                (id, parceiro_id)
            ).fetchone()

        if not agenda:
            flash("Agendamento não encontrado ou pertence a outro parceiro.", "evento_error")
            return redirect(url_for("eventos_agendamento", evento_id=evento_id))

        if agenda["evento_id"] != evento_id:
            flash("Agendamento não pertence ao evento informado.", "evento_error")
            return redirect(url_for("eventos_agendamento", evento_id=evento_id))

        # ============================================================
        # 3) Buscar grupos da agenda
        # ============================================================
        if usuario_tipo == "Administrador":
            grupos = conn.execute(
                "SELECT id FROM agendas_grupos WHERE agenda_id=%s",
                (id,)
            ).fetchall()
        else:
            grupos = conn.execute(
                "SELECT id FROM agendas_grupos WHERE agenda_id=%s AND parceiro_id=%s",
                (id, parceiro_id)
            ).fetchall()

        # ============================================================
        # 4) Excluir grupos em cascata
        # ============================================================
        for g in grupos:
            gid = g["id"]
            conn.execute("DELETE FROM frequencia_diaria WHERE grupo_id=%s", (gid,))
            conn.execute("DELETE FROM frequencia_mensal WHERE grupo_id=%s", (gid,))
            conn.execute("DELETE FROM agendas_grupos_participantes WHERE grupo_id=%s", (gid,))
            conn.execute("DELETE FROM agendas_grupos WHERE id=%s", (gid,))

        # ============================================================
        # 5) Excluir a agenda
        # ============================================================
        conn.execute("DELETE FROM agendas_evento WHERE id=%s", (id,))
        conn.commit()

        flash("Agenda excluída com sucesso!", "success")
        return redirect(url_for("eventos_agendamento", evento_id=evento_id))

    except Exception:
        conn.rollback()
        flash("Erro ao excluir a agenda. Nenhuma alteração foi aplicada.", "danger")
        return redirect(url_for("eventos_agendamento", evento_id=evento_id))

    finally:
        # 🔒 devolve conexão ao pool
        conn.close()

# -----------------------------
# PARTICIPANTES - LISTAGEM
# -----------------------------
@app.route("/participantes")
def participantes():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    usuario_tipo = session["usuario_tipo"]
    parceiro_id  = session.get("parceiro_id")

    # parâmetros GET
    busca  = request.args.get("busca", "").strip()
    pagina = int(request.args.get("pagina", 1))
    por_pagina = 10

    status_filtro = request.args.get("status", "").strip()
    grupo_filtro  = request.args.get("grupo", "").strip()
    pcg_filtro    = request.args.get("pcg", "").strip()

    sort      = request.args.get("sort", "nome")
    direction = request.args.get("dir", "asc")

    colunas_validas = {
        "nome": "nome",
        "idade": "idade",
        "credencial": "credencial",
        "pcg": "pcg",
        "grupo": "grupo",
        "status": "status"
    }
    coluna_ordenacao = colunas_validas.get(sort, "nome")
    ordem = "ASC" if direction == "asc" else "DESC"

    conn = get_db()
    try:
        # =====================================================
        # WHERE dinâmico
        # =====================================================
        where  = []
        params = []

        # multiempresa
        if usuario_tipo != "Administrador":
            where.append("parceiro_id = %s")
            params.append(parceiro_id)

        if busca:
            where.append("""
                (nome LIKE %s OR credencial LIKE %s OR pcg LIKE %s OR grupo LIKE %s)
            """)
            like = f"%{busca}%"
            params.extend([like, like, like, like])

        if status_filtro:
            where.append("status = %s")
            params.append(status_filtro)

        if grupo_filtro:
            where.append("grupo LIKE %s")
            params.append(f"%{grupo_filtro}%")

        if pcg_filtro:
            where.append("pcg LIKE %s")
            params.append(f"%{pcg_filtro}%")

        where_sql = "WHERE " + " AND ".join(where) if where else ""

        # =====================================================
        # TOTAL
        # =====================================================
        total = conn.execute(f"""
            SELECT COUNT(*) AS c
            FROM participantes
            {where_sql}
        """, params).fetchone()["c"]

        # =====================================================
        # DADOS PAGINADOS
        # =====================================================
        offset = (pagina - 1) * por_pagina

        dados = conn.execute(f"""
            SELECT *
            FROM participantes
            {where_sql}
            ORDER BY {coluna_ordenacao} {ordem}
            LIMIT %s OFFSET %s
        """, params + [por_pagina, offset]).fetchall()

        total_paginas = max(1, (total + por_pagina - 1) // por_pagina)

        return render_template(
            "participantes.html",
            dados=dados,
            busca=busca,
            pagina=pagina,
            total_paginas=total_paginas,
            status_filtro=status_filtro,
            grupo_filtro=grupo_filtro,
            pcg_filtro=pcg_filtro,
            sort=sort,
            total=total,
            direction=direction
        )

    except Exception:
        conn.rollback()
        flash("Erro ao carregar participantes.", "danger")
        return redirect(url_for("home"))

    finally:
        # 🔒 devolve a conexão ao pool
        conn.close()

@app.route("/participantes/painel")
def participantes_painel():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    usuario_tipo = session["usuario_tipo"]
    parceiro_id  = session.get("parceiro_id")

    conn = get_db()
    try:
        # 🔒 Filtro multiempresa
        where = ""
        params = []

        if usuario_tipo != "Administrador":
            where = "WHERE parceiro_id = %s"
            params.append(parceiro_id)

        # ===========================
        # KPIs
        # ===========================
        total = conn.execute(
            f"SELECT COUNT(*) AS total FROM participantes {where}",
            params
        ).fetchone()["total"]

        ativos = conn.execute(
            f"SELECT COUNT(*) AS total FROM participantes {where} "
            + ("AND status='Ativo'" if where else "WHERE status='Ativo'"),
            params
        ).fetchone()["total"]

        inativos = conn.execute(
            f"SELECT COUNT(*) AS total FROM participantes {where} "
            + ("AND status='Inativo'" if where else "WHERE status='Inativo'"),
            params
        ).fetchone()["total"]

        # ===========================
        # Agrupamentos
        # ===========================
        credenciais = conn.execute(f"""
            SELECT credencial, COUNT(*) AS total
            FROM participantes
            {where}
            GROUP BY credencial
        """, params).fetchall()

        pcg = conn.execute(f"""
            SELECT pcg, COUNT(*) AS total
            FROM participantes
            {where}
            GROUP BY pcg
        """, params).fetchall()

        grupos = conn.execute(f"""
            SELECT grupo, COUNT(*) AS total
            FROM participantes
            {where}
            GROUP BY grupo
            ORDER BY grupo
        """, params).fetchall()

        return render_template(
            "participantes_painel.html",
            total=total,
            ativos=ativos,
            inativos=inativos,
            credenciais=credenciais,
            pcg=pcg,
            grupos=grupos
        )

    except Exception:
        conn.rollback()
        flash("Erro ao carregar painel de participantes.", "danger")
        return redirect(url_for("home"))

    finally:
        # 🔒 devolve a conexão ao pool
        conn.close()

@app.route("/participantes/painel/pdf")
def participantes_painel_pdf():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    usuario_nome = session.get("usuario_nome", "Usuário")

    conn = get_db()

    # -----------------------------
    # DADOS DO PAINEL
    # -----------------------------
    total = conn.execute(
        "SELECT COUNT(*) AS total FROM participantes"
    ).fetchone()["total"]

    ativos = conn.execute(
        "SELECT COUNT(*) AS total FROM participantes WHERE status='Ativo'"
    ).fetchone()["total"]

    inativos = conn.execute(
        "SELECT COUNT(*) AS total FROM participantes WHERE status='Inativo'"
    ).fetchone()["total"]

    por_grupo = conn.execute("""
        SELECT grupo, COUNT(*) AS total
        FROM participantes
        GROUP BY grupo
        ORDER BY grupo
    """).fetchall()

    por_credencial = conn.execute("""
        SELECT credencial, COUNT(*) AS total
        FROM participantes
        GROUP BY credencial
        ORDER BY credencial
    """).fetchall()

    conn.close()

    # -----------------------------
    # INICIAR PDF (ReportLab)
    # -----------------------------
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    largura, altura = A4

    # Cabeçalho (igual ao relatório)
    pdf.setFillColorRGB(0.15, 0.15, 0.15)
    pdf.rect(0, altura - 60, largura, 60, fill=1)

    pdf.setFont("Helvetica-Bold", 18)
    pdf.setFillColor(colors.white)
    pdf.drawString(40, altura - 40, "Painel de Participantes")

    pdf.setFillColor(colors.black)
    pdf.line(40, altura - 70, largura - 40, altura - 70)

    y = altura - 100

    # -----------------------------
    # CARDS RESUMO
    # -----------------------------
    TABLE_STYLE = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e0e0e0")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ])

    tabela_resumo = [
        ["Indicador", "Quantidade"],
        ["Total de participantes", total],
        ["Ativos", ativos],
        ["Inativos", inativos],
    ]

    tbl = Table(tabela_resumo, colWidths=[260, 120])
    tbl.setStyle(TABLE_STYLE)
    tbl.wrapOn(pdf, 40, y)
    tbl.drawOn(pdf, 40, y - (len(tabela_resumo) * 16))

    y -= (len(tabela_resumo) * 16) + 30

    # -----------------------------
    # PARTICIPANTES POR GRUPO
    # -----------------------------
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(40, y, "Participantes por Grupo")
    y -= 15

    tabela_grupos = [["Grupo", "Quantidade"]]
    for g in por_grupo:
        tabela_grupos.append([g["grupo"] or "Não informado", g["total"]])

    tbl = Table(tabela_grupos, colWidths=[260, 120])
    tbl.setStyle(TABLE_STYLE)
    tbl.wrapOn(pdf, 40, y)
    tbl.drawOn(pdf, 40, y - (len(tabela_grupos) * 14))

    y -= (len(tabela_grupos) * 14) + 30

    # -----------------------------
    # PARTICIPANTES POR CREDENCIAL
    # -----------------------------
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(40, y, "Participantes por Credencial")
    y -= 15

    tabela_cred = [["Credencial", "Quantidade"]]
    for c in por_credencial:
        tabela_cred.append([c["credencial"] or "Não informado", c["total"]])

    tbl = Table(tabela_cred, colWidths=[260, 120])
    tbl.setStyle(TABLE_STYLE)
    tbl.wrapOn(pdf, 40, y)
    tbl.drawOn(pdf, 40, y - (len(tabela_cred) * 14))

    # Rodapé padrão do sistema
    desenhar_rodape(pdf, largura, usuario_nome)

    pdf.showPage()
    pdf.save()

    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="painel_participantes.pdf",
        mimetype="application/pdf"
    )

# -----------------------------
# Nova rota de exportação CSV
# -----------------------------
@app.route("/participantes/export")
def export_participantes():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    parceiro_id = session["parceiro_id"]
    usuario_tipo = session["usuario_tipo"]

    # mesmos filtros da listagem
    busca = request.args.get("busca", "").strip()
    status_filtro = request.args.get("status", "").strip()
    grupo_filtro = request.args.get("grupo", "").strip()
    pcg_filtro = request.args.get("pcg", "").strip()

    conn = get_db()

    # ================================
    # WHERE MULTI-EMPRESA (MYSQL)
    # ================================
    where_clauses = []
    params = []

    # 🔥 Se NÃO for admin → sempre filtra pelo parceiro
    if usuario_tipo != "Administrador":
        where_clauses.append("parceiro_id = %s")
        params.append(parceiro_id)

    # 🔍 Busca
    if busca:
        where_clauses.append("(nome LIKE %s OR credencial LIKE %s OR pcg LIKE %s OR grupo LIKE %s)")
        like = f"%{busca}%"
        params.extend([like, like, like, like])

    # 🟩 Status
    if status_filtro:
        where_clauses.append("status = %s")
        params.append(status_filtro)

    # 🟦 Grupo
    if grupo_filtro:
        where_clauses.append("grupo LIKE %s")
        params.append(f"%{grupo_filtro}%")

    # 🟪 PCG
    if pcg_filtro:
        where_clauses.append("pcg LIKE %s")
        params.append(f"%{pcg_filtro}%")

    # Montagem final do WHERE
    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    sql = f"""
        SELECT nome, idade, credencial, pcg, grupo, observacoes, status
        FROM participantes
        {where_sql}
        ORDER BY nome ASC
    """

    rows = conn.execute(sql, params).fetchall()

    # ======================
    # CSV EM MEMÓRIA
    # ======================
    si = StringIO()
    writer = csv.writer(si, delimiter=';')
    writer.writerow(["Nome", "Idade", "Credencial", "PCG", "Grupo", "Observações", "Status"])

    for r in rows:
        writer.writerow([
            r["nome"], r["idade"], r["credencial"],
            r["pcg"], r["grupo"], r["observacoes"], r["status"]
        ])

    output = si.getvalue().encode("utf-8-sig")
    conn.close()

    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=participantes.csv"}
    )

# -----------------------------
# NOVO PARTICIPANTE
# -----------------------------
@app.route("/participantes/novo", methods=["GET", "POST"])
def novo_participante():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    usuario_tipo = session["usuario_tipo"]
    parceiro_id  = session["parceiro_id"]

    if usuario_tipo not in ["Administrador", "Master"]:
        flash("Você não tem permissão para cadastrar participantes.", "danger")
        return redirect(url_for("participantes"))

    conn = get_db()
    try:
        if request.method == "POST":
            nome = request.form["nome"].strip()
            data_nascimento = request.form.get("data_nascimento") or None
            idade = request.form.get("idade") or None
            cred = request.form["credencial"].strip()
            pcg = request.form.get("pcg") or None
            grupo = request.form.get("grupo") or None
            obs = request.form.get("observacoes", "").strip()
            status = request.form.get("status", "Ativo")

            cep        = request.form.get("cep")
            logradouro = request.form.get("logradouro")
            numero     = request.form.get("numero")
            bairro     = request.form.get("bairro")
            cidade     = request.form.get("cidade")
            uf         = request.form.get("uf")

            if not nome or not cred:
                flash("Nome e Credencial são obrigatórios.", "danger")
                return redirect(url_for("novo_participante"))

            conn.execute("""
                INSERT INTO participantes (
                    nome, data_nascimento, idade, credencial, pcg, grupo,
                    cep, logradouro, numero, bairro, cidade, uf,
                    observacoes, status, parceiro_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                nome,
                data_nascimento,
                idade,
                cred,
                pcg,
                grupo,
                cep,
                logradouro,
                numero,
                bairro,
                cidade,
                uf,
                obs or None,
                status,
                parceiro_id
            ))

            conn.commit()
            flash("Participante cadastrado com sucesso!", "success")
            return redirect(url_for("participantes"))

        # GET
        return render_template("participantes_form.html", modo="novo")

    except Exception:
        conn.rollback()
        flash("Erro ao cadastrar participante.", "danger")
        return redirect(url_for("participantes"))

    finally:
        # 🔒 garante devolução da conexão ao pool
        conn.close()

# -----------------------------
# EDITAR PARTICIPANTE
# -----------------------------
@app.route("/participantes/editar/<int:id>", methods=["GET", "POST"])
def editar_participante(id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    usuario_tipo = session["usuario_tipo"]
    parceiro_id  = session["parceiro_id"]

    if not has_permission(usuario_tipo, "edit"):
        flash("Você não tem permissão para editar participantes.", "danger")
        return redirect(url_for("participantes"))

    conn = get_db()
    try:
        # ==========================
        # BUSCAR PARTICIPANTE
        # ==========================
        if usuario_tipo == "Administrador":
            registro = conn.execute(
                "SELECT * FROM participantes WHERE id=%s",
                (id,)
            ).fetchone()
        else:
            registro = conn.execute(
                "SELECT * FROM participantes WHERE id=%s AND parceiro_id=%s",
                (id, parceiro_id)
            ).fetchone()

        if not registro:
            flash("Participante não encontrado ou pertence a outro parceiro.", "danger")
            return redirect(url_for("participantes"))

        # ==========================
        # POST → ATUALIZAR
        # ==========================
        if request.method == "POST":
            nome = request.form["nome"].strip()
            data_nascimento = request.form.get("data_nascimento") or None
            idade = request.form.get("idade") or None
            cred = request.form["credencial"].strip()
            pcg = request.form.get("pcg") or None
            grupo = request.form.get("grupo") or None
            obs = request.form.get("observacoes", "").strip()
            status = request.form.get("status", "Ativo")

            cep        = request.form.get("cep")
            logradouro = request.form.get("logradouro")
            numero     = request.form.get("numero")
            bairro     = request.form.get("bairro")
            cidade     = request.form.get("cidade")
            uf         = request.form.get("uf")

            if not nome or not cred:
                flash("Nome e credencial são obrigatórios.", "danger")
                return redirect(url_for("editar_participante", id=id))

            conn.execute("""
                UPDATE participantes
                SET
                    nome=%s,
                    data_nascimento=%s,
                    idade=%s,
                    credencial=%s,
                    pcg=%s,
                    grupo=%s,
                    cep=%s,
                    logradouro=%s,
                    numero=%s,
                    bairro=%s,
                    cidade=%s,
                    uf=%s,
                    observacoes=%s,
                    status=%s
                WHERE id=%s
            """, (
                nome, data_nascimento, idade, cred, pcg, grupo,
                cep, logradouro, numero, bairro, cidade, uf,
                obs or None, status, id
            ))

            conn.commit()
            flash("Participante atualizado com sucesso!", "success")
            return redirect(url_for("participantes"))

        # ==========================
        # GET → FORM
        # ==========================
        return render_template(
            "participantes_form.html",
            modo="editar",
            registro=registro
        )

    except Exception:
        conn.rollback()
        flash("Erro ao atualizar participante.", "danger")
        return redirect(url_for("participantes"))

    finally:
        # 🔒 SEM return aqui
        conn.close()

# -----------------------------
# INATIVAR
# -----------------------------
@app.route("/participantes/inativar/<int:id>")
def inativar_participante(id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    usuario_tipo = session["usuario_tipo"]
    parceiro_id  = session["parceiro_id"]

    # 🔐 Permissão
    if usuario_tipo not in ["Administrador", "Master"]:
        flash("Você não tem permissão para inativar participantes.", "danger")
        return redirect(url_for("participantes"))

    conn = get_db()
    try:
        # ============================
        # VALIDAR PARTICIPANTE
        # ============================
        if usuario_tipo == "Administrador":
            participante = conn.execute(
                "SELECT status FROM participantes WHERE id=%s",
                (id,)
            ).fetchone()
        else:
            participante = conn.execute(
                "SELECT status FROM participantes WHERE id=%s AND parceiro_id=%s",
                (id, parceiro_id)
            ).fetchone()

        if not participante:
            flash("Participante não encontrado ou pertence a outro parceiro.", "danger")
            return redirect(url_for("participantes"))

        # ============================
        # EVITAR REPROCESSAMENTO
        # ============================
        if participante["status"] == "Inativo":
            flash("Este participante já está inativo.", "warning")
            return redirect(url_for("participantes"))

        # ============================
        # INATIVAR
        # ============================
        conn.execute(
            "UPDATE participantes SET status=%s WHERE id=%s",
            ("Inativo", id)
        )
        conn.commit()

        flash("Participante inativado com sucesso!", "success")
        return redirect(url_for("participantes"))

    except Exception:
        conn.rollback()
        flash("Erro ao inativar participante.", "danger")
        return redirect(url_for("participantes"))

    finally:
        # 🔒 garante devolução ao pool
        conn.close()

# -----------------------------
# EXCLUIR
# -----------------------------
@app.route("/participantes/excluir/<int:id>")
def excluir_participante(id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    usuario_tipo = session["usuario_tipo"]
    parceiro_id  = session["parceiro_id"]

    # 🔐 Permissões
    if usuario_tipo not in ["Administrador", "Master", "Suporte"]:
        flash("Ação não permitida para seu tipo de usuário.", "participante_error")
        return redirect(url_for("participantes"))

    conn = get_db()
    try:
        # =========================================
        # VALIDAR PARTICIPANTE
        # =========================================
        if usuario_tipo in ["Administrador", "Master"]:
            participante = conn.execute(
                "SELECT id FROM participantes WHERE id=%s",
                (id,)
            ).fetchone()
        else:
            participante = conn.execute(
                "SELECT id FROM participantes WHERE id=%s AND parceiro_id=%s",
                (id, parceiro_id)
            ).fetchone()

        if not participante:
            flash("Participante não encontrado ou pertence a outro parceiro.", "participante_error")
            return redirect(url_for("participantes"))

        # =========================================
        # EXCLUSÃO EM CASCATA
        # =========================================
        conn.execute(
            "DELETE FROM frequencia_diaria WHERE participante_id=%s",
            (id,)
        )
        conn.execute(
            "DELETE FROM frequencia_mensal WHERE participante_id=%s",
            (id,)
        )
        conn.execute(
            "DELETE FROM agendas_grupos_participantes WHERE participante_id=%s",
            (id,)
        )
        conn.execute(
            "DELETE FROM participantes WHERE id=%s",
            (id,)
        )

        conn.commit()
        flash("Participante excluído com sucesso!", "success")
        return redirect(url_for("participantes"))

    except Exception:
        conn.rollback()
        flash("Erro ao excluir participante.", "danger")
        return redirect(url_for("participantes"))

    finally:
        # 🔒 devolve conexão ao pool
        conn.close()

# ======================
# LISTAR + CADASTRAR EVENTOS
# ======================
@app.route("/eventos/cadastrar", methods=["GET", "POST"])
def eventos_cadastrar():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    usuario_tipo = session["usuario_tipo"]
    parceiro_id  = session["parceiro_id"]

    # 🔐 Permissão
    if usuario_tipo not in ["Suporte", "Master"]:
        flash("Você não tem permissão para cadastrar eventos.", "evento_error")
        return redirect(url_for("home"))

    conn = get_db()
    try:
        # ============================================================
        # POST – CADASTRAR EVENTO
        # ============================================================
        if request.method == "POST":
            nome = request.form["nome"].strip()

            if not nome:
                flash("O nome do evento é obrigatório.", "evento_error")
                return redirect(url_for("eventos_cadastrar"))

            existe = conn.execute(
                "SELECT id FROM eventos WHERE nome=%s AND parceiro_id=%s",
                (nome, parceiro_id)
            ).fetchone()

            if existe:
                flash("Já existe um evento com este nome para sua empresa.", "evento_warning")
                return redirect(url_for("eventos_cadastrar"))

            conn.execute("""
                INSERT INTO eventos (nome, parceiro_id, criado_em)
                VALUES (%s, %s, NOW())
            """, (nome, parceiro_id))

            conn.commit()
            flash("Evento criado com sucesso!", "success")
            return redirect(url_for("eventos_cadastrar"))

        # ============================================================
        # GET – LISTAR EVENTOS
        # ============================================================
        lista = conn.execute("""
            SELECT *
            FROM eventos
            WHERE parceiro_id=%s
            ORDER BY criado_em DESC
        """, (parceiro_id,)).fetchall()

        return render_template(
            "eventos_cadastrar.html",
            lista=lista
        )

    except Exception:
        conn.rollback()
        flash("Erro ao cadastrar evento.", "danger")
        return redirect(url_for("home"))

    finally:
        # 🔒 garante devolução da conexão ao pool
        conn.close()

# ======================
# EXCLUIR EVENTO
# ======================
@app.route("/eventos/excluir/<int:id>")
def eventos_excluir(id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    usuario_tipo = session["usuario_tipo"]
    parceiro_id  = session["parceiro_id"]

    # 🔐 Permissão:
    # Suporte → parceiro dele
    # Master → qualquer evento
    if usuario_tipo not in ["Suporte", "Master"]:
        flash("Você não tem permissão para excluir eventos.", "evento_error")
        return redirect(url_for("eventos_cadastrar"))

    conn = get_db()
    try:
        # ======================================
        # VALIDAR EVENTO
        # ======================================
        if usuario_tipo == "Master":
            evento = conn.execute(
                "SELECT id FROM eventos WHERE id=%s",
                (id,)
            ).fetchone()
        else:
            evento = conn.execute(
                "SELECT id FROM eventos WHERE id=%s AND parceiro_id=%s",
                (id, parceiro_id)
            ).fetchone()

        if not evento:
            flash("Evento não encontrado ou pertence a outro parceiro.", "evento_error")
            return redirect(url_for("eventos_cadastrar"))

        # ======================================
        # VERIFICAR AGENDAS VINCULADAS
        # ======================================
        if usuario_tipo == "Master":
            qtd = conn.execute(
                "SELECT COUNT(*) AS total FROM agendas_evento WHERE evento_id=%s",
                (id,)
            ).fetchone()["total"]
        else:
            qtd = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM agendas_evento
                WHERE evento_id=%s AND parceiro_id=%s
                """,
                (id, parceiro_id)
            ).fetchone()["total"]

        if qtd > 0:
            flash("Não é possível excluir: existem agendas vinculadas a este evento.", "evento_error")
            return redirect(url_for("eventos_cadastrar"))

        # ======================================
        # EXCLUIR EVENTO
        # ======================================
        conn.execute("DELETE FROM eventos WHERE id=%s", (id,))
        conn.commit()

        flash("Evento excluído com sucesso!", "success")
        return redirect(url_for("eventos_cadastrar"))

    except Exception:
        conn.rollback()
        flash("Erro ao excluir evento.", "danger")
        return redirect(url_for("eventos_cadastrar"))

    finally:
        # 🔒 devolve conexão ao pool
        conn.close()

# ======================
# EDITAR EVENTO
# ======================
@app.route("/eventos/editar/<int:id>", methods=["POST"])
def eventos_editar(id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    usuario_tipo = session["usuario_tipo"]
    parceiro_id  = session["parceiro_id"]

    # 🔐 Permissão correta
    if usuario_tipo not in ["Suporte", "Master"]:
        flash("Você não tem permissão para editar eventos.", "evento_error")
        return redirect(url_for("eventos_cadastrar"))

    nome = request.form.get("nome", "").strip()

    if not nome:
        flash("O nome do evento é obrigatório.", "evento_error")
        return redirect(url_for("eventos_cadastrar"))

    conn = get_db()
    try:
        # ===========================================
        # VALIDAR EVENTO
        # ===========================================
        if usuario_tipo == "Master":
            evento = conn.execute(
                "SELECT id FROM eventos WHERE id=%s",
                (id,)
            ).fetchone()
        else:
            evento = conn.execute(
                "SELECT id FROM eventos WHERE id=%s AND parceiro_id=%s",
                (id, parceiro_id)
            ).fetchone()

        if not evento:
            flash("Evento não encontrado ou pertence a outro parceiro.", "evento_error")
            return redirect(url_for("eventos_cadastrar"))

        # ===========================================
        # VERIFICAR DUPLICIDADE
        # ===========================================
        if usuario_tipo == "Master":
            existe = conn.execute(
                "SELECT id FROM eventos WHERE nome=%s AND id<>%s",
                (nome, id)
            ).fetchone()
        else:
            existe = conn.execute(
                """
                SELECT id FROM eventos
                WHERE nome=%s AND parceiro_id=%s AND id<>%s
                """,
                (nome, parceiro_id, id)
            ).fetchone()

        if existe:
            flash("Já existe um evento com este nome.", "evento_warning")
            return redirect(url_for("eventos_cadastrar"))

        # ===========================================
        # ATUALIZAR EVENTO (blindado)
        # ===========================================
        if usuario_tipo == "Master":
            conn.execute(
                "UPDATE eventos SET nome=%s WHERE id=%s",
                (nome, id)
            )
        else:
            conn.execute(
                "UPDATE eventos SET nome=%s WHERE id=%s AND parceiro_id=%s",
                (nome, id, parceiro_id)
            )

        conn.commit()

        flash("Evento atualizado com sucesso!", "success")
        return redirect(url_for("eventos_cadastrar"))

    except Exception:
        conn.rollback()
        flash("Erro ao atualizar evento.", "danger")
        return redirect(url_for("eventos_cadastrar"))

    finally:
        # 🔒 devolve conexão ao pool SEMPRE
        conn.close()

# =========================================
# PARTICIPANTES DE UM GRUPO DA AGENDA
# =========================================
@app.route("/agenda/<int:agenda_id>/grupos/<int:grupo_id>/participantes", methods=["GET", "POST"])
def grupo_participantes(agenda_id, grupo_id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    usuario_tipo = session["usuario_tipo"]
    parceiro_id  = session["parceiro_id"]

    conn = get_db()
    try:
        # =====================================================
        # VALIDAR GRUPO + AGENDA + EVENTO
        # =====================================================
        if usuario_tipo == "Administrador":
            grupo = conn.execute("""
                SELECT g.*, a.nome_agenda, a.parceiro_id, e.nome AS evento_nome
                FROM agendas_grupos g
                JOIN agendas_evento a ON a.id = g.agenda_id
                JOIN eventos e ON e.id = a.evento_id
                WHERE g.id = %s
            """, (grupo_id,)).fetchone()
        else:
            grupo = conn.execute("""
                SELECT g.*, a.nome_agenda, a.parceiro_id, e.nome AS evento_nome
                FROM agendas_grupos g
                JOIN agendas_evento a ON a.id = g.agenda_id
                JOIN eventos e ON e.id = a.evento_id
                WHERE g.id = %s AND a.parceiro_id = %s
            """, (grupo_id, parceiro_id)).fetchone()

        if not grupo or grupo["agenda_id"] != agenda_id:
            flash("Grupo não encontrado ou inválido.", "danger")
            return redirect(url_for("home"))

        # =====================================================
        # POST — ATUALIZAR VÍNCULOS
        # =====================================================
        if request.method == "POST":

            if usuario_tipo not in ["Administrador", "Master"]:
                flash("Você não tem permissão para alterar os participantes.", "danger")
                return redirect(url_for(
                    "grupo_participantes",
                    agenda_id=agenda_id,
                    grupo_id=grupo_id
                ))

            selecionados = request.form.getlist("participante")

            # 🔒 Transação segura
            conn.execute(
                "DELETE FROM agendas_grupos_participantes WHERE grupo_id = %s",
                (grupo_id,)
            )

            for pid in selecionados:
                if usuario_tipo == "Administrador":
                    participante = conn.execute(
                        "SELECT id FROM participantes WHERE id = %s",
                        (pid,)
                    ).fetchone()
                else:
                    participante = conn.execute(
                        "SELECT id FROM participantes WHERE id = %s AND parceiro_id = %s",
                        (pid, parceiro_id)
                    ).fetchone()

                if participante:
                    conn.execute("""
                        INSERT INTO agendas_grupos_participantes
                            (grupo_id, participante_id, parceiro_id)
                        VALUES (%s, %s, %s)
                    """, (
                        grupo_id,
                        pid,
                        grupo["parceiro_id"]
                    ))

            conn.commit()
            flash("Participantes associados com sucesso!", "success")
            return redirect(url_for(
                "grupo_participantes",
                agenda_id=agenda_id,
                grupo_id=grupo_id
            ))

        # =====================================================
        # GET — DADOS PARA TELA
        # =====================================================
        associados = conn.execute("""
            SELECT participante_id
            FROM agendas_grupos_participantes
            WHERE grupo_id = %s
        """, (grupo_id,)).fetchall()

        ids_associados = [r["participante_id"] for r in associados]

        busca = request.args.get("busca", "").strip()
        grupo_filtro = request.args.get("grupo", "").strip()
        pcg_filtro = request.args.get("pcg", "").strip()
        classificacao = request.args.get("classificacao", "").strip()

        where = ["parceiro_id = %s", "status = 'Ativo'"]
        params = [grupo["parceiro_id"]]

        if busca:
            where.append("nome LIKE %s")
            params.append(f"%{busca}%")

        if grupo_filtro:
            where.append("grupo LIKE %s")
            params.append(f"%{grupo_filtro}%")

        if pcg_filtro:
            where.append("pcg LIKE %s")
            params.append(f"%{pcg_filtro}%")

        if classificacao:
            where.append("classificacao LIKE %s")
            params.append(f"%{classificacao}%")

        participantes = conn.execute(f"""
            SELECT *
            FROM participantes
            WHERE {' AND '.join(where)}
            ORDER BY nome ASC
        """, params).fetchall()

        return render_template(
            "participantes_grupo.html",
            grupo=grupo,
            participantes=participantes,
            ids_associados=ids_associados,
            busca=busca,
            grupo_filtro=grupo_filtro,
            pcg=pcg_filtro,
            classificacao=classificacao
        )

    except Exception as e:
        conn.rollback()
        flash("Erro ao processar participantes do grupo.", "danger")
        return redirect(url_for("home"))

    finally:
        conn.close()

# ==========================================================
# FREQUÊNCIA DIÁRIA DO GRUPO
# ==========================================================
@app.route("/agenda/<int:agenda_id>/grupos/<int:grupo_id>/frequencia/diaria", methods=["GET", "POST"])
def grupo_frequencia_diaria(agenda_id, grupo_id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    usuario_tipo = session["usuario_tipo"]
    parceiro_id  = session["parceiro_id"]

    conn = get_db()
    try:
        # ===========================================================
        # VALIDAR GRUPO + AGENDA + EVENTO
        # ===========================================================
        if usuario_tipo == "Administrador":
            grupo = conn.execute("""
                SELECT g.*, a.nome_agenda, e.nome AS evento_nome, a.parceiro_id
                FROM agendas_grupos g
                JOIN agendas_evento a ON g.agenda_id = a.id
                JOIN eventos e ON a.evento_id = e.id
                WHERE g.id = %s
            """, (grupo_id,)).fetchone()
        else:
            grupo = conn.execute("""
                SELECT g.*, a.nome_agenda, e.nome AS evento_nome, a.parceiro_id
                FROM agendas_grupos g
                JOIN agendas_evento a ON g.agenda_id = a.id
                JOIN eventos e ON a.evento_id = e.id
                WHERE g.id = %s AND g.parceiro_id = %s
            """, (grupo_id, parceiro_id)).fetchone()

        if not grupo or grupo["agenda_id"] != agenda_id:
            flash("Grupo não encontrado ou inválido.", "danger")
            return redirect(url_for("home"))

        # ===========================================================
        # DATA
        # ===========================================================
        data = request.args.get("data") or datetime.now().strftime("%Y-%m-%d")

        # ===========================================================
        # POST — SALVAR FREQUÊNCIA
        # ===========================================================
        if request.method == "POST":

            if usuario_tipo not in ["Administrador", "Master"]:
                flash("Você não tem permissão para registrar frequência.", "danger")
                return redirect(url_for(
                    "grupo_frequencia_diaria",
                    agenda_id=agenda_id,
                    grupo_id=grupo_id,
                    data=data
                ))

            selecionados = request.form.getlist("presenca")

            # 🔒 Apaga frequências do dia
            conn.execute("""
                DELETE FROM frequencia_diaria
                WHERE grupo_id = %s AND data = %s
            """, (grupo_id, data))

            for pid in selecionados:

                if usuario_tipo == "Administrador":
                    participante = conn.execute(
                        "SELECT id FROM participantes WHERE id = %s",
                        (pid,)
                    ).fetchone()
                else:
                    participante = conn.execute(
                        "SELECT id FROM participantes WHERE id = %s AND parceiro_id = %s",
                        (pid, parceiro_id)
                    ).fetchone()

                if not participante:
                    continue

                conn.execute("""
                    INSERT INTO frequencia_diaria
                        (grupo_id, participante_id, data, presente, parceiro_id)
                    VALUES (%s, %s, %s, 1, %s)
                """, (
                    grupo_id,
                    pid,
                    data,
                    grupo["parceiro_id"]
                ))

            conn.commit()
            flash("Frequência diária salva com sucesso!", "success")
            return redirect(url_for(
                "grupo_frequencia_diaria",
                agenda_id=agenda_id,
                grupo_id=grupo_id,
                data=data
            ))

        # ===========================================================
        # GET — PARTICIPANTES DO GRUPO
        # ===========================================================
        participantes = conn.execute("""
            SELECT p.*
            FROM participantes p
            JOIN agendas_grupos_participantes agp
                ON agp.participante_id = p.id
            WHERE agp.grupo_id = %s AND p.parceiro_id = %s
            ORDER BY p.nome ASC
        """, (grupo_id, grupo["parceiro_id"])).fetchall()

        freq = conn.execute("""
            SELECT participante_id
            FROM frequencia_diaria
            WHERE grupo_id = %s AND data = %s
        """, (grupo_id, data)).fetchall()

        presentes_ids = [f["participante_id"] for f in freq]

        historico = conn.execute("""
            SELECT data, COUNT(*) AS qtd
            FROM frequencia_diaria
            WHERE grupo_id = %s
            GROUP BY data
            ORDER BY data DESC
            LIMIT 10
        """, (grupo_id,)).fetchall()

        return render_template(
            "frequencia_diaria.html",
            grupo=grupo,
            participantes=participantes,
            presentes_ids=presentes_ids,
            data=data,
            historico=historico
        )

    except Exception as e:
        conn.rollback()
        flash("Erro ao salvar frequência diária.", "danger")
        return redirect(url_for("home"))

    finally:
        conn.close()

# ==========================================================
# FREQUÊNCIA MENSAL DO GRUPO
# ==========================================================

@app.route("/agenda/<int:agenda_id>/grupos/<int:grupo_id>/frequencia/mensal", methods=["GET", "POST"])
def grupo_frequencia_mensal(agenda_id, grupo_id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    usuario_tipo = session["usuario_tipo"]
    parceiro_id  = session["parceiro_id"]

    conn = get_db()
    try:
        # ===========================================================
        # GRUPO / AGENDA / EVENTO
        # ===========================================================
        if usuario_tipo == "Administrador":
            grupo = conn.execute("""
                SELECT g.*, a.nome_agenda, e.nome AS evento_nome, a.parceiro_id
                FROM agendas_grupos g
                JOIN agendas_evento a ON g.agenda_id = a.id
                JOIN eventos e ON a.evento_id = e.id
                WHERE g.id = %s
            """, (grupo_id,)).fetchone()
        else:
            grupo = conn.execute("""
                SELECT g.*, a.nome_agenda, e.nome AS evento_nome, a.parceiro_id
                FROM agendas_grupos g
                JOIN agendas_evento a ON g.agenda_id = a.id
                JOIN eventos e ON a.evento_id = e.id
                WHERE g.id = %s AND g.parceiro_id = %s
            """, (grupo_id, parceiro_id)).fetchone()

        if not grupo or grupo["agenda_id"] != agenda_id:
            flash("Grupo inválido ou não pertence à agenda.", "danger")
            return redirect(url_for("home"))

        # ===========================================================
        # MÊS
        # ===========================================================
        mes = request.args.get("mes") or request.form.get("mes") or datetime.now().strftime("%Y-%m")
        ano, mes_num = map(int, mes.split("-"))
        total_dias = monthrange(ano, mes_num)[1]

        inicio_mes = f"{ano}-{mes_num:02d}-01"
        inicio_prox_mes = (
            f"{ano + 1}-01-01"
            if mes_num == 12
            else f"{ano}-{mes_num + 1:02d}-01"
        )

        # ===========================================================
        # PARTICIPANTES DO GRUPO
        # ===========================================================
        participantes = conn.execute("""
            SELECT p.*
            FROM participantes p
            JOIN agendas_grupos_participantes agp
                ON agp.participante_id = p.id
            WHERE agp.grupo_id = %s AND p.parceiro_id = %s
            ORDER BY p.nome
        """, (grupo_id, grupo["parceiro_id"])).fetchall()

        # ===========================================================
        # POST — SALVAR FREQUÊNCIA MENSAL
        # ===========================================================
        if request.method == "POST":

            if usuario_tipo not in ["Administrador", "Master"]:
                flash("Você não tem permissão para registrar frequência mensal.", "danger")
                return redirect(url_for(
                    "grupo_frequencia_mensal",
                    agenda_id=agenda_id,
                    grupo_id=grupo_id,
                    mes=mes
                ))

            # 🔒 apagar mês inteiro
            conn.execute("""
                DELETE FROM frequencia_diaria
                WHERE grupo_id = %s
                  AND data >= %s
                  AND data < %s
            """, (grupo_id, inicio_mes, inicio_prox_mes))

            for p in participantes:
                pid = str(p["id"])
                for dia in range(1, total_dias + 1):
                    if request.form.get(f"{pid}_{dia}") == "on":
                        data_formatada = f"{ano}-{mes_num:02d}-{dia:02d}"

                        conn.execute("""
                            INSERT INTO frequencia_diaria
                                (grupo_id, participante_id, data, presente, parceiro_id)
                            VALUES (%s, %s, %s, 1, %s)
                        """, (
                            grupo_id,
                            p["id"],
                            data_formatada,
                            grupo["parceiro_id"]
                        ))

            conn.commit()
            flash("Frequência mensal salva com sucesso!", "success")

            return redirect(url_for(
                "grupo_frequencia_mensal",
                agenda_id=agenda_id,
                grupo_id=grupo_id,
                mes=mes
            ))

        # ===========================================================
        # GET — CARREGAR MATRIZ
        # ===========================================================
        presencas = conn.execute("""
            SELECT participante_id, DAY(data) AS dia
            FROM frequencia_diaria
            WHERE grupo_id = %s
              AND data >= %s
              AND data < %s
        """, (grupo_id, inicio_mes, inicio_prox_mes)).fetchall()

        matriz = {
            p["id"]: {dia: False for dia in range(1, total_dias + 1)}
            for p in participantes
        }

        for row in presencas:
            if row["participante_id"] in matriz:
                matriz[row["participante_id"]][row["dia"]] = True

        return render_template(
            "frequencia_mensal.html",
            grupo=grupo,
            mes=mes,
            total_dias=total_dias,
            participantes=participantes,
            matriz=matriz
        )

    except Exception as e:
        conn.rollback()
        flash("Erro ao salvar frequência mensal.", "danger")
        return redirect(url_for("home"))

    finally:
        conn.close()

#Rota para buscar agendas de um evento
@app.route("/ajax/agendas/<int:evento_id>")
def ajax_agendas(evento_id):
    if "usuario_id" not in session:
        return jsonify({"error": "Não autenticado"}), 403

    parceiro_id = session["parceiro_id"]
    usuario_tipo = session["usuario_tipo"]

    mes = request.args.get("mes")  # formato YYYY-MM
    if not mes:
        return jsonify([])

    conn = get_db()
    try:
        # ====================================================
        # VALIDAR EVENTO
        # ====================================================
        if usuario_tipo == "Administrador":
            evento = conn.execute(
                "SELECT id FROM eventos WHERE id = %s",
                (evento_id,)
            ).fetchone()
        else:
            evento = conn.execute(
                "SELECT id FROM eventos WHERE id = %s AND parceiro_id = %s",
                (evento_id, parceiro_id)
            ).fetchone()

        if not evento:
            return jsonify({"error": "Evento não encontrado"}), 403

        # ====================================================
        # BUSCAR AGENDAS DO EVENTO NO MÊS (MYSQL)
        # ====================================================
        if usuario_tipo == "Administrador":
            rows = conn.execute("""
                SELECT id, nome_agenda
                FROM agendas_evento
                WHERE evento_id = %s
                  AND DATE_FORMAT(data_inicio, '%%Y-%%m') = %s
                ORDER BY nome_agenda
            """, (evento_id, mes)).fetchall()
        else:
            rows = conn.execute("""
                SELECT id, nome_agenda
                FROM agendas_evento
                WHERE evento_id = %s
                  AND parceiro_id = %s
                  AND DATE_FORMAT(data_inicio, '%%Y-%%m') = %s
                ORDER BY nome_agenda
            """, (evento_id, parceiro_id, mes)).fetchall()

        return jsonify([dict(r) for r in rows])

    finally:
        conn.close()

@app.route("/ajax/grupos/<int:agenda_id>")
def ajax_grupos(agenda_id):
    if "usuario_id" not in session:
        return jsonify({"error": "Não autenticado"}), 403

    parceiro_id = session["parceiro_id"]
    usuario_tipo = session["usuario_tipo"]

    mes = request.args.get("mes")  # formato YYYY-MM
    if not mes:
        return jsonify([])

    conn = get_db()
    try:
        # =====================================================
        # VALIDAR AGENDA
        # =====================================================
        if usuario_tipo == "Administrador":
            agenda = conn.execute(
                "SELECT id FROM agendas_evento WHERE id = %s",
                (agenda_id,)
            ).fetchone()
        else:
            agenda = conn.execute(
                "SELECT id FROM agendas_evento WHERE id = %s AND parceiro_id = %s",
                (agenda_id, parceiro_id)
            ).fetchone()

        if not agenda:
            return jsonify({"error": "Agenda não encontrada"}), 403

        # =====================================================
        # LISTAR GRUPOS DA AGENDA (MYSQL)
        # =====================================================
        if usuario_tipo == "Administrador":
            rows = conn.execute("""
                SELECT g.id, g.nome
                FROM agendas_grupos g
                JOIN agendas_evento a ON a.id = g.agenda_id
                WHERE g.agenda_id = %s
                  AND DATE_FORMAT(a.data_inicio, '%%Y-%%m') = %s
                ORDER BY g.nome
            """, (agenda_id, mes)).fetchall()
        else:
            rows = conn.execute("""
                SELECT g.id, g.nome
                FROM agendas_grupos g
                JOIN agendas_evento a ON a.id = g.agenda_id
                WHERE g.agenda_id = %s
                  AND g.parceiro_id = %s
                  AND DATE_FORMAT(a.data_inicio, '%%Y-%%m') = %s
                ORDER BY g.nome
            """, (agenda_id, parceiro_id, mes)).fetchall()

        return jsonify([dict(r) for r in rows])

    finally:
        conn.close()

# /ajax/painel-dados (retorna TUDO em JSON)
@app.route("/ajax/painel-dados")
def ajax_painel_dados():
    if "usuario_id" not in session:
        return jsonify({"error": "Não autenticado"}), 403

    from datetime import datetime
    from calendar import monthrange

    parceiro_id = session["parceiro_id"]
    usuario_tipo = session["usuario_tipo"]

    conn = get_db()
    try:

        # -------------------------
        # PARÂMETROS DE FILTRO
        # -------------------------
        tipo_data = request.args.get("tipo_data", "mes")
        mes = request.args.get("mes", "")          # "YYYY-MM"
        ano_param = request.args.get("ano", "")    # "YYYY"
        data_de = request.args.get("data_de", "")
        data_ate = request.args.get("data_ate", "")

        evento_id = request.args.get("evento") or None
        agenda_id = request.args.get("agenda") or None
        grupo_id = request.args.get("grupo") or None

        # normalizar IDs
        try:
            evento_id = int(evento_id) if evento_id else None
        except ValueError:
            evento_id = None

        try:
            agenda_id = int(agenda_id) if agenda_id else None
        except ValueError:
            agenda_id = None

        try:
            grupo_id = int(grupo_id) if grupo_id else None
        except ValueError:
            grupo_id = None

        # -------------------------
        # VALIDAR EVENTO / AGENDA / GRUPO CONTRA PARCEIRO
        # -------------------------
        # Evento
        if evento_id:
            if usuario_tipo == "Administrador":
                ev = conn.execute(
                    "SELECT * FROM eventos WHERE id=%s",
                    (evento_id,)
                ).fetchone()
            else:
                ev = conn.execute(
                    "SELECT * FROM eventos WHERE id=%s AND parceiro_id=%s",
                    (evento_id, parceiro_id)
                ).fetchone()
            if not ev:
                evento_id = None

        # Agenda
        if agenda_id:
            if usuario_tipo == "Administrador":
                ag = conn.execute(
                    "SELECT * FROM agendas_evento WHERE id=%s",
                    (agenda_id,)
                ).fetchone()
            else:
                ag = conn.execute(
                    "SELECT * FROM agendas_evento WHERE id=%s AND parceiro_id=%s",
                    (agenda_id, parceiro_id)
                ).fetchone()
            if not ag:
                agenda_id = None
            else:
                # se veio evento_id, garantir coerência
                if evento_id and ag["evento_id"] != evento_id:
                    agenda_id = None

        # Grupo
        if grupo_id:
            if usuario_tipo == "Administrador":
                gr = conn.execute(
                    "SELECT * FROM agendas_grupos WHERE id=%s",
                    (grupo_id,)
                ).fetchone()
            else:
                gr = conn.execute(
                    "SELECT * FROM agendas_grupos WHERE id=%s AND parceiro_id=%s",
                    (grupo_id, parceiro_id)
                ).fetchone()
            if not gr:
                grupo_id = None
            else:
                if agenda_id and gr["agenda_id"] != agenda_id:
                    grupo_id = None

        # -------------------------
        # DEFINIR INTERVALO DE DATAS
        # -------------------------
        hoje = datetime.now()

        # 1) Filtro por ANO
        if tipo_data == "ano" and ano_param:
            try:
                ano_int = int(ano_param)
                data_ini = f"{ano_int:04d}-01-01"
                data_fim = f"{ano_int:04d}-12-31"
            except ValueError:
                tipo_data = "mes"

        # 2) Filtro por PERÍODO
        if tipo_data == "periodo" and data_de and data_ate:
            data_ini = data_de
            data_fim = data_ate

        # 3) Filtro por MÊS (padrão)
        if tipo_data == "mes" or ("data_ini" not in locals()):
            if not mes:
                mes = hoje.strftime("%Y-%m")
            ano, mes_num = map(int, mes.split("-"))
            data_ini = f"{ano:04d}-{mes_num:02d}-01"
            ultimo_dia = monthrange(ano, mes_num)[1]
            data_fim = f"{ano:04d}-{mes_num:02d}-{ultimo_dia:02d}"

        # -------------------------
        # CARDS: TOTAL DE AGENDAS
        # -------------------------
        sql_agendas = """
            SELECT COUNT(DISTINCT a.id) AS total
            FROM agendas_evento a
            LEFT JOIN agendas_grupos g ON g.agenda_id = a.id
            WHERE a.data_inicio BETWEEN %s AND %s
        """
        params_agendas = [data_ini, data_fim]

        if usuario_tipo != "Administrador":
            sql_agendas += " AND a.parceiro_id = %s"
            params_agendas.append(parceiro_id)

        if evento_id:
            sql_agendas += " AND a.evento_id = %s"
            params_agendas.append(evento_id)

        if agenda_id:
            sql_agendas += " AND a.id = %s"
            params_agendas.append(agenda_id)

        if grupo_id:
            sql_agendas += " AND g.id = %s"
            params_agendas.append(grupo_id)

        total_agendas = conn.execute(sql_agendas, params_agendas).fetchone()["total"]

        # -------------------------
        # CARDS: TOTAL DE PRESENÇAS
        # -------------------------
        sql_pres = """
            SELECT COUNT(*) AS total
            FROM frequencia_diaria f
            JOIN agendas_grupos g   ON g.id = f.grupo_id
            JOIN agendas_evento a   ON a.id = g.agenda_id
           WHERE f.data BETWEEN %s AND %s
        """
        params_pres = [data_ini, data_fim]

        if usuario_tipo != "Administrador":
            sql_pres += " AND a.parceiro_id = %s"
            params_pres.append(parceiro_id)

        if evento_id:
            sql_pres += " AND a.evento_id = %s"
            params_pres.append(evento_id)

        if agenda_id:
            sql_pres += " AND g.agenda_id = %s"
            params_pres.append(agenda_id)

        if grupo_id:
            sql_pres += " AND g.id = %s"
            params_pres.append(grupo_id)

        total_presencas = conn.execute(sql_pres, params_pres).fetchone()["total"]

        # -------------------------
        # COMBOS DEPENDENTES
        # -------------------------
        agendas = []
        if evento_id:
            sql_list_ag = """
                SELECT a.id, a.nome_agenda
                FROM agendas_evento a
                WHERE a.evento_id = %s
                AND DATE(a.data_inicio) BETWEEN DATE(%s) AND DATE(%s)
            """
            params_list_ag = [evento_id, data_ini, data_fim]

            if usuario_tipo != "Administrador":
                sql_list_ag += " AND a.parceiro_id = %s"
                params_list_ag.append(parceiro_id)

            sql_list_ag += " ORDER BY a.nome_agenda"
            agendas = conn.execute(sql_list_ag, params_list_ag).fetchall()

        grupos = []
        if agenda_id:
            sql_list_gr = """
                SELECT g.id, g.nome
                FROM agendas_grupos g
                WHERE g.agenda_id = %s
            """
            params_list_gr = [agenda_id]

            if usuario_tipo != "Administrador":
                sql_list_gr += " AND g.parceiro_id = %s"
                params_list_gr.append(parceiro_id)

            sql_list_gr += " ORDER BY g.nome"
            grupos = conn.execute(sql_list_gr, params_list_gr).fetchall()

        # -------------------------
        # GRÁFICO BARRAS: AGENDAS x MÊS
        # -------------------------
        sql_ag_mes = """
            SELECT DATE_FORMAT(a.data_inicio, '%Y-%m') AS mes,
                COUNT(DISTINCT a.id) AS qtd
            FROM agendas_evento a
            LEFT JOIN agendas_grupos g ON g.agenda_id = a.id
            WHERE a.data_inicio BETWEEN %s AND %s
        """
        params_ag_mes = [data_ini, data_fim]

        if usuario_tipo != "Administrador":
            sql_ag_mes += " AND a.parceiro_id = %s"
            params_ag_mes.append(parceiro_id)

        if evento_id:
            sql_ag_mes += " AND a.evento_id = %s"
            params_ag_mes.append(evento_id)

        if agenda_id:
            sql_ag_mes += " AND a.id = %s"
            params_ag_mes.append(agenda_id)

        if grupo_id:
            sql_ag_mes += " AND g.id = %s"
            params_ag_mes.append(grupo_id)

        sql_ag_mes += """
            GROUP BY DATE_FORMAT(a.data_inicio, '%Y-%m')
            ORDER BY mes
        """

        agendas_mes_rows = conn.execute(sql_ag_mes, params_ag_mes).fetchall()
        agendas_mes = [{"mes": r["mes"], "qtd": r["qtd"]} for r in agendas_mes_rows]

        # -------------------------
        # GRÁFICO BARRAS: CREDENCIAL (POR PARTICIPANTE ÚNICO / GRUPO)
        # -------------------------
        sql_cred = """
            SELECT tipo, COUNT(*) AS qtd
            FROM (
                SELECT 
                    CASE
                        WHEN UPPER(p.credencial) = 'PG' THEN 'PG'
                        WHEN UPPER(p.credencial) = 'CO' THEN 'CO'
                        WHEN UPPER(p.credencial) = 'DC' THEN 'DC'
                        ELSE 'OUTROS'
                    END AS tipo,
                    f.grupo_id,
                    f.participante_id
                FROM frequencia_diaria f
                JOIN participantes    p ON p.id = f.participante_id
                JOIN agendas_grupos   g ON g.id = f.grupo_id
                JOIN agendas_evento   a ON a.id = g.agenda_id
                WHERE f.data BETWEEN %s AND %s
        """

        params_cred = [data_ini, data_fim]

        if usuario_tipo != "Administrador":
            sql_cred += " AND a.parceiro_id = %s"
            params_cred.append(parceiro_id)

        if evento_id:
            sql_cred += " AND a.evento_id = %s"
            params_cred.append(evento_id)

        if agenda_id:
            sql_cred += " AND g.agenda_id = %s"
            params_cred.append(agenda_id)

        if grupo_id:
            sql_cred += " AND g.id = %s"
            params_cred.append(grupo_id)

        # aqui garantimos 1 linha por participante/grupo/tipo
        sql_cred += """
                GROUP BY f.grupo_id, f.participante_id, tipo
            ) sub
            GROUP BY tipo
        """

        cred_rows = conn.execute(sql_cred, params_cred).fetchall()
        mapa_cred = {r["tipo"]: r["qtd"] for r in cred_rows}
        cred_series = []
        for tipo in ["PG", "CO", "DC"]:
            cred_series.append({
                "tipo": tipo,
                "qtd": mapa_cred.get(tipo, 0)
            })
    
        # -------------------------
        # GRÁFICO PIZZA: PCG (POR PARTICIPANTE ÚNICO / GRUPO)
        # -------------------------
        sql_pcg = """
            SELECT pcg, COUNT(*) AS qtd
            FROM (
                SELECT 
                CASE 
                    WHEN p.pcg IS NULL OR p.pcg = '' THEN 'Não informado'
                    ELSE p.pcg
                END AS pcg,
                f.grupo_id,
                f.participante_id
                FROM frequencia_diaria f
                JOIN participantes    p ON p.id = f.participante_id
                JOIN agendas_grupos   g ON g.id = f.grupo_id
                JOIN agendas_evento   a ON a.id = g.agenda_id
                WHERE f.data BETWEEN %s AND %s
        """

        params_pcg = [data_ini, data_fim]

        if usuario_tipo != "Administrador":
            sql_pcg += " AND a.parceiro_id = %s"
            params_pcg.append(parceiro_id)

        if evento_id:
            sql_pcg += " AND a.evento_id = %s"
            params_pcg.append(evento_id)

        if agenda_id:
            sql_pcg += " AND g.agenda_id = %s"
            params_pcg.append(agenda_id)

        if grupo_id:
            sql_pcg += " AND g.id = %s"
            params_pcg.append(grupo_id)

        # 1 linha por participante/grupo/pcg
        sql_pcg += """
                GROUP BY f.grupo_id, f.participante_id, pcg
            ) sub
            GROUP BY pcg
            ORDER BY pcg
        """

        pcg_rows = conn.execute(sql_pcg, params_pcg).fetchall()
        pcg_series = [{"pcg": r["pcg"], "qtd": r["qtd"]} for r in pcg_rows]
    
        # -------------------------
        # GRÁFICO PARTICIPANTES POR GRUPO
        # -------------------------
        sql_pgrupo = """
            SELECT g.nome AS grupo_nome,
                COUNT(DISTINCT agp.participante_id) AS qtd
            FROM agendas_grupos g
            LEFT JOIN agendas_grupos_participantes agp 
                    ON agp.grupo_id = g.id
            LEFT JOIN agendas_evento a 
                    ON a.id = g.agenda_id
            WHERE a.data_inicio BETWEEN %s AND %s
        """
        params_pgrupo = [data_ini, data_fim]

        if usuario_tipo != "Administrador":
            sql_pgrupo += " AND g.parceiro_id = %s"
            params_pgrupo.append(parceiro_id)

        if evento_id:
            sql_pgrupo += " AND a.evento_id = %s"
            params_pgrupo.append(evento_id)

        if agenda_id:
            sql_pgrupo += " AND g.agenda_id = %s"
            params_pgrupo.append(agenda_id)

        if grupo_id:
            sql_pgrupo += " AND g.id = %s"
            params_pgrupo.append(grupo_id)

        sql_pgrupo += """
            GROUP BY g.nome
            ORDER BY g.nome
        """

        pgrupo_rows = conn.execute(sql_pgrupo, params_pgrupo).fetchall()
        participantes_por_grupo = [
            {"grupo": r["grupo_nome"], "qtd": r["qtd"]} 
            for r in pgrupo_rows
        ]

        return jsonify({
            "cards": {
                "total_agendas": total_agendas,
                "total_presencas": total_presencas
            },
            "agendas": [dict(r) for r in agendas],
            "grupos": [dict(r) for r in grupos],
            "series": {
                "agendas_mes": agendas_mes,
                "credencial": cred_series,
                "pcg": pcg_series,
                "participantes_grupo": participantes_por_grupo
            },
            "intervalo": {
                "tipo_data": tipo_data,
                "ano": ano_param or "",
                "mes": mes or "",
                "data_de": data_ini,
                "data_ate": data_fim
            }
        })
    except Exception:
        return jsonify({"errr": "Erro ao carregar dados do painel"}), 500
    finally:
        conn.close()

def desenhar_rodape(pdf, largura, nome_usuario):
    pdf.setFont("Helvetica", 8)
    pdf.setFillColorRGB(0.3, 0.3, 0.3)

    agora = datetime.now().strftime("%d/%m/%Y %H:%M")

    y = 20  # margem segura de rodapé

    # Esquerda: data/hora
    pdf.drawString(40, y, f"Gerado em: {agora}")

    # Direita: usuário
    pdf.drawRightString(largura - 40, y, f"Usuário: {nome_usuario}")

    # Centro: página (um pouco abaixo)
    pdf.drawCentredString(largura / 2, y - 10, f"Página {pdf.getPageNumber()}")

@app.route("/relatorio/pdf")
def gerar_relatorio_pdf():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    usuario_tipo = session["usuario_tipo"]
    parceiro_id = session["parceiro_id"]
    usuario_nome = session.get("usuario_nome", "Usuário")

    if usuario_tipo not in ["Administrador", "Master"]:
        flash("Você não tem permissão para gerar relatórios.", "danger")
        return redirect(url_for("painel"))

    # -----------------------------
    # PARÂMETROS
    # -----------------------------
    tipo_data = request.args.get("tipo_data", "")
    mes = request.args.get("mes", "")
    ano = request.args.get("ano", "")
    data_de = request.args.get("data_de", "")
    data_ate = request.args.get("data_ate", "")
    evento = request.args.get("evento", "")
    agenda = request.args.get("agenda", "")
    grupo = request.args.get("grupo", "")

    def to_int(v):
        try:
            return int(v)
        except:
            return None

    evento_id = to_int(evento)
    agenda_id = to_int(agenda)
    grupo_id = to_int(grupo)

    conn = get_db()

    # -----------------------------
    # VALIDAR EVENTO
    # -----------------------------
    if evento_id:
        q = "SELECT * FROM eventos WHERE id=?"
        params = [evento_id]
        if usuario_tipo != "Administrador":
            q += " AND parceiro_id=?"
            params.append(parceiro_id)
        ev = conn.execute(q, params).fetchone()
        if not ev:
            conn.close()
            flash("Evento inválido.", "danger")
            return redirect(url_for("painel"))

    # -----------------------------
    # VALIDAR AGENDA
    # -----------------------------
    if agenda_id:
        q = "SELECT * FROM agendas_evento WHERE id=?"
        params = [agenda_id]
        if usuario_tipo != "Administrador":
            q += " AND parceiro_id=?"
            params.append(parceiro_id)
        ag = conn.execute(q, params).fetchone()
        if not ag:
            conn.close()
            flash("Agenda inválida.", "danger")
            return redirect(url_for("painel"))
        if evento_id and ag["evento_id"] != evento_id:
            conn.close()
            flash("Agenda não pertence ao evento.", "danger")
            return redirect(url_for("painel"))

    # -----------------------------
    # VALIDAR GRUPO
    # -----------------------------
    if grupo_id:
        q = "SELECT * FROM agendas_grupos WHERE id=?"
        params = [grupo_id]
        if usuario_tipo != "Administrador":
            q += " AND parceiro_id=?"
            params.append(parceiro_id)
        gr = conn.execute(q, params).fetchone()
        if not gr:
            conn.close()
            flash("Grupo inválido.", "danger")
            return redirect(url_for("painel"))
        if agenda_id and gr["agenda_id"] != agenda_id:
            conn.close()
            flash("Grupo não pertence à agenda.", "danger")
            return redirect(url_for("painel"))

    conn.close()

    # -----------------------------
    # REAPROVEITAR FILTROS DO PAINEL
    # -----------------------------
    params = {"tipo_data": tipo_data, "mes": mes, "ano": ano}
    if data_de: params["data_de"] = data_de
    if data_ate: params["data_ate"] = data_ate
    if evento: params["evento"] = evento
    if agenda: params["agenda"] = agenda
    if grupo: params["grupo"] = grupo

    query = "&".join(f"{k}={v}" for k, v in params.items())

    sess = dict(session)

    with app.test_request_context(f"/ajax/painel-dados?{query}"):
        session.update(sess)

        resp = ajax_painel_dados()
        if isinstance(resp, tuple):
            resp = resp[0]

        dados = resp.get_json()
        if not dados or "error" in dados:
            flash("Erro ao gerar dados do relatório.", "danger")
            return redirect(url_for("painel"))

    # -----------------------------
    # ESTILO DAS TABELAS
    # -----------------------------
    TABLE_STYLE = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e0e0e0")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ])

    # -----------------------------
    # INICIAR PDF
    # -----------------------------
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    largura, altura = A4

    # Cabeçalho
    pdf.setFillColorRGB(0.15, 0.15, 0.15)
    pdf.rect(0, altura - 60, largura, 60, fill=1)

    pdf.setFont("Helvetica-Bold", 20)
    pdf.setFillColor(colors.white)
    pdf.drawString(40, altura - 40, "Relatório Consolidado")

    pdf.setFillColor(colors.black)
    pdf.line(40, altura - 70, largura - 40, altura - 70)

    y = altura - 100

    # Filtros
    pdf.setFont("Helvetica", 10)
    pdf.setFillColorRGB(0.2, 0.2, 0.2)

    pdf.drawString(40, y, f"Tipo: {tipo_data.upper()} | Ano: {ano} | Mês: {mes}")
    y -= 13
    pdf.drawString(40, y, f"Período: {data_de or '-'} até {data_ate or '-'}")
    y -= 13
    pdf.drawString(40, y, f"Evento: {evento or 'Todos'} | Agenda: {agenda or 'Todas'} | Grupo: {grupo or 'Todos'}")
    y -= 25

    # -----------------------------
    # TABELA CARDS
    # -----------------------------
    cards = dados["cards"]
    tabela_cards = [
        ["Agendas x Presenças", "Valor"],
        ["Total de agendas", cards["total_agendas"]],
        ["Total de presenças", cards["total_presencas"]],
    ]

    tbl = Table(tabela_cards, colWidths=[230, 120])
    tbl.setStyle(TABLE_STYLE)
    tbl.wrapOn(pdf, 40, y)
    tbl.drawOn(pdf, 40, y - (len(tabela_cards) * 14))

    y -= (len(tabela_cards) * 14) + 30

    # -----------------------------
    # PARTICIPANTES POR GRUPO
    # -----------------------------
    pdf.setFillColorRGB(0.8, 0.8, 0.8)
    pdf.rect(40, y - 5, 200, 1, fill=1, stroke=0)

    y -= 20

    tabela_grupo = [["Grupo", "Qtde"]]
    for item in dados["series"]["participantes_grupo"]:
        tabela_grupo.append([item["grupo"], item["qtd"]])

    tbl = Table(tabela_grupo, colWidths=[250, 100])
    tbl.setStyle(TABLE_STYLE)
    tbl.wrapOn(pdf, 40, y)
    tbl.drawOn(pdf, 40, y - (len(tabela_grupo) * 14))

    y -= (len(tabela_grupo) * 14) + 30

    # -----------------------------
    # CREDENCIAIS
    # -----------------------------
    pdf.setFont("Helvetica-Bold", 12)
    pdf.setFillColorRGB(0.15, 0.15, 0.15)
    pdf.drawString(40, y, "Credenciais")
    y -= 20

    cred = dados["series"]["credencial"]
    cred_dict = {c["tipo"]: c["qtd"] for c in cred}

    tabela_cred = [
        ["Credencial", "Qtde"],
        ["PG", cred_dict.get("PG", 0)],
        ["CO", cred_dict.get("CO", 0)],
        ["DC", cred_dict.get("DC", 0)],
        ["OUTROS", cred_dict.get("OUTROS", 0)],
    ]

    tbl = Table(tabela_cred, colWidths=[250, 100])
    tbl.setStyle(TABLE_STYLE)
    tbl.wrapOn(pdf, 40, y)
    tbl.drawOn(pdf, 40, y - (len(tabela_cred) * 14))

    y -= (len(tabela_cred) * 14) + 30

    # -----------------------------
    # PCG
    # -----------------------------   
    y -= 12

    tabela_pcg = [["PCG", "Qtde"]]
    for p in dados["series"]["pcg"]:
        tabela_pcg.append([p["pcg"], p["qtd"]])

    tbl = Table(tabela_pcg, colWidths=[250, 100])
    tbl.setStyle(TABLE_STYLE)
    tbl.wrapOn(pdf, 40, y)
    tbl.drawOn(pdf, 40, y - (len(tabela_pcg) * 14))

    # rodapé da página 1
    desenhar_rodape(pdf, largura, usuario_nome)

    pdf.showPage()
    pdf.save()

    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name="relatorio.pdf",
        mimetype="application/pdf"
    )

@app.route("/painel")
def painel():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    usuario_tipo = session["usuario_tipo"]
    parceiro_id  = session["parceiro_id"]

    conn = get_db()
    try:
        mes_atual = datetime.now().strftime("%Y-%m")

        # =====================================================
        # PARTICIPANTES
        # =====================================================
        if usuario_tipo == "Administrador":
            total_participantes = conn.execute(
                "SELECT COUNT(*) AS c FROM participantes"
            ).fetchone()["c"]

            total_ativos = conn.execute(
                "SELECT COUNT(*) AS c FROM participantes WHERE status = 'Ativo'"
            ).fetchone()["c"]

            total_inativos = conn.execute(
                "SELECT COUNT(*) AS c FROM participantes WHERE status = 'Inativo'"
            ).fetchone()["c"]
        else:
            total_participantes = conn.execute(
                "SELECT COUNT(*) AS c FROM participantes WHERE parceiro_id = ?",
                (parceiro_id,)
            ).fetchone()["c"]

            total_ativos = conn.execute(
                "SELECT COUNT(*) AS c FROM participantes WHERE parceiro_id = ? AND status = 'Ativo'",
                (parceiro_id,)
            ).fetchone()["c"]

            total_inativos = conn.execute(
                "SELECT COUNT(*) AS c FROM participantes WHERE parceiro_id = ? AND status = 'Inativo'",
                (parceiro_id,)
            ).fetchone()["c"]

        # =====================================================
        # EVENTOS
        # =====================================================
        if usuario_tipo == "Administrador":
            eventos = conn.execute("""
                SELECT id, nome 
                FROM eventos
                ORDER BY nome
            """).fetchall()
        else:
            eventos = conn.execute("""
                SELECT id, nome 
                FROM eventos
                WHERE parceiro_id = ?
                ORDER BY nome
            """, (parceiro_id,)).fetchall()

        return render_template(
            "painel.html",
            mes_atual=mes_atual,
            eventos=eventos,
            total_participantes=total_participantes,
            ativos=total_ativos,
            inativos=total_inativos
        )

    finally:
        conn.close()

# ++++++++++ Rota do Ranking ++++++++++
@app.route("/ranking")
def ranking():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    try:
        usuario_tipo = session["usuario_tipo"]
        parceiro_id  = session["parceiro_id"]

        # ==========================
        # PARÂMETROS
        # ==========================
        mes = request.args.get("mes") or datetime.now().strftime("%Y-%m")
        evento_id = request.args.get("evento")
        agenda_id = request.args.get("agenda")
        grupo_id  = request.args.get("grupo")
        pcg_filtro = request.args.get("pcg")

        def to_int(v):
            try:
                return int(v)
            except:
                return None

        evento_id = to_int(evento_id)
        agenda_id = to_int(agenda_id)
        grupo_id  = to_int(grupo_id)

        # ==========================
        # VALIDAR EVENTO
        # ==========================
        if evento_id:
            if usuario_tipo == "Administrador":
                e = conn.execute(
                    "SELECT id FROM eventos WHERE id=%s",
                    (evento_id,)
                ).fetchone()
            else:
                e = conn.execute(
                    "SELECT id FROM eventos WHERE id=%s AND parceiro_id=%s",
                    (evento_id, parceiro_id)
                ).fetchone()
            if not e:
                evento_id = None

        # ==========================
        # VALIDAR AGENDA
        # ==========================
        if agenda_id:
            if usuario_tipo == "Administrador":
                a = conn.execute(
                    "SELECT id, evento_id FROM agendas_evento WHERE id=%s",
                    (agenda_id,)
                ).fetchone()
            else:
                a = conn.execute(
                    "SELECT id, evento_id FROM agendas_evento WHERE id=%s AND parceiro_id=%s",
                    (agenda_id, parceiro_id)
                ).fetchone()

            if not a or (evento_id and a["evento_id"] != evento_id):
                agenda_id = None

        # ==========================
        # VALIDAR GRUPO
        # ==========================
        if grupo_id:
            if usuario_tipo == "Administrador":
                g = conn.execute(
                    "SELECT id, agenda_id FROM agendas_grupos WHERE id=%s",
                    (grupo_id,)
                ).fetchone()
            else:
                g = conn.execute(
                    "SELECT id, agenda_id FROM agendas_grupos WHERE id=%s AND parceiro_id=%s",
                    (grupo_id, parceiro_id)
                ).fetchone()

            if not g or (agenda_id and g["agenda_id"] != agenda_id):
                grupo_id = None

        # ==========================
        # COMBOS
        # ==========================
        if usuario_tipo == "Administrador":
            eventos = conn.execute(
                "SELECT id, nome FROM eventos ORDER BY nome"
            ).fetchall()
        else:
            eventos = conn.execute(
                "SELECT id, nome FROM eventos WHERE parceiro_id=? ORDER BY nome",
                (parceiro_id,)
            ).fetchall()

        agendas = []
        if evento_id:
            agendas = conn.execute(
                "SELECT id, nome_agenda FROM agendas_evento WHERE evento_id=? ORDER BY nome_agenda",
                (evento_id,)
            ).fetchall()

        grupos = []
        if agenda_id:
            grupos = conn.execute(
                "SELECT id, nome FROM agendas_grupos WHERE agenda_id=? ORDER BY nome",
                (agenda_id,)
            ).fetchall()

        # ==========================
        # PARTICIPANTES ENVOLVIDOS
        # ==========================
        sql_part = """
            SELECT DISTINCT p.id, p.nome, p.grupo, p.pcg
            FROM participantes p
            JOIN agendas_grupos_participantes agp ON agp.participante_id = p.id
            JOIN agendas_grupos g ON g.id = agp.grupo_id
            JOIN agendas_evento a ON a.id = g.agenda_id
            WHERE 1=1
        """
        params_part = []

        if usuario_tipo != "Administrador":
            sql_part += " AND a.parceiro_id = %s"
            params_part.append(parceiro_id)

        if evento_id:
            sql_part += " AND a.evento_id = %s"
            params_part.append(evento_id)

        if agenda_id:
            sql_part += " AND g.agenda_id = %s"
            params_part.append(agenda_id)

        if grupo_id:
            sql_part += " AND g.id = %s"
            params_part.append(grupo_id)

        if pcg_filtro:
            sql_part += " AND p.pcg = %s"
            params_part.append(pcg_filtro)

        participantes_raw = conn.execute(sql_part, params_part).fetchall()

        ranking_lista = []

        # ==========================
        # LOOP DE CÁLCULO
        # ==========================
        for p in participantes_raw:
            pid = p["id"]

            total_pres = conn.execute("""
                SELECT COUNT(*) AS c
                FROM frequencia_diaria
                WHERE participante_id = ?
                  AND presente = 1
                  AND substr(data, 1, 7) = ?
            """, (pid, mes)).fetchone()["c"] or 0

            sql_dias = """
                SELECT COUNT(DISTINCT f.data) AS c
                FROM frequencia_diaria f
                JOIN agendas_grupos g ON g.id = f.grupo_id
                JOIN agendas_evento a ON a.id = g.agenda_id
                WHERE substr(f.data, 1, 7) = ?
            """
            params_dias = [mes]

            if usuario_tipo != "Administrador":
                sql_dias += " AND a.parceiro_id = %s"
                params_dias.append(parceiro_id)

            if evento_id:
                sql_dias += " AND a.evento_id = %s"
                params_dias.append(evento_id)

            if agenda_id:
                sql_dias += " AND g.agenda_id = %s"
                params_dias.append(agenda_id)

            if grupo_id:
                sql_dias += " AND g.id = %s"
                params_dias.append(grupo_id)

            total_dias = conn.execute(sql_dias, params_dias).fetchone()["c"] or 0

            percentual = round((total_pres / total_dias) * 100, 1) if total_dias > 0 else 0

            ranking_lista.append({
                "nome": p["nome"],
                "grupo": p["grupo"],
                "pcg": p["pcg"],
                "presencas": total_pres,
                "percentual": percentual
            })

        if not ranking_lista:
            ranking_lista = [{
                "nome": "Nenhum dado disponível",
                "grupo": "-",
                "pcg": "-",
                "presencas": 0,
                "percentual": 0
            }]

        ranking_sorted = sorted(
            ranking_lista,
            key=lambda x: x["presencas"],
            reverse=True
        )

        top5 = ranking_sorted[:5]
        bottom5 = sorted(ranking_lista, key=lambda x: x["presencas"])[:5]

        return render_template(
            "ranking.html",
            mes=mes,
            eventos=eventos,
            agendas=agendas,
            grupos=grupos,
            evento_id=evento_id,
            agenda_id=agenda_id,
            grupo_id=grupo_id,
            pcg_filtro=pcg_filtro,
            top10=top5,
            bottom10=bottom5,
            ranking=ranking_sorted
        )

    finally:
        conn.close()

@app.route("/parceiros")
def parceiros():
    if session.get("usuario_tipo") != "Administrador":
        return redirect(url_for("home"))

    conn = get_db()
    try:
        parceiros = conn.execute(
            "SELECT * FROM parceiros ORDER BY id DESC"
        ).fetchall()

        return render_template(
            "parceiros.html",
            parceiros=parceiros
        )
    finally:
        conn.close()

@app.route("/parceiros/novo", methods=["POST"])
def parceiros_novo():
    if session.get("usuario_tipo") != "Administrador":
        return redirect(url_for("home"))

    nome = request.form["nome"].strip()
    cnpj = request.form.get("cnpj", "").strip().replace(".", "").replace("/", "").replace("-", "")
    email = request.form.get("email", "").strip().lower()
    telefone = request.form.get("telefone", "").strip()

    if not nome:
        flash("Informe o nome do parceiro.", "parceiro_error")
        return redirect(url_for("parceiros"))

    if not email:
        flash("Informe o e-mail do parceiro (será usado no usuário Master).", "parceiro_error")
        return redirect(url_for("parceiros"))

    conn = get_db()
    try:
        # 🔍 Verificar se já existe usuário com esse e-mail
        existe = conn.execute(
            "SELECT id FROM usuarios WHERE email = %s",
            (email,)
        ).fetchone()

        if existe:
            flash("Já existe um usuário cadastrado com este e-mail.", "parceiro_error")
            return redirect(url_for("parceiros"))

        # ==========================
        # INSERIR PARCEIRO
        # ==========================
        cursor = conn.execute("""
            INSERT INTO parceiros (nome, cnpj, email, telefone, status)
            VALUES (%s, %s, %s, %s, %s)
        """, (nome, cnpj or None, email, telefone or None, "Ativo"))

        parceiro_id = cursor.lastrowid

        # ==========================
        # CRIAR USUÁRIO MASTER
        # ==========================
        senha_hash = generate_password_hash("123456")

        conn.execute("""
            INSERT INTO usuarios (nome, email, senha_hash, tipo, status, parceiro_id)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (f"Admin {nome}", email, senha_hash, "Master", "Ativo", parceiro_id))

        conn.commit()

        flash("Parceiro criado com sucesso! Usuário Master criado com senha padrão.", "success")
        return redirect(url_for("parceiros"))

    finally:
        conn.close()

@app.route("/parceiros/editar/<int:id>", methods=["POST"])
def parceiros_editar(id):
    if session.get("usuario_tipo") != "Administrador":
        return redirect(url_for("home"))

    nome = request.form.get("nome", "").strip()
    cnpj = request.form.get("cnpj", "").strip().replace(".", "").replace("/", "").replace("-", "")
    email = request.form.get("email", "").strip().lower()
    telefone = request.form.get("telefone", "").strip()
    status = request.form.get("status", "Ativo")

    if not nome:
        flash("O nome do parceiro é obrigatório.", "parceiro_error")
        return redirect(url_for("parceiros"))

    if status not in ["Ativo", "Inativo"]:
        status = "Ativo"

    conn = get_db()
    try:
        # ==========================
        # VERIFICAR SE PARCEIRO EXISTE
        # ==========================
        parceiro = conn.execute(
            "SELECT id FROM parceiros WHERE id = %s",
            (id,)
        ).fetchone()

        if not parceiro:
            flash("Parceiro não encontrado.", "parceiro_error")
            return redirect(url_for("parceiros"))

        # ==========================
        # EVITAR E-MAIL DUPLICADO
        # ==========================
        if email:
            existe = conn.execute("""
                SELECT id 
                FROM parceiros 
                WHERE email = %s AND id <> %s
            """, (email, id)).fetchone()

            if existe:
                flash("Já existe outro parceiro com este e-mail.", "parceiro_error")
                return redirect(url_for("parceiros"))

        # ==========================
        # UPDATE FINAL (MYSQL)
        # ==========================
        conn.execute("""
            UPDATE parceiros
               SET nome = %s,
                   cnpj = %s,
                   email = %s,
                   telefone = %s,
                   status = %s
             WHERE id = %s
        """, (
            nome,
            cnpj or None,
            email or None,
            telefone or None,
            status,
            id
        ))

        conn.commit()
        flash("Parceiro atualizado com sucesso!", "success")
        return redirect(url_for("parceiros"))

    finally:
        conn.close()

@app.route("/parceiros/inativar/<int:id>")
def parceiros_inativar(id):
    if session.get("usuario_tipo") != "Administrador":
        return redirect(url_for("home"))

    conn = get_db()
    try:
        # ==========================
        # VERIFICAR SE PARCEIRO EXISTE
        # ==========================
        parceiro = conn.execute(
            "SELECT status FROM parceiros WHERE id = %s",
            (id,)
        ).fetchone()

        if not parceiro:
            flash("Parceiro não encontrado.", "parceiro_error")
            return redirect(url_for("parceiros"))

        # ==========================
        # EVITAR REPROCESSAMENTO
        # ==========================
        if parceiro["status"] == "Inativo":
            flash("Este parceiro já está inativo.", "warning")
            return redirect(url_for("parceiros"))

        # ==========================
        # INATIVAR PARCEIRO
        # ==========================
        conn.execute(
            "UPDATE parceiros SET status = 'Inativo' WHERE id = %s",
            (id,)
        )

        # ==========================
        # INATIVAR USUÁRIOS DO PARCEIRO
        # ==========================
        conn.execute(
            "UPDATE usuarios SET status = 'Inativo' WHERE parceiro_id = %s",
            (id,)
        )

        conn.commit()

        flash("Parceiro e usuários inativados com sucesso!", "success")
        return redirect(url_for("parceiros"))

    finally:
        conn.close()

@app.route("/parceiros/ativar/<int:id>")
def parceiros_ativar(id):
    if session.get("usuario_tipo") != "Administrador":
        return redirect(url_for("home"))

    conn = get_db()
    try:
        # ==========================
        # VERIFICAR SE PARCEIRO EXISTE
        # ==========================
        parceiro = conn.execute(
            "SELECT status FROM parceiros WHERE id = %s",
            (id,)
        ).fetchone()

        if not parceiro:
            flash("Parceiro não encontrado.", "parceiro_error")
            return redirect(url_for("parceiros"))

        # ==========================
        # EVITAR REPROCESSAMENTO
        # ==========================
        if parceiro["status"] == "Ativo":
            flash("Este parceiro já está ativo.", "warning")
            return redirect(url_for("parceiros"))

        # ==========================
        # ATIVAR PARCEIRO
        # ==========================
        conn.execute(
            "UPDATE parceiros SET status = 'Ativo' WHERE id = %s",
            (id,)
        )

        conn.commit()

        flash(
            "Parceiro ativado com sucesso. Os usuários permanecem inativos.",
            "success"
        )
        return redirect(url_for("parceiros"))

    finally:
        conn.close()

@app.route("/parceiros/excluir/<int:id>")
def parceiros_excluir(id):
    if session.get("usuario_tipo") != "Administrador":
        return redirect(url_for("home"))

    conn = get_db()
    try:
        parceiro = conn.execute(
            "SELECT status FROM parceiros WHERE id = %s",
            (id,)
        ).fetchone()

        if not parceiro:
            flash("Parceiro não encontrado.", "parceiro_error")
            return redirect(url_for("parceiros"))

        if parceiro["status"] == "Excluído":
            flash("Este parceiro já foi excluído.", "warning")
            return redirect(url_for("parceiros"))

        # 🔥 Exclusão lógica
        conn.execute(
            "UPDATE parceiros SET status = 'Excluído' WHERE id = %s",
            (id,)
        )

        # 🔐 Opcional: bloquear usuários automaticamente
        conn.execute(
            "UPDATE usuarios SET status = 'Inativo' WHERE parceiro_id = %s",
            (id,)
        )

        conn.commit()

        flash(
            "Parceiro excluído logicamente. Dados preservados.",
            "success"
        )
        return redirect(url_for("parceiros"))

    finally:
        conn.close()

from flask import request

def registrar_acao(
    parceiro_id,
    usuario_id,
    usuario_nome,
    acao,
    detalhes="",
    ip=None,
    user_agent=None
):
    """
    Registra ações importantes do sistema para auditoria.
    Nunca deve quebrar o fluxo principal.
    """

    try:
        conn = get_db()

        ip_final = ip or request.remote_addr
        ua_final = user_agent or request.headers.get("User-Agent", "")

        conn.execute("""
            INSERT INTO auditoria (
                parceiro_id,
                usuario_id,
                usuario_nome,
                acao,
                detalhes,
                ip,
                user_agent,
                criado_em
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        """, (
            parceiro_id,
            usuario_id,
            usuario_nome,
            acao,
            detalhes,
            ip_final,
            ua_final
        ))

        conn.commit()

    except Exception as e:
        # ⚠️ Nunca derruba o sistema por falha de auditoria
        print(f"[AUDITORIA][ERRO] {e}")

    finally:
        try:
            conn.close()
        except:
            pass

@app.route("/auditoria")
def auditoria():
    if session.get("usuario_tipo") != "Administrador":
        flash("Acesso negado.", "danger")
        return redirect(url_for("home"))

    conn = get_db()

    parceiros = conn.execute("""
        SELECT id, nome, cnpj
        FROM parceiros
        ORDER BY nome
    """).fetchall()

    conn.close()

    return render_template("auditoria.html", parceiros=parceiros)

@app.route("/auditoria/<int:parceiro_id>")
def auditoria_parceiro(parceiro_id):
    if session.get("usuario_tipo") != "Administrador":
        flash("Acesso negado.", "danger")
        return redirect(url_for("home"))

    conn = get_db()

    parceiro = conn.execute("""
        SELECT id, nome, cnpj
        FROM parceiros
        WHERE id = %s
    """, (parceiro_id,)).fetchone()

    if not parceiro:
        conn.close()
        flash("Parceiro não encontrado.", "danger")
        return redirect(url_for("auditoria"))

    historico = conn.execute("""
        SELECT *
        FROM auditoria
        WHERE parceiro_id = %s
        ORDER BY data_hora DESC
        LIMIT 300
    """, (parceiro_id,)).fetchall()

    conn.close()

    return render_template(
        "auditoria_detalhes.html",
        parceiro=parceiro,
        historico=historico
    )

@app.context_processor
def inject_notificacoes():
    if "usuario_id" not in session:
        return {
            "notificacoes": [],
            "notificacoes_nao_lidas": 0
        }

    conn = get_db()
    parceiro_id = session.get("parceiro_id")

    notificacoes = conn.execute("""
        SELECT id, mensagem, link
        FROM notificacoes
        WHERE parceiro_id = %s AND lida = 0
        ORDER BY criada_em DESC
        LIMIT 5
    """, (parceiro_id,)).fetchall()

    conn.close()

    return {
        "notificacoes": notificacoes,
        "notificacoes_nao_lidas": len(notificacoes)
    }
@app.route("/notificacoes/abrir/<int:id>")
def abrir_notificacao(id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    parceiro_id = session["parceiro_id"]
    conn = get_db()

    notif = conn.execute("""
        SELECT id, link
        FROM notificacoes
        WHERE id = %s AND parceiro_id = %s
    """, (id, parceiro_id)).fetchone()

    if not notif:
        conn.close()
        return redirect(url_for("home"))

    conn.execute("""
        UPDATE notificacoes
        SET lida = 1
        WHERE id = %s AND parceiro_id = %s
    """, (id, parceiro_id))

    conn.commit()
    conn.close()

    link = (notif.get("link") or "").strip()

    # 🔐 segurança: só permite URL interna
    if link and url_parse(link).netloc == "":
        return redirect(link)

    return redirect(url_for("home"))

def gerar_notificacoes_aniversario(conn):
    aniversariantes = conn.execute("""
        SELECT id, nome, idade, parceiro_id
        FROM participantes
        WHERE status = 'Ativo'
          AND data_nascimento IS NOT NULL
          AND DAY(data_nascimento) = DAY(CURDATE())
          AND MONTH(data_nascimento) = MONTH(CURDATE())
    """).fetchall()

    for p in aniversariantes:
        ja_existe = conn.execute("""
            SELECT 1
            FROM notificacoes
            WHERE tipo = 'aniversario'
              AND parceiro_id = %s
              AND mensagem LIKE %s
              AND DATE(criada_em) = CURDATE()
        """, (p["parceiro_id"], f"%{p['nome']}%")).fetchone()

        if ja_existe:
            continue

        conn.execute("""
            INSERT INTO notificacoes (parceiro_id, tipo, mensagem, link)
            VALUES (%s, %s, %s, %s)
        """, (
            p["parceiro_id"],
            "aniversario",
            f"🎂 Hoje é aniversário de {p['idade']} anos de {p['nome']}!",
            url_for("participantes", _external=False)
        ))

    conn.commit()

def limpar_notificacoes_antigas(conn):
    conn.execute("""
        DELETE FROM notificacoes
        WHERE criada_em < NOW() - INTERVAL 7 DAY
    """)
    conn.commit()

@app.route("/notificacoes")
def notificacoes_historico():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    parceiro_id = session["parceiro_id"]
    conn = get_db()

    notificacoes = conn.execute("""
        SELECT id, tipo, mensagem, lida, criada_em
        FROM notificacoes
        WHERE parceiro_id = %s
          AND criada_em >= NOW() - INTERVAL 7 DAY
        ORDER BY criada_em DESC
    """, (parceiro_id,)).fetchall()

    conn.close()

    return render_template(
        "notificacoes.html",
        notificacoes=notificacoes
    )

# ==========================
# ENTRYPOINT (rodar local / empacotar)
# ==========================
def _start_server():
    # garante schema criado
    try:
        init_db()
    except Exception as e:
        print("ERRO ao inicializar banco SQLite:", e)

    host = os.getenv("HOST", "0.0.0.0")
    try:
        port = int(os.getenv("PORT", "5000"))
    except Exception:
        port = 5000

    env = (os.getenv("APP_ENV", "dev") or "dev").lower()
    debug = env in ("dev", "development")

    # Preferir waitress (mais estável em EXE). Se não existir, usa Flask dev server.
    use_waitress = os.getenv("USE_WAITRESS", "1") == "1"
    if use_waitress:
        try:
            from waitress import serve
            print(f"SyncFlow (SQLite) rodando em http://127.0.0.1:{port}")
            serve(app, host=host, port=port)
            return
        except Exception:
            pass

    print(f"SyncFlow (SQLite) rodando em http://127.0.0.1:{port}")
    app.run(host=host, port=port, debug=debug, use_reloader=False)

if __name__ == "__main__":
    _start_server()
