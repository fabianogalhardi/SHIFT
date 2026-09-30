# Robô de exames da UTI (eLIS → Notion)

Todo dia às **06:00**, no computador do hospital, o robô:

1. lê no Notion os prompts **IA PARA DIGITAR EXAMES** e **IA UTI PED** e o painel **ROTINAS E CONTROLES** (para tendências);
2. entra no eLIS com seu usuário, procura os pacientes do setor configurado e copia os laudos liberados nas últimas 24 h — **só consulta**, nunca libera, altera ou imprime nada;
3. digita os exames exatamente conforme os prompts (linha de exames, OBS, ALERTA PHOENIX, prioridades 🔴🟠🟡);
4. cria **uma subpágina de RASCUNHO** dentro de ROTINAS E CONTROLES, com os laudos brutos no fim para conferência, e salva também um `.txt` na pasta `saidas` pronto para colar no prontuário.

> **Por que rascunho e não direto no painel?** Seus próprios prompts dizem para atualizar o Notion só com o seu comando e só com os pacientes que você confirmar como ativos. O robô deixa tudo pronto; você revisa e, no chat, diz "manda exames" como sempre.

Como ainda não sabemos o caminho das telas do eLIS, é o Claude quem navega: ele lê cada tela e escolhe onde clicar. Na primeira execução ele anota o caminho que funcionou (`roteiro_elis.txt`) e, nos dias seguintes, vai direto.

---

## Instalação (uma vez só, ~15 min)

### 1. Python
Baixe o Python 3.12 em <https://www.python.org/downloads/> e, na instalação, **marque "Add python.exe to PATH"**.
(Se o computador do hospital bloquear instalações, peça à TI.)

### 2. Chave da API do Claude
Em <https://console.anthropic.com> → *API Keys* → *Create Key*. Copie a chave (`sk-ant-...`).
A API é cobrada à parte da assinatura do Claude (por uso, alguns centavos a poucos reais por dia, dependendo do número de laudos). Cadastre um cartão em *Billing*.

### 3. Token do Notion
1. Acesse <https://www.notion.so/profile/integrations> → *Nova integração* → nome "Robô UTI" → tipo *Interna*. Copie o token (`ntn_...`).
2. No Notion, abra a página **PROMPTS** → menu **•••** → **Conexões** → adicione "Robô UTI".
3. Faça o mesmo na página **ROTINAS E CONTROLES**.

### 4. Copiar a pasta e instalar
1. Copie esta pasta `robo_uti` para o computador (ex.: `C:\robo_uti`). Pelo GitHub: botão **Code → Download ZIP** no branch `claude/automated-uti-exam-access-53ww3z`.
2. Dê dois cliques em **`instalar.bat`**. Ele instala tudo, pede usuário/senha do eLIS, a chave do Claude e o token do Notion (ficam guardados no **Gerenciador de Credenciais do Windows**, não em arquivo) e agenda a tarefa das 06:00.

### 5. Ajustar o setor
Abra `config.ini` no Bloco de Notas e confira a linha `setor =` com o nome exato do setor como aparece no eLIS (ex.: `UTI PEDIÁTRICA` ou `UTI ONCOLÓGICA`).

### 6. Testar
Dê dois cliques em **`testar.bat`**. O navegador abre na tela, você vê o robô navegando, e no fim o texto aparece na pasta `saidas`. **No teste o Notion não é alterado.** Se funcionar, está pronto; amanhã às 6h ele roda sozinho.

---

## No dia a dia

| Arquivo | Para quê |
|---|---|
| `testar.bat` | rodar agora, vendo o navegador, sem mexer no Notion |
| `rodar_robo.bat` | rodar agora de verdade (o mesmo que roda às 6h) |
| `configurar.bat` | trocar senha do eLIS, chave ou token |
| `logs\` | o que o robô fez em cada execução |
| `saidas\` | texto digitado de cada dia |

- **O computador precisa estar ligado e com o Windows logado** às 6h (a tarefa roda na sua sessão).
- Se o eLIS mudar de tela e o robô se perder, apague `roteiro_elis.txt` para ele reaprender.
- Para mudar o horário: *Agendador de Tarefas* do Windows → "Robo UTI - exames".
- Para editar como os exames são digitados, **edite só os prompts no Notion**: o robô lê a versão atual a cada execução.

## Segurança e responsabilidade

- É uma **transcrição feita por IA**: confira cada valor com o laudo original (estão no fim do rascunho) antes de usar em prontuário ou conduta. O rascunho nunca confirma que uma intervenção foi feita.
- Os laudos (dados de pacientes) são enviados à API do Claude para a digitação, assim como já acontece quando você cola no chat. **Confirme com a TI/direção do hospital** se o uso de robôs no eLIS e o envio desses dados são permitidos pela política interna e pela LGPD.
- O robô só lê: ele se recusa a clicar em botões como *Liberar, Excluir, Cancelar, Assinar, Salvar, Gravar, Imprimir*.
- As pastas `saidas` e `logs` contêm dados de pacientes: mantenha-as só nesse computador.
