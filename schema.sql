PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS parceiros (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    cnpj TEXT,
    email TEXT,
    telefone TEXT,
    status TEXT DEFAULT 'Ativo'
);

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

CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    parceiro_id INTEGER NOT NULL,
    criado_em TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(parceiro_id) REFERENCES parceiros(id)
);

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

CREATE TABLE IF NOT EXISTS agendas_grupos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agenda_id INTEGER NOT NULL,
    nome TEXT NOT NULL,
    parceiro_id INTEGER NOT NULL,
    FOREIGN KEY(agenda_id) REFERENCES agendas_evento(id),
    FOREIGN KEY(parceiro_id) REFERENCES parceiros(id)
);

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

CREATE TABLE IF NOT EXISTS agendas_grupos_participantes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grupo_id INTEGER NOT NULL,
    participante_id INTEGER NOT NULL,
    parceiro_id INTEGER NOT NULL,
    FOREIGN KEY(grupo_id) REFERENCES agendas_grupos(id),
    FOREIGN KEY(participante_id) REFERENCES participantes(id),
    FOREIGN KEY(parceiro_id) REFERENCES parceiros(id)
);

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

CREATE TABLE IF NOT EXISTS reset_senha (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL,
    token TEXT NOT NULL,
    expira_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS logs_suporte (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parceiro_id INTEGER,
    usuario_id INTEGER,
    mensagem TEXT,
    criado_em TEXT DEFAULT (datetime('now'))
);
