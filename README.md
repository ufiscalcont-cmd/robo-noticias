# 📰 Robô de Notícias

Coleta as notícias do período, organiza por tópicos e envia por **e-mail** e **WhatsApp** duas vezes por dia (horário de Brasília):

| Envio | Período coberto |
|---|---|
| **08:00** | 20:00 do dia anterior → 08:00 |
| **20:00** | 08:00 → 20:00 |

- Python puro (só biblioteca padrão — nada para instalar, nada que quebre com atualização de pacote).
- Fonte: Google News RSS em português, por tópico e por busca (gratuito, sem chave).
- Notícia repetida em vários portais aparece uma vez só.
- WhatsApp recebe as manchetes resumidas; o e-mail traz a lista completa com links.

## Como ele garante "todos os dias, sem falha"

1. **Execuções de reserva** — além do horário principal, roda de novo 20, 45 e 90 minutos depois.
2. **Registro de envio** (`data/estado.json`) — cada edição é marcada por canal. As reservas só enviam o que ainda não foi enviado: nunca duplica.
3. **Canais independentes** — se o WhatsApp falhar, o e-mail sai mesmo assim (e vice-versa), e a reserva reenvia só o canal que falhou.
4. **Alerta** — se um canal falhar, você recebe um aviso pelo outro, e o GitHub também manda e-mail de "workflow falhou".
5. **Tentativas automáticas** — cada download e cada envio tenta até 4 vezes com espera crescente.
6. **Fonte fora do ar** não derruba o resumo: as demais seguem e o relatório indica a falha.
7. **Atraso tolerado** — se rodar às 20:40, continua cobrindo 08h–20h corretamente.

## Instalação recomendada: GitHub Actions (grátis, roda na nuvem, não depende do seu PC)

1. Crie um repositório **privado** no GitHub e envie esta pasta inteira (incluindo `.github/`).
2. Em **Settings → Secrets and variables → Actions → New repository secret**, cadastre:

   **E-mail (Gmail)**
   - `SMTP_USUARIO` — seu Gmail
   - `SMTP_SENHA` — **senha de app** (Conta Google → Segurança → Verificação em duas etapas → Senhas de app)
   - `EMAIL_DESTINO` — quem recebe (pode ser vários, separados por vírgula)

   **WhatsApp** — escolha um provedor:
   - `WHATSAPP_PROVEDOR` = `callmebot`, `zapi` ou `evolution`
   - `WHATSAPP_NUMERO` — ex.: `5579999999999`
   - mais as chaves do provedor escolhido (veja abaixo)

3. Em **Settings → Actions → General → Workflow permissions**, marque **Read and write permissions** (para salvar o registro de envio).
4. Teste agora: **Actions → Robô de Notícias → Run workflow**.

Pronto. A partir daí roda sozinho às 08h e 20h.

## Provedores de WhatsApp

| Provedor | Custo | Quando usar |
|---|---|---|
| **CallMeBot** | Grátis | Uso pessoal, só para o seu número. Ativação: adicione **+34 644 51 95 23** aos contatos, envie *"I allow callmebot to send me messages"* e ele responde com sua `CALLMEBOT_APIKEY`. Mensagens longas são divididas em partes. |
| **Z-API** | Pago (mensal) | Serviço brasileiro estável. Conecta seu WhatsApp via QR Code. Secrets: `ZAPI_INSTANCIA`, `ZAPI_TOKEN`, `ZAPI_CLIENT_TOKEN`. |
| **Evolution API** | Grátis (auto-hospedado) | Se você tem servidor próprio. Secrets: `EVOLUTION_URL`, `EVOLUTION_INSTANCIA`, `EVOLUTION_APIKEY`. |

Para máxima confiabilidade no WhatsApp, prefira Z-API ou Evolution; o CallMeBot é gratuito mas tem fila e limite de uso.

## Personalizar os tópicos

Edite `topicos.json`. A **ordem** define a exibição e a prioridade (se uma notícia cabe em dois tópicos, fica no primeiro).

```json
{ "nome": "Agronegócio", "emoji": "🌾",
  "fontes": [{ "tipo": "google_busca", "q": "agronegócio OR safra OR \"preço do boi\"" }] }
```

Tipos de fonte: `google_busca` (`q`), `google_topico` (`id`: NATION, WORLD, BUSINESS, TECHNOLOGY, SPORTS, HEALTH, SCIENCE, ENTERTAINMENT), `google_destaques`, `rss` (`url` de qualquer portal).

`max_por_topico_whatsapp` controla quantas manchetes por tópico vão no WhatsApp. Para incluir links no WhatsApp, crie a *variável* (não secret) `WHATSAPP_LINKS=true`.

## Rodar no próprio computador ou servidor

```bash
cp .env.example .env        # preencha
python3 -m noticias_bot --simular   # gera prévias em saida/ sem enviar nada
python3 -m noticias_bot             # envia a edição mais recente que ainda não foi enviada
python3 -m noticias_bot --data 2026-10-28 --edicao 20h --forcar   # reenvia uma edição
python3 -m unittest discover -s tests   # testes
```

Agendamento em servidor Linux (alternativa ao GitHub): copie `deploy/robo-noticias.service` e `.timer` para `/etc/systemd/system/`, ajuste o caminho e rode
`sudo systemctl enable --now robo-noticias.timer`. Com `Persistent=true`, se a máquina estiver desligada no horário, ele envia assim que ligar.

> Rodar num PC pessoal (Agendador de Tarefas do Windows) funciona, mas só envia se o PC estiver ligado — por isso o GitHub Actions é o recomendado.

## Estrutura

```
noticias_bot/
  janela.py      cálculo das janelas 08h–20h / 20h–08h
  coletor.py     download (com tentativas), leitura RSS/Atom, filtro por horário, deduplicação
  formatador.py  texto do WhatsApp (com divisão em partes) e HTML do e-mail
  envio.py       SMTP e provedores de WhatsApp
  __main__.py    orquestração, registro de envio, alertas
topicos.json     tópicos e fontes
data/estado.json registro de edições enviadas
.github/workflows/noticias.yml   agendamento com reservas
deploy/          alternativa systemd
tests/           testes automatizados
```
