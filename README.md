# Pipeline de Dados — Viagens a Serviço (Portal da Transparência)

Projeto avaliativo da disciplina de Análise de Dados com Python — Módulo 1.
Pipeline de dados completo (ETL) usando a Arquitetura Medallion (Raw, Silver
e Gold), construído em Python + PostgreSQL.

## Qual problema o projeto resolve

O Portal da Transparência do Governo Federal disponibiliza os dados de
"Viagens a Serviço" em formato bruto (CSV), desorganizado e sem qualquer
tratamento. Este projeto simula o trabalho de uma consultoria de dados
contratada para transformar esses dados brutos em informação confiável,
permitindo que o governo (e o cidadão) responda perguntas reais sobre os
gastos públicos com viagens: quais órgãos gastam mais, quais destinos são
mais caros, qual o perfil de pagamentos e deslocamentos, entre outras.

## Técnicas e tecnologias utilizadas

- **Python 3** — extração, transformação e análise
- **PostgreSQL** — banco de dados relacional
- **psycopg2** — conexão do Python com o PostgreSQL
- **pandas** — manipulação de dados e leitura de resultados SQL
- **matplotlib** — visualização de dados (gráficos)
- **Jupyter Notebook** — análise exploratória e apresentação dos resultados
- **Arquitetura Medallion** (Raw → Silver → Gold) para organização das
  camadas de dados
- **Git/GitHub** — versionamento, com branches por funcionalidade

### Arquitetura do pipeline

```mermaid
flowchart LR
    A[Google Drive<br/>.zip com 4 CSVs] -->|1_extrair.py| B[(Camada Raw<br/>dados brutos, VARCHAR)]
    B -->|2_transformar.py| C[(Camada Silver<br/>tipado, PK/FK/constraints)]
    C -->|3_analise.ipynb| D[(Camada Gold<br/>agregada: tabela + view)]
    D --> E[Perguntas de negócio<br/>+ gráficos]
```

- **Raw** (`raw_viagem`, `raw_pagamento`, `raw_passagem`, `raw_trecho`):
  cópia fiel dos CSVs, tudo como texto, sem alterar o conteúdo original.
- **Silver** (`silver_viagem`, `silver_pagamento`, `silver_passagem`,
  `silver_trecho`): dados tipados (`DATE`, `DECIMAL`), com chave primária,
  chave estrangeira e constraints (`NOT NULL`, `CHECK`, `UNIQUE`).
- **Gold** (`gold_orgao_destino`, tabela e view): agregação por órgão e UF
  de destino, construída com `JOIN` + `GROUP BY` sobre a Silver.

## Como executar

### Pré-requisitos
- Python 3.11+
- PostgreSQL instalado e rodando localmente (ou acessível via rede)

### Passo a passo

1. Clone o repositório e entre na pasta do projeto.
2. Instale as dependências:
   ```
   pip install -r requirements.txt
   ```
3. Copie `.env.example` para `.env` e preencha com as credenciais do seu
   PostgreSQL:
   ```
   POSTGRES_HOST=localhost
   POSTGRES_PORT=5432
   POSTGRES_USER=postgres
   POSTGRES_PASSWORD=sua_senha_aqui
   POSTGRES_DATABASE=transparencia
   ```
4. Crie o banco `transparencia` (via pgAdmin ou `CREATE DATABASE`) e rode
   o script `0_criar_banco.sql` nele — cria as 8 tabelas (Raw + Silver).
5. Rode a extração (baixa o zip do Google Drive automaticamente e carrega
   a Raw):
   ```
   python 1_extrair.py
   ```
6. Rode a transformação (Raw → Silver):
   ```
   python 2_transformar.py
   ```
7. Abra `3_analise.ipynb` (recomendado: VS Code com a extensão Jupyter) e
   rode todas as células ("Run All") — cria a camada Gold e responde as
   perguntas de negócio com tabelas e gráficos.

Todo o pipeline é **idempotente**: rodar `1_extrair.py` ou
`2_transformar.py` de novo não duplica nenhum dado (ambos fazem
`TRUNCATE` antes de recarregar).

## Perguntas de negócio respondidas

1. Qual a viagem de maior duração e qual foi o seu custo total?
2. Qual o tipo de pagamento com maior valor médio?
3. Qual o meio de transporte mais usado nos trechos?
4. Quais os 5 órgãos com maior custo total?
5. Quais os 3 destinos (UF) com maior custo médio por viagem?
6. Qual UF de destino aparece em mais trechos?
7. Qual órgão pagou mais no total?

## Conclusões e insights

- **Concentração de custos**: o Ministério da Justiça e Segurança Pública
  lidera o custo total em viagens por uma margem considerável em relação
  ao 2º colocado (Ministério da Defesa) — mais de 3x maior.
- **Órgão do viajante ≠ órgão pagador**: o órgão que mais *pagou* no total
  (Fundo Nacional de Segurança Pública) é diferente do órgão com maior
  custo total de viagens vinculadas a ele. Isso mostra que convênios e
  fundos específicos frequentemente bancam viagens de servidores
  formalmente lotados em outros órgãos.
- **Custo por destino não é proporcional à frequência**: os destinos mais
  "visitados" (São Paulo, Distrito Federal) não são os mais caros em
  média — na verdade, os destinos com maior custo médio por viagem são
  estados do Norte (Roraima, Acre, Rondônia), provavelmente por causa da
  distância e do custo logístico de chegar até lá.
- **Veículo oficial domina os deslocamentos**: mais da metade dos trechos
  registrados usam veículo oficial, com deslocamento aéreo em segundo
  lugar — sugerindo que boa parte das viagens é de curta/média distância
  dentro do território nacional.
- **Diárias são o tipo de pagamento mais caro em média**, à frente de
  passagens — o que faz sentido, já que diárias costumam ser pagas por
  vários dias de uma vez, enquanto passagens são um valor único por
  trecho.

## Possíveis melhorias futuras

- Adicionar testes automatizados (ex: `pytest`) para as funções de
  conversão e carga.
- Parametrizar o pipeline para aceitar diferentes períodos/anos, não só
  o zip fixo de 2025.
- Adicionar uma camada de qualidade de dados (ex: relatório automático de
  quantos valores viraram `NULL` em cada carga).
- Orquestrar as 3 fases com uma ferramenta como Airflow ou Prefect, em vez
  de rodar os scripts manualmente em sequência.
- Adicionar mais dimensões na camada Gold (ex: por mês, por cargo do
  viajante).

## Estrutura do repositório

```
├── 0_criar_banco.sql      # Fase 0: cria banco e 8 tabelas (Raw + Silver)
├── 1_extrair.py           # Fase 1: baixa o zip e carrega a Raw
├── 2_transformar.py       # Fase 2: transforma Raw -> Silver
├── 3_analise.ipynb        # Fase 3: cria a Gold e responde perguntas de negócio
├── banco.py               # funções utilitárias de conexão com o PostgreSQL
├── config.py               # configurações e leitura do .env
├── requirements.txt        # dependências do projeto
├── .env.example             # modelo de variáveis de ambiente
└── .gitignore                # ignora .env, dados brutos e cache
```
