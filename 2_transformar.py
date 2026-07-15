from datetime import datetime
from decimal import Decimal, InvalidOperation

from banco import conectar, executar, inserir_em_lote
from config import TAMANHO_BLOCO


# ---------------------------------------------------------------------------
# Funções de conversão (texto -> tipo), resilientes a valores vazios/invalidos
# ---------------------------------------------------------------------------
def converter_decimal(texto):
    """Converte texto no formato brasileiro (ex: '1272,97') para Decimal."""
    if texto is None:
        return None
    limpo = texto.strip()
    if not limpo:
        return None
    if "," in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    try:
        return Decimal(limpo)
    except InvalidOperation:
        return None


def converter_data(texto):
    """Converte texto no formato DD/MM/AAAA para date."""
    if texto is None:
        return None
    limpo = texto.strip()
    if not limpo:
        return None
    try:
        return datetime.strptime(limpo, "%d/%m/%Y").date()
    except ValueError:
        return None


def converter_inteiro(texto):
    """Converte texto para int, com tolerancia a vazio/invalido."""
    if texto is None:
        return None
    limpo = texto.strip()
    if not limpo:
        return None
    try:
        return int(limpo)
    except ValueError:
        return None


def somar_valores(*valores):
    """Soma valores Decimal ignorando None; retorna None se todos forem None."""
    presentes = [v for v in valores if v is not None]
    if not presentes:
        return None
    return sum(presentes)


def calcular_duracao_dias(data_inicio, data_fim):
    """Calcula a duracao em dias entre duas datas, se ambas existirem."""
    if data_inicio is None or data_fim is None:
        return None
    return (data_fim - data_inicio).days


# ---------------------------------------------------------------------------
# Leitura em blocos das tabelas Raw (cursor de servidor)
# ---------------------------------------------------------------------------
def ler_raw_em_blocos(conexao, tabela, nome_cursor):
    """Abre um cursor de servidor e devolve um gerador que produz blocos de linhas."""
    cursor = conexao.cursor(name=nome_cursor)
    cursor.itersize = TAMANHO_BLOCO
    cursor.execute(f"SELECT * FROM {tabela};")

    while True:
        bloco = cursor.fetchmany(TAMANHO_BLOCO)
        if not bloco:
            break
        yield bloco

    cursor.close()


# ---------------------------------------------------------------------------
# silver_viagem (tabela pai - processada primeiro)
# ---------------------------------------------------------------------------
def transformar_silver_viagem(conexao_leitura, conexao_escrita):
    sql_insert = """
        INSERT INTO silver_viagem (
            id_viagem, num_proposta, situacao, viagem_urgente, cod_orgao_superior,
            nome_orgao_superior, nome_viajante, cargo, data_inicio, data_fim,
            destinos, motivo, valor_diarias, valor_passagens, valor_devolucao,
            valor_outros_gastos, valor_total, duracao_dias
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id_viagem) DO NOTHING
    """

    ids_validos = set()
    total = 0

    for bloco_raw in ler_raw_em_blocos(conexao_leitura, "raw_viagem", "cursor_raw_viagem"):
        bloco_silver = []
        for linha in bloco_raw:
            (
                identificador_processo_viagem, numero_proposta_pcdp, situacao,
                viagem_urgente, _justificativa, codigo_orgao_superior,
                nome_orgao_superior, _cod_orgao_solic, _nome_orgao_solic,
                _cpf_viajante, nome, cargo, _funcao, _descricao_funcao,
                periodo_data_inicio, periodo_data_fim, destinos, motivo,
                valor_diarias, valor_passagens, valor_devolucao, valor_outros_gastos,
            ) = linha

            id_viagem = identificador_processo_viagem.strip()
            data_inicio = converter_data(periodo_data_inicio)
            data_fim = converter_data(periodo_data_fim)
            v_diarias = converter_decimal(valor_diarias)
            v_passagens = converter_decimal(valor_passagens)
            v_devolucao = converter_decimal(valor_devolucao)
            v_outros = converter_decimal(valor_outros_gastos)
            valor_total = somar_valores(v_diarias, v_passagens, v_devolucao, v_outros)
            duracao_dias = calcular_duracao_dias(data_inicio, data_fim)

            ids_validos.add(id_viagem)

            bloco_silver.append((
                id_viagem, numero_proposta_pcdp.strip(), situacao, viagem_urgente,
                codigo_orgao_superior, nome_orgao_superior, nome, cargo,
                data_inicio, data_fim, destinos, motivo, v_diarias, v_passagens,
                v_devolucao, v_outros, valor_total, duracao_dias,
            ))

        inserir_em_lote(conexao_escrita, sql_insert, bloco_silver)
        total += len(bloco_silver)

    print(f"[OK] silver_viagem: {total} linhas processadas")
    return ids_validos


# ---------------------------------------------------------------------------
# silver_pagamento (tabela filha)
# ---------------------------------------------------------------------------
def transformar_silver_pagamento(conexao_leitura, conexao_escrita, ids_validos):
    sql_insert = """
        INSERT INTO silver_pagamento (
            id_viagem, num_proposta, nome_orgao_pagador, nome_ug_pagadora,
            tipo_pagamento, valor
        ) VALUES (%s, %s, %s, %s, %s, %s)
    """

    total, descartadas = 0, 0

    for bloco_raw in ler_raw_em_blocos(conexao_leitura, "raw_pagamento", "cursor_raw_pagamento"):
        bloco_silver = []
        for linha in bloco_raw:
            (
                identificador_processo_viagem, numero_proposta_pcdp,
                _cod_orgao_sup, _nome_orgao_sup, _cod_orgao_pag,
                nome_orgao_pagador, _cod_ug, nome_ug_pagadora,
                tipo_pagamento, valor,
            ) = linha

            id_viagem = identificador_processo_viagem.strip()
            if id_viagem not in ids_validos:
                descartadas += 1
                continue

            bloco_silver.append((
                id_viagem, numero_proposta_pcdp.strip(), nome_orgao_pagador,
                nome_ug_pagadora, tipo_pagamento, converter_decimal(valor),
            ))

        inserir_em_lote(conexao_escrita, sql_insert, bloco_silver)
        total += len(bloco_silver)

    print(
        f"[OK] silver_pagamento: {total} linhas carregadas "
        f"({descartadas} sem viagem correspondente)"
    )


# ---------------------------------------------------------------------------
# silver_passagem (tabela filha)
# ---------------------------------------------------------------------------
def transformar_silver_passagem(conexao_leitura, conexao_escrita, ids_validos):
    sql_insert = """
        INSERT INTO silver_passagem (
            id_viagem, meio_transporte, pais_origem_ida, uf_origem_ida,
            cidade_origem_ida, pais_destino_ida, uf_destino_ida, cidade_destino_ida,
            valor_passagem, taxa_servico, data_emissao
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    total, descartadas = 0, 0

    for bloco_raw in ler_raw_em_blocos(conexao_leitura, "raw_passagem", "cursor_raw_passagem"):
        bloco_silver = []
        for linha in bloco_raw:
            (
                identificador_processo_viagem, _numero_proposta, meio_transporte,
                pais_origem_ida, uf_origem_ida, cidade_origem_ida,
                pais_destino_ida, uf_destino_ida, cidade_destino_ida,
                _pais_origem_volta, _uf_origem_volta, _cidade_origem_volta,
                _pais_destino_volta, _uf_destino_volta, _cidade_destino_volta,
                valor_passagem, taxa_servico, data_emissao, _hora_emissao,
            ) = linha

            id_viagem = identificador_processo_viagem.strip()
            if id_viagem not in ids_validos:
                descartadas += 1
                continue

            bloco_silver.append((
                id_viagem, meio_transporte, pais_origem_ida, uf_origem_ida,
                cidade_origem_ida, pais_destino_ida, uf_destino_ida, cidade_destino_ida,
                converter_decimal(valor_passagem), converter_decimal(taxa_servico),
                converter_data(data_emissao),
            ))

        inserir_em_lote(conexao_escrita, sql_insert, bloco_silver)
        total += len(bloco_silver)

    print(
        f"[OK] silver_passagem: {total} linhas carregadas "
        f"({descartadas} sem viagem correspondente)"
    )


# ---------------------------------------------------------------------------
# silver_trecho (tabela filha)
# ---------------------------------------------------------------------------
def transformar_silver_trecho(conexao_leitura, conexao_escrita, ids_validos):
    sql_insert = """
        INSERT INTO silver_trecho (
            id_viagem, sequencia_trecho, origem_data, origem_uf, origem_cidade,
            destino_data, destino_uf, destino_cidade, meio_transporte, numero_diarias
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id_viagem, sequencia_trecho) DO NOTHING
    """

    total, descartadas = 0, 0

    for bloco_raw in ler_raw_em_blocos(conexao_leitura, "raw_trecho", "cursor_raw_trecho"):
        bloco_silver = []
        for linha in bloco_raw:
            (
                identificador_processo_viagem, _numero_proposta, sequencia_trecho,
                origem_data, _origem_pais, origem_uf, origem_cidade,
                destino_data, _destino_pais, destino_uf, destino_cidade,
                meio_transporte, numero_diarias, _missao,
            ) = linha

            id_viagem = identificador_processo_viagem.strip()
            if id_viagem not in ids_validos:
                descartadas += 1
                continue

            bloco_silver.append((
                id_viagem, converter_inteiro(sequencia_trecho),
                converter_data(origem_data), origem_uf, origem_cidade,
                converter_data(destino_data), destino_uf, destino_cidade,
                meio_transporte, converter_decimal(numero_diarias),
            ))

        inserir_em_lote(conexao_escrita, sql_insert, bloco_silver)
        total += len(bloco_silver)

    print(
        f"[OK] silver_trecho: {total} linhas carregadas "
        f"({descartadas} sem viagem correspondente)"
    )


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------
def main():
    print("=== Fase 2: Transformação e carga na camada Silver ===")

    # Duas conexoes separadas: uma so pra LER a Raw (cursor de servidor,
    # nao pode ter commit no meio) e outra so pra ESCREVER na Silver
    # (cada bloco inserido da commit). Usar a mesma conexao pras duas
    # coisas invalida o cursor de leitura no meio do processo.
    conexao_leitura = conectar()
    conexao_escrita = conectar()

    try:
        # TRUNCATE nas 4 tabelas de uma vez (CASCADE cuida da ordem de FK)
        executar(
            conexao_escrita,
            "TRUNCATE TABLE silver_viagem, silver_pagamento, "
            "silver_passagem, silver_trecho RESTART IDENTITY CASCADE;",
        )

        # Tabela pai primeiro: precisamos do conjunto de ids validos
        # antes de processar as tabelas filhas (integridade referencial).
        try:
            ids_validos = transformar_silver_viagem(conexao_leitura, conexao_escrita)
        except Exception as erro:
            raise RuntimeError(f"Falha ao transformar silver_viagem: {erro}")

        for nome_tabela, funcao in (
            ("silver_pagamento", transformar_silver_pagamento),
            ("silver_passagem", transformar_silver_passagem),
            ("silver_trecho", transformar_silver_trecho),
        ):
            try:
                funcao(conexao_leitura, conexao_escrita, ids_validos)
            except Exception as erro:
                print(f"[ERRO] Falha ao transformar {nome_tabela}: {erro}")

    finally:
        conexao_leitura.close()
        conexao_escrita.close()

    print("=== Fase 2 concluída ===")


if __name__ == "__main__":
    main()