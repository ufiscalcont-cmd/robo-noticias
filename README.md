# 📰 Notícias uFiscal

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
   - `EMAIL_DESTINO` — quem recebe. Vários e-mails separados por vírgula, ponto e vírgula ou um por linha.
     Todos recebem em **cópia oculta (Cco)**: ninguém vê os outros destinatários.
   - `EMAIL_ADMIN` (opcional) — quem recebe os avisos de falha. Padrão: o próprio remetente.

   **WhatsApp** — escolha um provedor:
   - `WHATSAPP_PROVEDOR` = `callmebot`, `zapi` ou `evolution`
   - `WHATSAPP_NUMERO` — ex.: `5579999999999`
   - mais as chaves do provedor escolhido (veja abaixo)

3. Em **Settings → Actions → General → Workflow permissions**, marque **Read and write permissions** (para salvar o registro de envio).
4. Teste agora: **Actions → Notícias uFiscal → Run workflow**.

Pronto. A partir daí roda sozinho às 08h e 20h.

## Provedores de WhatsApp

| Provedor | Custo | Quando usar |
|---|---|---|
| **CallMeBot** | Grátis | Uso pessoal, só para o seu número. Ativação: adicione **+34 644 51 95 23** aos contatos, envie *"I allow callmebot to send me messages"* e ele responde com sua `CALLMEBOT_APIKEY`. Mensagens longas são divididas em partes. |
| **Z-API** | Pago (mensal) | Serviço brasileiro estável. Conecta seu WhatsApp via QR Code. Secrets: `ZAPI_INSTANCIA`, `ZAPI_TOKEN`, `ZAPI_CLIENT_TOKEN`. |
| **Evolution API** | Grátis (auto-hospedado) | Se você tem servidor próprio. Secrets: `EVOLUTION_URL`, `EVOLUTION_INSTANCIA`, `EVOLUTION_APIKEY`. |

Para máxima confiabilidade no WhatsApp, prefira Z-API ou Evolution; o CallMeBot é gratuito mas tem fila e limite de uso.

## Panorama da edição (resumo)

Antes da lista de notícias vem um resumo geral, gratuito:

1. **Com IA gratuita (Google Gemini, plano gratuito)** — texto jornalístico redigido a partir das manchetes, na norma-padrão, com atribuição às fontes. Crie uma chave grátis em aistudio.google.com (sem cartão) e cadastre o secret `GEMINI_API_KEY`. Não ative faturamento no projeto do Google: isso desliga o plano gratuito.
2. **Sem IA (plano B automático)** — se a IA estiver indisponível ou no limite diário, o robô monta o resumo com as manchetes mais repercutidas, citadas entre aspas e atribuídas aos veículos.

Nos dois casos, notícias com alerta de fake news ficam de fora, e as **Referências** seguem a ABNT NBR 6023:2018, geradas pelo código a partir dos dados reais de cada notícia.

Variáveis opcionais: `RESUMO=sem_ia` (nunca usa IA) ou `RESUMO=nao` (desliga); `RESUMO_MODELO` para trocar o modelo (padrão: gemini-flash-latest).

## Sem notícias repetidas entre edições

O robô guarda em `data/historico.json` as notícias enviadas nos últimos 15 dias. A cada edição:
- mesma notícia (mesmo link, mesmo título ou título praticamente igual) → **não é enviada de novo**;
- mesmo assunto com fato novo (aprovação, adiamento, decisão, prisão, números novos…) → entra com o selo **🔄 ATUALIZAÇÃO** e a indicação da edição em que o assunto saiu antes.

## Alerta de possível fake news

Cada notícia recebe uma nota de risco. As de risco alto ou médio chegam marcadas:

| Selo | Significado |
|---|---|
| 🔴 **POSSÍVEL FAKE NEWS** | vários sinais de risco juntos |
| 🟡 **ATENÇÃO** | um ou dois sinais — vale confirmar |
| 🔎 **CHECAGEM** | a própria notícia é de uma agência de checagem |

Os sinais analisados (`noticias_bot/credibilidade.py`):

- **Fonte** — veículo reconhecido, desconhecido ou da sua lista de suspeitos.
- **Título** — termos apelativos ("URGENTE", "compartilhe antes que apaguem"…), excesso de maiúsculas e de "!!!".
- **Confirmação cruzada** — se outros veículos noticiaram o mesmo no período.
- **Agências de checagem** — compara com as checagens dos últimos 7 dias (Aos Fatos, Lupa, Comprova, Boatos.org, E-farsas, AFP Checamos, Fato ou Fake, Estadão Verifica) e manda o link da checagem.

O motivo do alerta vem escrito logo abaixo da manchete. É uma **triagem automática, não um veredito**: confirme antes de compartilhar.

Ajuste as listas em `credibilidade.json`:
- `fontes_confiaveis` — adicione portais regionais que você conhece (reduz alertas 🟡 em notícias locais).
- `fontes_suspeitas` — sites que você quer sempre marcados em 🔴.
- `termos_sensacionalistas` — expressões que acendem o alerta.

Para desligar a análise, crie a variável `ALERTA_FAKE_NEWS=false`.

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
  credibilidade.py  análise de risco de fake news
  coletor.py     download (com tentativas), leitura RSS/Atom, filtro por horário, deduplicação
  formatador.py  texto do WhatsApp (com divisão em partes) e HTML do e-mail
  envio.py       SMTP e provedores de WhatsApp
  __main__.py    orquestração, registro de envio, alertas
topicos.json     tópicos e fontes
credibilidade.json  listas de fontes confiáveis/suspeitas, termos e agências de checagem
data/estado.json registro de edições enviadas
data/historico.json notícias já enviadas (evita repetição)
.github/workflows/noticias.yml   agendamento com reservas
deploy/          alternativa systemd
tests/           testes automatizados
```

## ⚖️ Jurídico uFiscal (segundo robô, mesmo motor)

Boletim só com notícias jurídicas para advocacia **tributária, trabalhista, previdenciária, administrativa (licitações) e empresarial**, mais um tópico de **Tribunais, Leis e Prática** (repercussão geral, repetitivos, súmulas, leis e MPs, prazos, PJe, OAB/CNJ). Sai às **08h07** e **20h07**, com as mesmas reservas e garantias do Notícias uFiscal.

- **Configuração:** `perfis/juridico.json` (tópicos, buscas, termos exigidos no título de cada área, filtros e o texto-guia do resumo).
- **Destinatários:** secret `EMAIL_DESTINO_JURIDICO` (vários e-mails, todos em cópia oculta). Enquanto ele não existir, o boletim vai só para o administrador (`EMAIL_ADMIN` ou o próprio remetente).
- **Registro de envios:** `data/juridico/`, separado do robô de notícias.
- **Qualidade:** portais jurídicos (Conjur, Migalhas, JOTA, tribunais, gov.br) aparecem primeiro; editais e avisos de licitação publicados em jornais, páginas de arquivo e de autor são descartados; a mesma notícia contada por vários veículos aparece uma vez só.
- **Teste:** Actions → **Jurídico uFiscal** → Run workflow (marque *simular* para não enviar; a prévia fica no ramo `previa-juridico`).
- **Limite do Gmail:** os dois robôs usam o mesmo remetente e somam no limite de ~500 destinatários por dia.
