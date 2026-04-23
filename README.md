# SyncFlow

Aplicacao Flask com banco SQLite para gestao de parceiros, usuarios, eventos, agendas, participantes, frequencias e auditoria.

## O que precisa estar no GitHub

Este repositorio agora guarda o necessario para continuar o desenvolvimento em outro notebook:

- codigo-fonte da aplicacao;
- dependencias em `requirements.txt`;
- variaveis de ambiente de referencia em `.env.example`;
- schema do banco em `schema.sql`;
- instrucoes de setup neste `README.md`.

Arquivos locais e gerados nao devem ir para o Git:

- `venv/`;
- `output/` e outros artefatos de build;
- `data/*.db` e arquivos temporarios do SQLite;
- arquivos compactados como `.rar` e `.zip`.

## Requisitos

- Python 3.13
- `pip`

## Como subir no novo notebook

1. Clone o repositorio.
2. Crie e ative um ambiente virtual.
3. Instale as dependencias com `pip install -r requirements.txt`.
4. Copie `.env.example` para `.env` ou configure as variaveis no sistema.
5. Rode `python SyncFlow.py`.

Exemplo no Windows PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python SyncFlow.py
```

Por padrao, a aplicacao sobe em `http://127.0.0.1:5000`.

O `SyncFlow.py` carrega automaticamente um arquivo `.env` na raiz do projeto.

## Banco de dados

- O banco padrao fica em `data/syncflow.db`.
- O schema e criado automaticamente na inicializacao por `init_db()` em `SyncFlow.py`.
- O arquivo `schema.sql` fica no repositorio como referencia e apoio para recuperacao.
- O banco local nao deve ser versionado.

### Quando copiar o arquivo do banco

Para continuar apenas o desenvolvimento, nao e necessario levar o arquivo `data/syncflow.db`, porque a aplicacao recria a estrutura sozinha.

Se voce quiser levar tambem os dados atuais do ambiente local, copie manualmente o arquivo `data/syncflow.db` do notebook antigo para o novo, no mesmo caminho. Esse arquivo deve continuar fora do GitHub.

### Primeiro acesso

Se o banco estiver vazio, o sistema abre o fluxo de setup para criar o primeiro usuario administrador.

## Variaveis de ambiente

Variaveis reconhecidas pela aplicacao:

- `APP_ENV`: `dev`, `development`, `prod` ou `production`.
- `SECRET_KEY`: chave da sessao Flask. Troque em qualquer ambiente real.
- `HOST`: host do servidor.
- `PORT`: porta do servidor.
- `USE_WAITRESS`: usa `waitress` quando igual a `1`.
- `SQLITE_PATH`: caminho alternativo para o arquivo SQLite.
- `SMTP_HOST`: host SMTP.
- `SMTP_PORT`: porta SMTP.
- `SMTP_USER`: usuario do email para recuperacao de senha.
- `SMTP_PASS`: senha do email para recuperacao de senha.

## Observacoes para continuidade

- O repositorio usa SQLite como banco local principal.
- O arquivo principal da aplicacao e `SyncFlow.py`.
- Templates ficam em `templates/` e arquivos estaticos em `static/`.
- O envio de email depende de `SMTP_USER` e `SMTP_PASS`; sem isso, a recuperacao de senha nao funciona.
