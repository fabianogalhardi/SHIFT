"""Senhas e chaves guardadas no Gerenciador de Credenciais do Windows (keyring)."""

import getpass

import keyring

SERVICO = "robo_uti"

CAMPOS = {
    "elis_usuario": "Usuário do eLIS",
    "elis_senha": "Senha do eLIS",
    "anthropic_api_key": "Chave da API do Claude (começa com sk-ant-)",
    "notion_token": "Token da integração do Notion (começa com ntn_ ou secret_)",
}
SECRETOS = {"elis_senha", "anthropic_api_key", "notion_token"}


def obter(campo: str) -> str:
    valor = keyring.get_password(SERVICO, campo)
    if not valor:
        raise SystemExit(
            f"Credencial '{CAMPOS[campo]}' não configurada. Rode configurar.bat primeiro."
        )
    return valor


def configurar() -> None:
    print("Configuração das credenciais do robô (Enter mantém o valor atual).\n")
    for campo, rotulo in CAMPOS.items():
        atual = keyring.get_password(SERVICO, campo)
        sufixo = " [já configurado]" if atual else ""
        pergunta = f"{rotulo}{sufixo}: "
        valor = getpass.getpass(pergunta) if campo in SECRETOS else input(pergunta)
        valor = valor.strip()
        if valor:
            keyring.set_password(SERVICO, campo, valor)
        elif not atual:
            print(f"  Aviso: '{rotulo}' ficou em branco.")
    print("\nCredenciais salvas no Gerenciador de Credenciais do Windows.")


if __name__ == "__main__":
    configurar()
