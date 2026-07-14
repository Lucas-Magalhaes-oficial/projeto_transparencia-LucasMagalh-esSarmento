import csv
import io
import re
import zipfile
from pathlib import Path

import requests

from banco import conectar, executar, inserir_em_lote
from config import (
    ARQUIVOS,
    CSV_ENCODING,
    CSV_SEPARADOR,
    DRIVE_FILE_ID,
    PASTA_DADOS,
    TAMANHO_BLOCO,
)

URL_DOWNLOAD_DRIVE = "https://drive.google.com/uc"
CAMINHO_ZIP = PASTA_DADOS / "dados_transparencia.zip"


# ---------------------------------------------------------------------------
# Download do .zip no Google Drive
# ---------------------------------------------------------------------------
def _resolver_pagina_de_confirmacao(sessao, resposta, destino: Path):
    """
    Para arquivos grandes, o Drive retorna uma pagina HTML de aviso
    ('nao foi possivel verificar virus') em vez do arquivo. Essa pagina
    tem um formulario escondido que, se reenviado, libera o download real.
    Essa funcao detecta esse caso, resolve o formulario e refaz a
    requisicao. Se a resposta ja for o arquivo, apenas a devolve.
    """
    tipo_conteudo = resposta.headers.get("Content-Type", "")
    if "text/html" not in tipo_conteudo:
        return resposta  # já é o arquivo binário, nada a fazer

    html = resposta.text
    acao = re.search(r'action="([^"]+)"', html)
    campos = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', html))

    if not acao:
        # salva a resposta bruta pra facilitar diagnostico, caso precise investigar
        debug_path = destino.parent / "_debug_resposta_drive.html"
        debug_path.write_text(html, encoding="utf-8", errors="ignore")
        raise RuntimeError(
            "O Google Drive retornou uma página HTML em vez do arquivo, e não foi "
            "possível encontrar o formulário de confirmação. Verifique se o link do "
            "arquivo está compartilhado como 'Qualquer pessoa com o link'. "
            f"A resposta foi salva em '{debug_path}' para diagnóstico."
        )

    url_confirmada = acao.group(1).replace("&amp;", "&")
    return sessao.get(url_confirmada, params=campos, stream=True)


def baixar_zip_do_drive(file_id, destino: Path):
    """Baixa o arquivo do Google Drive para 'destino', tratando arquivos grandes."""
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)

        sessao = requests.Session()
        resposta = sessao.get(
            URL_DOWNLOAD_DRIVE, params={"id": file_id, "export": "download"}, stream=True
        )
        resposta.raise_for_status()

        resposta = _resolver_pagina_de_confirmacao(sessao, resposta, destino)
        resposta.raise_for_status()

        with open(destino, "wb") as arquivo:
            for pedaco in resposta.iter_content(chunk_size=1024 * 1024):
                if pedaco:
                    arquivo.write(pedaco)

        tamanho_mb = destino.stat().st_size / 1_048_576
        if tamanho_mb < 0.5 or not zipfile.is_zipfile(destino):
            raise RuntimeError(
                f"O download terminou, mas o arquivo salvo ({tamanho_mb:.2f} MB) não "
                "parece ser um .zip válido. Confira se o link do Drive está "
                "compartilhado como 'Qualquer pessoa com o link' e se o "
                "DRIVE_FILE_ID no config.py está correto."
            )

        print(f"[OK] Download concluido: {destino.name} ({tamanho_mb:.1f} MB)")

    except requests.RequestException as erro:
        raise RuntimeError(
            f"Falha ao baixar o arquivo do Google Drive (id={file_id}). "
            f"Verifique sua conexao e se o link esta com acesso publico. Detalhe: {erro}"
        )


# ---------------------------------------------------------------------------
# Leitura do CSV (dentro do zip) e carga em blocos na tabela Raw
# ---------------------------------------------------------------------------
def carregar_csv_para_raw(conexao, zip_ref, nome_csv, tabela_raw):
    """Le um CSV de dentro do zip em blocos e insere na tabela Raw correspondente."""
    with zip_ref.open(nome_csv) as arquivo_bin:
        texto = io.TextIOWrapper(arquivo_bin, encoding=CSV_ENCODING, newline="")
        leitor = csv.reader(texto, delimiter=CSV_SEPARADOR)

        cabecalho = next(leitor)
        num_colunas = len(cabecalho)
        placeholders = ", ".join(["%s"] * num_colunas)
        sql_insert = f"INSERT INTO {tabela_raw} VALUES ({placeholders})"

        total_inserido = 0
        bloco = []

        for linha in leitor:
            # protege contra linhas quebradas/incompletas no fim do arquivo
            if len(linha) != num_colunas:
                continue
            bloco.append(tuple(linha))

            if len(bloco) >= TAMANHO_BLOCO:
                inserir_em_lote(conexao, sql_insert, bloco)
                total_inserido += len(bloco)
                bloco = []

        if bloco:
            inserir_em_lote(conexao, sql_insert, bloco)
            total_inserido += len(bloco)

        print(f"[OK] {tabela_raw}: {total_inserido} linhas carregadas de {nome_csv}")


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------
def main():
    print("=== Fase 1: Extração e carga na camada Raw ===")

    baixar_zip_do_drive(DRIVE_FILE_ID, CAMINHO_ZIP)

    conexao = conectar()

    try:
        with zipfile.ZipFile(CAMINHO_ZIP) as zip_ref:
            nomes_no_zip = zip_ref.namelist()

            for chave, info in ARQUIVOS.items():
                nome_csv = info["csv"]
                tabela_raw = info["tabela_raw"]

                if nome_csv not in nomes_no_zip:
                    print(f"[AVISO] '{nome_csv}' nao encontrado dentro do zip. Pulando.")
                    continue

                try:
                    # TRUNCATE antes de carregar: garante idempotencia
                    executar(conexao, f"TRUNCATE TABLE {tabela_raw};")
                    carregar_csv_para_raw(conexao, zip_ref, nome_csv, tabela_raw)
                except Exception as erro:
                    print(f"[ERRO] Falha ao processar '{nome_csv}' -> '{tabela_raw}': {erro}")

    finally:
        conexao.close()

    print("=== Fase 1 concluída ===")


if __name__ == "__main__":
    main()