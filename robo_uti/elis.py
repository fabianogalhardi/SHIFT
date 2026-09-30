"""Acesso ao eLIS com Playwright: login automático e ferramentas de navegação
usadas pelo Claude para encontrar e ler os laudos da UTI (somente leitura)."""

import re

from playwright.sync_api import Page, sync_playwright

LIMITE_PAGINA = 25000  # caracteres por leitura de tela

# Palavras que o robô nunca clica: ele só consulta, jamais altera o sistema.
PROIBIDO = re.compile(
    r"liberar|excluir|apagar|deletar|cancelar|assinar|salvar|gravar|alterar|"
    r"confirmar|enviar|imprimir|recoleta|bloquear|desbloquear|inativar",
    re.IGNORECASE,
)

MARCAR_ELEMENTOS_JS = r"""
(inicio) => {
  const sel = 'a, button, select, input:not([type=hidden]):not([type=password]), ' +
              '[onclick], [role=button], [role=link], [role=tab], tr[onclick], td[onclick]';
  const itens = [];
  let n = inicio;
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const texto = (el.innerText || el.value || el.title || el.getAttribute('aria-label') ||
                   el.name || el.id || '').replace(/\s+/g, ' ').trim().slice(0, 80);
    el.setAttribute('data-robo-id', String(n));
    let tipo = el.tagName.toLowerCase();
    if (tipo === 'input') tipo += ':' + (el.type || 'text');
    if (tipo === 'select') {
      const ops = [...el.options].map(o => o.text.trim()).slice(0, 30).join(' / ');
      itens.push(`[${n}] select "${texto}" opções: ${ops}`);
    } else {
      itens.push(`[${n}] ${tipo} "${texto}"`);
    }
    n++;
  }
  return {itens, proximo: n};
}
"""


class ELIS:
    def __init__(self, cfg, usuario: str, senha: str, visivel: bool = False):
        self.cfg = cfg
        self.usuario, self.senha = usuario, senha
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=not visivel, slow_mo=150 if visivel else 0)
        self._ctx = self._browser.new_context(locale="pt-BR", viewport={"width": 1400, "height": 900})
        self._ctx.on("page", self._nova_aba)
        self.page: Page = self._ctx.new_page()
        self._prepara(self.page)
        self.laudos: list[dict] = []

    # ---------- infraestrutura ----------

    def _prepara(self, page: Page):
        # alertas simples são aceitos; confirmações ("tem certeza?") são recusadas
        page.on("dialog", lambda d: d.accept() if d.type == "alert" else d.dismiss())
        page.set_default_timeout(20000)

    def _nova_aba(self, page: Page):
        self._prepara(page)
        page.wait_for_load_state()
        self.page = page

    def fechar(self):
        try:
            self._browser.close()
        finally:
            self._pw.stop()

    def _esperar(self):
        try:
            self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

    # ---------- login ----------

    def login(self):
        c = self.cfg
        self.page.goto(c["url_login"])
        self._esperar()
        senha = self._primeiro_visivel(c.get("seletor_senha") or "input[type=password]")
        if senha is None:
            raise RuntimeError("Campo de senha não encontrado na tela de login do eLIS.")
        frame, campo_senha = senha
        if c.get("seletor_usuario"):
            campo_usuario = frame.locator(c["seletor_usuario"]).first
        else:
            # o campo de texto visível imediatamente antes da senha
            campo_usuario = frame.locator(
                "input[type=text], input:not([type])").filter(visible=True).first
        campo_usuario.fill(self.usuario)
        campo_senha.fill(self.senha)
        if c.get("seletor_botao_entrar"):
            frame.locator(c["seletor_botao_entrar"]).first.click()
        else:
            campo_senha.press("Enter")
        self._esperar()
        if self._primeiro_visivel("input[type=password]") is not None:
            raise RuntimeError(
                "O login no eLIS não foi aceito (a tela de senha continua aberta). "
                "Confira usuário/senha com configurar.bat.")

    def _primeiro_visivel(self, seletor):
        for frame in self.page.frames:
            loc = frame.locator(seletor).filter(visible=True)
            try:
                if loc.count():
                    return frame, loc.first
            except Exception:
                continue
        return None

    # ---------- ferramentas para o Claude ----------

    def ler_tela(self, parte: int = 1) -> str:
        blocos, proximo = [], 0
        for i, frame in enumerate(self.page.frames):
            try:
                marcados = frame.evaluate(MARCAR_ELEMENTOS_JS, proximo)
                texto = frame.locator("body").inner_text(timeout=5000)
            except Exception:
                continue
            proximo = marcados["proximo"]
            nome = "principal" if i == 0 else f"quadro {i} ({frame.name or frame.url[-60:]})"
            blocos.append(f"=== {nome} ===\nTEXTO:\n{texto.strip()}\n\nELEMENTOS CLICÁVEIS:\n"
                          + "\n".join(marcados["itens"]))
        completo = f"URL: {self.page.url}\nTÍTULO: {self.page.title()}\n\n" + "\n\n".join(blocos)
        total = max(1, -(-len(completo) // LIMITE_PAGINA))
        parte = min(max(parte, 1), total)
        trecho = completo[(parte - 1) * LIMITE_PAGINA: parte * LIMITE_PAGINA]
        return f"[parte {parte} de {total}]\n{trecho}"

    def _elemento(self, n: int):
        for frame in self.page.frames:
            loc = frame.locator(f'[data-robo-id="{n}"]')
            try:
                if loc.count():
                    return loc.first
            except Exception:
                continue
        raise ValueError(f"Elemento [{n}] não existe mais; use ler_tela de novo.")

    def clicar(self, n: int) -> str:
        el = self._elemento(n)
        rotulo = (el.inner_text(timeout=3000) or el.get_attribute("value") or "").strip()
        if PROIBIDO.search(rotulo):
            return f"BLOQUEADO: o robô é somente leitura e não clica em '{rotulo}'."
        el.click()
        self._esperar()
        return "ok — leia a tela de novo para ver o resultado."

    def digitar(self, n: int, texto: str) -> str:
        self._elemento(n).fill(texto)
        return "ok"

    def selecionar(self, n: int, opcao: str) -> str:
        self._elemento(n).select_option(label=opcao)
        self._esperar()
        return "ok"

    def voltar(self) -> str:
        self.page.go_back()
        self._esperar()
        return "ok"

    def salvar_laudo(self, paciente: str, descricao: str) -> str:
        # Guarda o texto da tela exatamente como está no eLIS (não o que a IA
        # leu), para que a digitação parta sempre do laudo original.
        textos = []
        for frame in self.page.frames:
            try:
                textos.append(frame.locator("body").inner_text(timeout=5000).strip())
            except Exception:
                continue
        texto = "\n\n".join(t for t in textos if t)
        self.laudos.append({"paciente": paciente, "descricao": descricao, "texto": texto})
        return f"laudo salvo ({len(self.laudos)} até agora)."
