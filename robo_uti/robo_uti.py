"""Robô diário da UTI: entra no eLIS, lê os exames liberados, digita conforme
o prompt "IA PARA DIGITAR EXAMES" / "IA UTI PED" do Notion e cria um RASCUNHO
dentro de ROTINAS E CONTROLES para o médico revisar.

Uso:
    python robo_uti.py            execução normal (agendada às 6h)
    python robo_uti.py --teste    abre o navegador na tela e NÃO grava no Notion
"""

import argparse
import configparser
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import anthropic

import credenciais
from elis import ELIS
from notion_io import Notion, montar_rascunho

PASTA = Path(__file__).resolve().parent
ROTEIRO = PASTA / "roteiro_elis.txt"
log = logging.getLogger("robo_uti")

BETAS_FALLBACK = ["server-side-fallback-2026-07-01"]

# ---------------------------------------------------------------- navegação

FERRAMENTAS = [
    {"name": "ler_tela", "description":
        "Lê o texto da tela atual do eLIS e lista os elementos clicáveis numerados [n]. "
        "Telas longas vêm em partes; peça parte=2, 3... se precisar.",
     "input_schema": {"type": "object", "properties": {"parte": {"type": "integer"}},
                      "required": ["parte"], "additionalProperties": False}},
    {"name": "clicar", "description": "Clica no elemento [n] da última leitura de tela.",
     "input_schema": {"type": "object", "properties": {"n": {"type": "integer"}},
                      "required": ["n"], "additionalProperties": False}},
    {"name": "digitar", "description":
        "Preenche um campo de busca/filtro [n] (ex.: data, setor, nome). Nunca use para alterar dados.",
     "input_schema": {"type": "object", "properties": {"n": {"type": "integer"}, "texto": {"type": "string"}},
                      "required": ["n", "texto"], "additionalProperties": False}},
    {"name": "selecionar", "description": "Escolhe a opção (pelo texto visível) de uma lista suspensa [n].",
     "input_schema": {"type": "object", "properties": {"n": {"type": "integer"}, "opcao": {"type": "string"}},
                      "required": ["n", "opcao"], "additionalProperties": False}},
    {"name": "voltar", "description": "Volta para a tela anterior do navegador.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "salvar_laudo", "description":
        "Guarda o laudo que está aberto AGORA na tela, copiando o texto original do eLIS. "
        "Chame uma vez para cada laudo/resultado aberto de cada paciente.",
     "input_schema": {"type": "object", "properties": {
         "paciente": {"type": "string", "description": "Nome completo como aparece no eLIS"},
         "descricao": {"type": "string", "description": "Ex.: 'Hemograma + bioquímica 30/09 04:05'"}},
         "required": ["paciente", "descricao"], "additionalProperties": False}},
    {"name": "anotar_roteiro", "description":
        "Grava (substituindo o anterior) um roteiro curto de como chegar aos resultados da UTI "
        "no eLIS, para as próximas execuções serem mais rápidas. Não inclua dados de pacientes.",
     "input_schema": {"type": "object", "properties": {"roteiro": {"type": "string"}},
                      "required": ["roteiro"], "additionalProperties": False}},
]
for f in FERRAMENTAS:
    f["strict"] = True


def executar_ferramenta(elis: ELIS, nome: str, args: dict) -> str:
    if nome == "ler_tela":
        return elis.ler_tela(args.get("parte", 1))
    if nome == "clicar":
        return elis.clicar(args["n"])
    if nome == "digitar":
        return elis.digitar(args["n"], args["texto"])
    if nome == "selecionar":
        return elis.selecionar(args["n"], args["opcao"])
    if nome == "voltar":
        return elis.voltar()
    if nome == "salvar_laudo":
        return elis.salvar_laudo(args["paciente"], args["descricao"])
    if nome == "anotar_roteiro":
        ROTEIRO.write_text(args["roteiro"], encoding="utf-8")
        return "roteiro gravado."
    return f"ferramenta desconhecida: {nome}"


def navegar(cliente, modelo, elis: ELIS, setor: str, desde: datetime, max_passos: int):
    roteiro = ROTEIRO.read_text(encoding="utf-8") if ROTEIRO.exists() else "(ainda não há roteiro)"
    sistema = (
        "Você opera o eLIS (sistema de laboratório do hospital) em modo SOMENTE LEITURA, já logado. "
        "Nunca libere, altere, cancele, imprima ou grave nada no sistema.\n"
        f"Objetivo: encontrar TODOS os pacientes internados no setor '{setor}' e abrir cada "
        f"resultado de exame (laboratório, gasometria, culturas, imagem) liberado desde "
        f"{desde:%d/%m/%Y %H:%M} até agora, chamando salvar_laudo com cada laudo aberto na tela. "
        "Culturas ainda em andamento também interessam (registre-as como estão). "
        "Não salve o mesmo laudo duas vezes. Se não houver exames novos, diga isso.\n"
        "Ao final, grave com anotar_roteiro o caminho que funcionou (menus, filtros, botões) e "
        "responda com um resumo curto: pacientes encontrados e quantos laudos salvou.\n\n"
        f"Roteiro das execuções anteriores:\n{roteiro}"
    )
    mensagens = [{"role": "user", "content": "Comece lendo a tela atual."}]
    for passo in range(max_passos):
        with cliente.beta.messages.stream(
            model=modelo, max_tokens=16000, system=sistema, tools=FERRAMENTAS,
            messages=mensagens, thinking={"type": "adaptive"},
            output_config={"effort": "medium"}, betas=BETAS_FALLBACK,
            extra_body={"fallbacks": "default"},
        ) as stream:
            resp = stream.get_final_message()
        mensagens.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "refusal":
            raise RuntimeError("O Claude recusou a navegação.")
        chamadas = [b for b in resp.content if b.type == "tool_use"]
        if not chamadas:
            resumo = "".join(b.text for b in resp.content if b.type == "text")
            log.info("Navegação concluída: %s", resumo)
            return resumo
        resultados = []
        for c in chamadas:
            try:
                saida = executar_ferramenta(elis, c.name, c.input)
                erro = False
            except Exception as e:  # erros de tela voltam para o Claude tentar outro caminho
                saida, erro = f"erro: {e}", True
            log.info("passo %d: %s %s -> %s", passo, c.name,
                     json.dumps(c.input, ensure_ascii=False)[:120], saida[:80].replace("\n", " "))
            resultados.append({"type": "tool_result", "tool_use_id": c.id,
                               "content": saida, "is_error": erro})
        mensagens.append({"role": "user", "content": resultados})
    log.warning("Limite de %d passos atingido; seguindo com os laudos já salvos.", max_passos)
    return "limite de passos atingido"


# ---------------------------------------------------------------- digitação

ESQUEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["pacientes", "avisos_gerais"],
    "properties": {
        "avisos_gerais": {"type": "array", "items": {"type": "string"}},
        "pacientes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["nome_completo", "linhas_exames", "obs", "alerta_phoenix",
                         "prioridades", "pendencias"],
            "properties": {
                "nome_completo": {"type": "string"},
                "linhas_exames": {"type": "array", "items": {"type": "string"}},
                "obs": {"type": "string"},
                "alerta_phoenix": {"type": "array", "items": {"type": "string"}},
                "prioridades": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["nivel", "titulo", "itens"],
                    "properties": {
                        "nivel": {"type": "string", "enum": ["IMEDIATA", "PRIORITARIA", "MONITORAR"]},
                        "titulo": {"type": "string"},
                        "itens": {"type": "array", "items": {"type": "string"}},
                    }}},
                "pendencias": {"type": "array", "items": {"type": "string"}},
            }}},
    },
}


def digitar(cliente, modelo, prompt_digitar, prompt_uti, painel, laudos, agora):
    sistema = (
        "Você segue integralmente os dois prompts do médico abaixo.\n\n"
        f"===== IA PARA DIGITAR EXAMES =====\n{prompt_digitar}\n\n"
        f"===== IA UTI PED =====\n{prompt_uti}\n\n"
        "===== MODO AUTOMÁTICO (robô das 6h) =====\n"
        "Os laudos vêm do eLIS lidos por um robô, sem o médico presente. Setor: UTI — use a "
        "referência temporal da UTI definida na seção 3 (culturas: coleta e liberação). "
        "Para cada paciente: 'linhas_exames' = uma linha por conjunto/coleta, no formato "
        "'Nome Sobrenome, DD/MM (HH:MM): ...' com alterados em **negrito**; 'obs' = o parágrafo OBS; "
        "'alerta_phoenix' = itens do ALERTA PHOENIX (lista vazia se nada pontuar); 'prioridades' = "
        "módulo de condutas prioritárias, cada item com valor, data/hora, tendência, ação e "
        "situação PENDENTE DE CONFIRMAÇÃO; 'pendencias' = o que falta conferir. Use o painel atual "
        "apenas para tendências. Nunca invente valores; se um laudo estiver ilegível ou incompleto, "
        "diga isso em 'avisos_gerais'."
    )
    texto_laudos = "\n\n".join(
        f"----- {l['paciente']} | {l['descricao']} -----\n{l['texto']}" for l in laudos)
    usuario = (f"Data/hora desta execução: {agora}.\n\n"
               f"PAINEL ATUAL DE ROTINAS E CONTROLES (para tendências):\n{painel}\n\n"
               f"LAUDOS BRUTOS DO eLIS:\n{texto_laudos}\n\nDigite os exames.")
    with cliente.beta.messages.stream(
        model=modelo, max_tokens=64000, system=sistema,
        messages=[{"role": "user", "content": usuario}],
        thinking={"type": "adaptive"},
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": ESQUEMA}},
        betas=BETAS_FALLBACK, extra_body={"fallbacks": "default"},
    ) as stream:
        resp = stream.get_final_message()
    if resp.stop_reason == "refusal":
        raise RuntimeError("O Claude recusou a digitação.")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("Resposta da digitação cortada por tamanho.")
    return json.loads(next(b.text for b in resp.content if b.type == "text"))


def texto_simples(resultado: dict) -> str:
    """Versão em texto puro para colar direto no prontuário (arquivo local)."""
    partes = []
    for p in resultado["pacientes"]:
        partes.append("\n".join(p["linhas_exames"]))
        if p["obs"]:
            partes.append(f"OBS: {p['obs']}")
        if p["alerta_phoenix"]:
            partes.append("ALERTA PHOENIX:\n" + "\n".join(f"- {i}" for i in p["alerta_phoenix"]))
        partes.append("")
    return "\n\n".join(partes).replace("**", "")


# ---------------------------------------------------------------- principal

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teste", action="store_true",
                    help="mostra o navegador e não grava no Notion")
    args = ap.parse_args()

    for pasta in ("logs", "saidas"):
        (PASTA / pasta).mkdir(exist_ok=True)
    agora_dt = datetime.now()
    agora = agora_dt.strftime("%d/%m/%Y %H:%M")
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(PASTA / "logs" / f"{agora_dt:%Y-%m-%d_%H%M}.log", encoding="utf-8"),
                  logging.StreamHandler(sys.stdout)])

    cfg = configparser.ConfigParser()
    cfg.read(PASTA / "config.ini", encoding="utf-8")
    c_elis, c_notion, c_claude = cfg["elis"], cfg["notion"], cfg["claude"]
    modelo = c_claude.get("modelo", "claude-opus-5-5")

    cliente = anthropic.Anthropic(api_key=credenciais.obter("anthropic_api_key"))
    notion = Notion(credenciais.obter("notion_token"))

    log.info("Lendo prompts e painel no Notion...")
    prompt_digitar = notion.texto_da_pagina(c_notion["pagina_prompt_digitar"])
    prompt_uti = notion.texto_da_pagina(c_notion["pagina_prompt_uti_ped"])
    painel = notion.texto_da_pagina(c_notion["pagina_rotinas"])

    log.info("Entrando no eLIS...")
    elis = ELIS(c_elis, credenciais.obter("elis_usuario"), credenciais.obter("elis_senha"),
                visivel=args.teste)
    try:
        elis.login()
        desde = agora_dt - timedelta(hours=c_elis.getint("janela_horas", 24))
        navegar(cliente, modelo, elis, c_elis["setor"], desde, c_claude.getint("max_passos", 80))
        laudos = elis.laudos
    finally:
        elis.fechar()

    if not laudos:
        log.warning("Nenhum laudo encontrado no eLIS.")
        resultado = {"pacientes": [], "avisos_gerais": [
            "O robô não encontrou laudos novos no eLIS nesta execução. Conferir manualmente."]}
    else:
        log.info("Digitando %d laudos conforme os prompts...", len(laudos))
        resultado = digitar(cliente, modelo, prompt_digitar, prompt_uti, painel, laudos, agora)

    arquivo = PASTA / "saidas" / f"exames_{agora_dt:%Y-%m-%d_%H%M}.txt"
    arquivo.write_text(texto_simples(resultado), encoding="utf-8")
    log.info("Texto para o prontuário salvo em %s", arquivo)

    if args.teste:
        log.info("Modo teste: Notion não foi alterado.")
        return
    url = notion.criar_pagina(
        c_notion["pagina_rotinas"],
        f"RASCUNHO AUTOMÁTICO — exames {agora} (revisar)",
        montar_rascunho(resultado, laudos, agora))
    log.info("Rascunho criado no Notion: %s", url)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        log.exception("Falha na execução do robô")
        sys.exit(1)
