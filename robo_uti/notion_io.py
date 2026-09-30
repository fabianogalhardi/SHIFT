"""Leitura dos prompts e escrita do rascunho no Notion (API oficial)."""

import re

import requests

API = "https://api.notion.com/v1"
VERSAO = "2022-06-28"
LIMITE_TEXTO = 1900  # a API aceita até 2000 caracteres por trecho de texto
LIMITE_BLOCOS = 100  # por requisição

CORES = {"IMEDIATA": ("🔴", "red_background"),
         "PRIORITARIA": ("🟠", "orange_background"),
         "MONITORAR": ("🟡", "yellow_background")}
ROTULOS = {"IMEDIATA": "IMEDIATA", "PRIORITARIA": "PRIORITÁRIA",
           "MONITORAR": "MONITORAR / CONFERIR"}


class Notion:
    def __init__(self, token: str):
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {token}",
            "Notion-Version": VERSAO,
            "Content-Type": "application/json",
        })

    def _req(self, metodo, caminho, **kw):
        r = self.s.request(metodo, API + caminho, timeout=60, **kw)
        if r.status_code == 404:
            raise SystemExit(
                "Notion: página não encontrada. Conecte a integração às páginas "
                "PROMPTS e ROTINAS E CONTROLES (menu ••• > Conexões)."
            )
        r.raise_for_status()
        return r.json()

    # ---------- leitura ----------

    def texto_da_pagina(self, page_id: str) -> str:
        linhas: list[str] = []
        self._ler_blocos(page_id, linhas, 0)
        return "\n".join(linhas)

    def _ler_blocos(self, bloco_id, linhas, nivel):
        cursor = None
        while True:
            params = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            dados = self._req("GET", f"/blocks/{bloco_id}/children", params=params)
            for b in dados["results"]:
                linhas.append("  " * nivel + _texto_do_bloco(b))
                if b.get("has_children") and b["type"] != "child_page":
                    self._ler_blocos(b["id"], linhas, nivel + 1)
            if not dados.get("has_more"):
                break
            cursor = dados["next_cursor"]

    # ---------- escrita ----------

    def criar_pagina(self, pai_id: str, titulo: str, blocos: list[dict]) -> str:
        pagina = self._req("POST", "/pages", json={
            "parent": {"page_id": pai_id},
            "icon": {"type": "emoji", "emoji": "🤖"},
            "properties": {"title": {"title": _rich(titulo)}},
            "children": blocos[:LIMITE_BLOCOS],
        })
        for i in range(LIMITE_BLOCOS, len(blocos), LIMITE_BLOCOS):
            self._req("PATCH", f"/blocks/{pagina['id']}/children",
                      json={"children": blocos[i:i + LIMITE_BLOCOS]})
        return pagina["url"]


def _texto_do_bloco(b: dict) -> str:
    tipo = b["type"]
    conteudo = b.get(tipo, {})
    texto = "".join(t.get("plain_text", "") for t in conteudo.get("rich_text", []))
    prefixos = {"heading_1": "# ", "heading_2": "## ", "heading_3": "### ",
                "bulleted_list_item": "- ", "numbered_list_item": "1. ",
                "to_do": "- [ ] ", "quote": "> "}
    if tipo == "callout":
        icone = (conteudo.get("icon") or {}).get("emoji", "")
        return f"[caixa {icone}] {texto}"
    if tipo == "table_row":
        return " | ".join("".join(t["plain_text"] for t in c) for c in conteudo["cells"])
    if tipo == "child_page":
        return f"[subpágina: {conteudo.get('title', '')}]"
    return prefixos.get(tipo, "") + texto


def _rich(texto: str) -> list[dict]:
    """Converte **negrito** em anotações do Notion, respeitando o limite de tamanho."""
    partes = []
    for i, trecho in enumerate(re.split(r"\*\*", texto)):
        for j in range(0, len(trecho), LIMITE_TEXTO):
            pedaco = trecho[j:j + LIMITE_TEXTO]
            if pedaco:
                partes.append({"type": "text", "text": {"content": pedaco},
                               "annotations": {"bold": i % 2 == 1}})
    return partes or [{"type": "text", "text": {"content": ""}}]


def _bloco(tipo: str, texto: str, **extra) -> dict:
    return {"object": "block", "type": tipo, tipo: {"rich_text": _rich(texto), **extra}}


def montar_rascunho(resultado: dict, laudos: list[dict], agora: str) -> list[dict]:
    """Monta os blocos do rascunho a partir da saída estruturada do Claude."""
    blocos = [_bloco(
        "callout",
        f"**RASCUNHO AUTOMÁTICO — gerado às {agora}. REVISAR ANTES DE USAR.** "
        "Transcrição feita por IA a partir do eLIS; conferir cada valor com o laudo "
        "original. Nada aqui confirma que uma conduta foi realizada.",
        icon={"type": "emoji", "emoji": "⚠️"}, color="gray_background",
    )]
    for aviso in resultado.get("avisos_gerais", []):
        blocos.append(_bloco("bulleted_list_item", aviso))

    for p in resultado.get("pacientes", []):
        blocos.append(_bloco("heading_2", p["nome_completo"].upper()))
        blocos.append(_bloco("heading_3", "Exames laboratoriais — digitação"))
        for linha in p["linhas_exames"]:
            blocos.append(_bloco("paragraph", linha))
        if p.get("obs"):
            blocos.append(_bloco("paragraph", f"OBS: {p['obs']}"))
        if p.get("alerta_phoenix"):
            blocos.append(_bloco("paragraph", "**ALERTA PHOENIX:**"))
            for item in p["alerta_phoenix"]:
                blocos.append(_bloco("bulleted_list_item", item))
        if p.get("prioridades"):
            blocos.append(_bloco("heading_3", f"PRIORIDADES / CONDUTAS IMEDIATAS — {agora}"))
            ordem = {"IMEDIATA": 0, "PRIORITARIA": 1, "MONITORAR": 2}
            for pr in sorted(p["prioridades"], key=lambda x: ordem[x["nivel"]]):
                icone, cor = CORES[pr["nivel"]]
                filhos = [_bloco("bulleted_list_item", i) for i in pr["itens"]]
                bloco = _bloco("callout", f"**{ROTULOS[pr['nivel']]} — {pr['titulo']}**",
                               icon={"type": "emoji", "emoji": icone}, color=cor)
                bloco["callout"]["children"] = filhos[:LIMITE_BLOCOS]
                blocos.append(bloco)
        for pend in p.get("pendencias", []):
            blocos.append(_bloco("to_do", pend, checked=False))

    if laudos:
        filhos = []
        for l in laudos:
            filhos.append(_bloco("paragraph", f"**{l['paciente']} — {l['descricao']}**"))
            filhos.append(_bloco("paragraph", l["texto"]))
        toggle = _bloco("toggle", "Laudos brutos lidos do eLIS (para conferência)")
        toggle["toggle"]["children"] = filhos[:LIMITE_BLOCOS]
        blocos.append(toggle)
    return blocos
